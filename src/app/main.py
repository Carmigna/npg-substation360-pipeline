from fastapi import FastAPI
from loguru import logger
from sqlalchemy import text
import datetime as dt
from datetime import UTC
from src.app.sync.cloud import cloud_health, cloud_init, sync as cloud_sync
from src.app.config import settings

from src.app.clients.substation360 import (
    get_token, list_instruments,
    voltage_mean_30min, current_mean_30min
)
from src.app.db.session import SessionLocal
from src.app.db.models import Instrument as DBInstrument, RawMeasurement
from src.app.ingest.normalize import (
    normalize_voltage_mean_30min, normalize_current_mean_30min
)

app = FastAPI(title="NPG Substation360 Pipeline Demo", version="0.1.3")

@app.get("/healthz", summary="Healthz")
def healthz():
    return {"status": "ok"}

# -----------------------
# helpers
# -----------------------
def _as_list(raw):
    """Normalize vendor responses to a list."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("items", "data", "results", "instruments"):
            if key in raw and isinstance(raw[key], list):
                return raw[key]
        return [raw]
    return []

def _iid(i: dict) -> int | None:
    """
    Extract an integer instrument id; the deployment you showed uses 'instrumentId'.
    Fall back to other common keys so this stays robust across tenants.
    """
    for k in (
        "instrumentId", "InstrumentId", "instrumentID", "instrument_id",
        "id", "deviceId", "DeviceId", "assetId", "AssetId"
    ):
        v = i.get(k)
        if v is not None:
            try:
                return int(v)
            except Exception:
                logger.warning("Non-integer id in key {}: {}", k, v)
                return None
    return None

def _iname(i: dict, iid: int | None) -> str | None:
    """
    Derive a display name. Prefer vendor-provided names/tags; as a last resort
    synthesize 'instrument-<id>'.
    """
    name = (
        i.get("name")
        or i.get("instrumentName")
        or i.get("assetName")
        or i.get("displayName")
        or (i.get("transformerAssetTag") or "").strip()
    )
    if name:
        return name
    return f"instrument-{iid}" if iid is not None else None

# -----------------------
# routes
# -----------------------
@app.post("/ingest/instruments", summary="Fetch & upsert instruments")
def ingest_instruments():
    token = get_token()
    instruments = _as_list(list_instruments(token))

    upserted = 0
    with SessionLocal() as s:
        for i in instruments:
            iid = _iid(i)
            if iid is None:
                logger.warning("Skipping instrument without id; keys={}", list(i.keys()))
                continue
            rec = s.get(DBInstrument, iid) or DBInstrument(id=iid)
            rec.name = _iname(i, iid)
            rec.commissioned = i.get("commissioned") or i.get("isCommissioned")
            rec.meta = i  # keep full vendor record
            s.add(rec)
            upserted += 1
        s.commit()

    return {"received": len(instruments), "upserted": upserted}

@app.post("/ingest/voltage-mean-30m", summary="Voltage mean (30m) bronze->silver")
def ingest_voltage_mean_30m(hours: int = 2, limit: int = 3):
    token = get_token()
    instruments = _as_list(list_instruments(token))
    # select up to `limit` ids
    ids: list[int] = []
    for i in instruments:
        val = _iid(i)
        if val is not None:
            ids.append(val)
        if len(ids) >= max(1, limit):
            break
    if not ids:
        logger.warning("No instrument IDs could be extracted; skipping fetch")
        return {"instrument_ids": [], "fetched": 0, "normalized": 0}

    to_ts = dt.datetime.now(UTC)
    from_ts = to_ts - dt.timedelta(hours=hours)

    data = voltage_mean_30min(token, ids, from_ts, to_ts)

    # bronze
    with SessionLocal() as s:
        for row in data:
            s.add(RawMeasurement(
                endpoint="voltage/mean/30min",
                instrument_id=int(row.get("instrumentId") or row.get("instrument_id") or ids[0]),
                payload=row
            ))
        s.commit()

    # silver
    n = normalize_voltage_mean_30min(data)
    return {"instrument_ids": ids, "fetched": len(data), "normalized": n}

@app.post("/ingest/current-mean-30m", summary="Current mean (30m) bronze->silver")
def ingest_current_mean_30m(hours: int = 2, limit: int = 3):
    token = get_token()
    instruments = _as_list(list_instruments(token))

    ids: list[int] = []
    for i in instruments:
        val = _iid(i)
        if val is not None:
            ids.append(val)
        if len(ids) >= max(1, limit):
            break
    if not ids:
        logger.warning("No instrument IDs could be extracted; skipping fetch")
        return {"instrument_ids": [], "fetched": 0, "normalized": 0}

    to_ts = dt.datetime.now(UTC)
    from_ts = to_ts - dt.timedelta(hours=hours)

    data = current_mean_30min(token, ids, from_ts, to_ts)

    with SessionLocal() as s:
        for row in data:
            s.add(RawMeasurement(
                endpoint="current/mean/30min",
                instrument_id=int(row.get("instrumentId") or row.get("instrument_id") or ids[0]),
                payload=row
            ))
        s.commit()

    n = normalize_current_mean_30min(data)
    return {"instrument_ids": ids, "fetched": len(data), "normalized": n}

@app.get("/metrics/ingest-summary", summary="Rows ingested in last N hours")
def ingest_summary(hours: int = 24):
    q = text("""
      with rng as (select now() - (:h||' hours')::interval as since)
      select 'voltage_mean_30m' as table, count(*) as rows
        from voltage_mean_30m, rng where ts_utc >= rng.since
      union all
      select 'current_mean_30m', count(*) from current_mean_30m, rng
        where ts_utc >= rng.since
    """)
    with SessionLocal() as s:
        result = s.execute(q, {"h": hours})
        rows = [dict(m) for m in result.mappings()]  # SQLAlchemy 2.x safe conversion
    return {"since_hours": hours, "tables": rows}

@app.get("/cloud/healthz", summary="Cloud sink connectivity")
def cloud_healthz():
    ok, msg = cloud_health()
    return {"enabled": settings.ENABLE_CLOUD_SINK, "ok": ok, "status": msg}

@app.post("/cloud/init", summary="Create tables/indexes on cloud target")
def cloud_init_route():
    cloud_init()
    return {"ok": True}

@app.post("/cloud/sync", summary="Replicate recent rows to cloud target")
def cloud_sync_route(tables: str = "instrument,voltage_mean_30m,current_mean_30m", since_hours: int = 24):
    tlist = [t.strip() for t in tables.split(",") if t.strip()]
    res = cloud_sync(tlist, since_hours=since_hours)
    return {"tables": tlist, "since_hours": since_hours, "copied_rows": res}
