from typing import Iterable, Iterator, Any
from loguru import logger
from sqlalchemy import text
import re

from src.app.db.session import SessionLocal

# -------------------------
# DB helper
# -------------------------
def _upsert(sql: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    with SessionLocal() as s:
        for p in rows:
            s.execute(text(sql), p)
        s.commit()
    return len(rows)

# -------------------------
# Generic recursive flattener
# -------------------------
_TS_KEYS = (
    "timestamp", "timeUtc", "timestampUtc", "timeUTC", "ts", "time",
    "endTimeUtc", "startTimeUtc", "periodEndUtc", "periodStartUtc",
    "dateTime", "datetime", "readingTimeUtc", "time_utc", "timestampUTC",
)

def _detect_ts(d: dict) -> str | None:
    for k in _TS_KEYS:
        v = d.get(k)
        if v not in (None, ""):
            return str(v)
    return None

def _walk_points(obj: Any, iid: Any = None, unit: str | None = None, depth: int = 0) -> Iterator[dict]:
    """
    Recursively traverse obj. Yield any dict that looks like a time-series 'point':
    i.e. it has a timestamp-ish key. Carry instrumentId/unit from parents.
    """
    if depth > 8:
        return
    if isinstance(obj, dict):
        # inherit identifiers/units
        iid2 = obj.get("instrumentId") or obj.get("instrument_id") or obj.get("id") or iid
        unit2 = obj.get("unit") or obj.get("units") or unit

        # if this dict itself has a timestamp, treat as a point
        ts = _detect_ts(obj)
        if ts is not None:
            d = dict(obj)
            if iid2 is not None and "instrumentId" not in d:
                d["instrumentId"] = iid2
            if unit2 and "unit" not in d:
                d["unit"] = unit2
            yield d

        # continue walking deeper
        for v in obj.values():
            yield from _walk_points(v, iid2, unit2, depth + 1)

    elif isinstance(obj, list):
        for it in obj:
            yield from _walk_points(it, iid, unit, depth + 1)

# -------------------------
# Phase detection
# -------------------------
# Broader patterns: catch l1/l2/l3 even when glued to other words (e.g. 'voltageL1')
_PAT_L1 = re.compile(r'(?:^|[^a-z0-9])l1(?:[^a-z0-9]|$)|voltagel1|currentl1|^l1|l1$', re.I)
_PAT_L2 = re.compile(r'(?:^|[^a-z0-9])l2(?:[^a-z0-9]|$)|voltagel2|currentl2|^l2|l2$', re.I)
_PAT_L3 = re.compile(r'(?:^|[^a-z0-9])l3(?:[^a-z0-9]|$)|voltagel3|currentl3|^l3|l3$', re.I)
_PAT_A  = re.compile(r'(^|[^a-z0-9])phase?\s*a([^a-z0-9]|$)|voltage.*a|current.*a|(^|[^a-z0-9])a([^a-z0-9]|$)', re.I)
_PAT_B  = re.compile(r'(^|[^a-z0-9])phase?\s*b([^a-z0-9]|$)|voltage.*b|current.*b|(^|[^a-z0-9])b([^a-z0-9]|$)', re.I)
_PAT_C  = re.compile(r'(^|[^a-z0-9])phase?\s*c([^a-z0-9]|$)|voltage.*c|current.*c|(^|[^a-z0-9])c([^a-z0-9]|$)', re.I)



def _phase_from_subject(name: str) -> str | None:
    s = str(name).strip().upper()
    # Normalize common labels to A/B/C
    if s in ("L1", "PHASE A", "A"): return "L1"
    if s in ("L2", "PHASE B", "B"): return "L2"
    if s in ("L3", "PHASE C", "C"): return "L3"
    # If “TOTAL”, “3-PHASE”, etc. shows up, treat as TOTAL
    if s in ("TOTAL", "3-PHASE", "3PH", "ALL"): return "TOTAL"
    return None

def _numeric_value(d: dict):
    """Try vendor numeric fields in priority order."""
    for k in ("numericData", "numericValue", "value", "mean", "avg", "average", "meanValue", "dataValue"):
        v = d.get(k)
        if v in (None, ""):
            continue
        try:
            return float(v)
        except Exception:
            continue
    return None


def _phase_values(d: dict) -> list[tuple[str, float]]:
    """
    Return [(phase, value), ...] from a point dict.
    Priority:
      1) subjectAssetName + numericX (your tenant's shape)
      2) explicit ('phase', 'value'/'mean'...)
      3) scan numeric keys for L1/L2/L3 or A/B/C (legacy shapes)
      4) single numeric 'value' fallback -> TOTAL
    """
    out: list[tuple[str, float]] = []

    # 1) subjectAssetName + numericData
    subj = d.get("subjectAssetName") or d.get("subjectPhaseName") or d.get("channelName")
    if subj:
        ph = _phase_from_subject(subj)
        val = _numeric_value(d)
        if ph and val is not None:
            out.append((ph, val))
            return out

    # 2) explicit phase + value/mean/avg
    ph = d.get("phase") or d.get("Phase") or d.get("PHASE")
    if ph:
        val = _numeric_value(d)
        if val is not None:
            out.append((str(ph).strip().upper().replace("L", ""), val))
            return out

    # 3) scan numeric keys for matches (l1/l2/l3 or a/b/c embedded in key names)
    for key, raw in d.items():
        if raw is None:
            continue
        try:
            f = float(raw)
        except Exception:
            continue
        k = str(key).lower()
        if _PAT_L1.search(k) or _PAT_A.search(k):
            out.append(("A", f)); continue
        if _PAT_L2.search(k) or _PAT_B.search(k):
            out.append(("B", f)); continue
        if _PAT_L3.search(k) or _PAT_C.search(k):
            out.append(("C", f)); continue

    # 4) single numeric 'value' fallback -> TOTAL
    v = _numeric_value(d)
    if not out and v is not None:
        out.append(("TOTAL", v))

    return out

# -------------------------
# Normalizers
# -------------------------
def normalize_voltage_mean_30min(rows: Iterable[dict]) -> int:
    points = list(_walk_points(rows))
    mapped: list[dict] = []
    skipped = 0

    for p in points:
        iid = p.get("instrumentId") or p.get("instrument_id") or p.get("id")
        ts = _detect_ts(p)
        unit = p.get("unit") or p.get("units") or "V"
        phases = _phase_values(p)

        if iid is None or ts is None or not phases:
            skipped += 1
            continue

        try:
            iid = int(iid)
        except Exception:
            skipped += 1
            continue

        for ph, val in phases:
            mapped.append({"i": iid, "t": ts, "p": ph, "v": val, "u": unit})

    if skipped:
        logger.info(f"normalize_voltage_mean_30min: mapped={len(mapped)} skipped={skipped}")

    sql = """
    INSERT INTO voltage_mean_30m (instrument_id, ts_utc, phase, value, unit)
    VALUES (:i, :t, :p, :v, :u)
    ON CONFLICT (instrument_id, ts_utc, phase)
    DO UPDATE SET value=EXCLUDED.value, unit=EXCLUDED.unit;
    """
    n = _upsert(sql, mapped)
    logger.info(f"Normalized voltage rows inserted/updated: {n}")
    return n

def normalize_current_mean_30min(rows: Iterable[dict]) -> int:
    points = list(_walk_points(rows))
    mapped: list[dict] = []
    skipped = 0

    for p in points:
        iid = p.get("instrumentId") or p.get("instrument_id") or p.get("id")
        ts = _detect_ts(p)
        unit = p.get("unit") or p.get("units") or "A"
        phases = _phase_values(p)

        if iid is None or ts is None or not phases:
            skipped += 1
            continue

        try:
            iid = int(iid)
        except Exception:
            skipped += 1
            continue

        for ph, val in phases:
            mapped.append({"i": iid, "t": ts, "p": ph, "v": val, "u": unit})

    if skipped:
        logger.info(f"normalize_current_mean_30min: mapped={len(mapped)} skipped={skipped}")

    sql = """
    INSERT INTO current_mean_30m (instrument_id, ts_utc, phase, value, unit)
    VALUES (:i, :t, :p, :v, :u)
    ON CONFLICT (instrument_id, ts_utc, phase)
    DO UPDATE SET value=EXCLUDED.value, unit=EXCLUDED.unit;
    """
    n = _upsert(sql, mapped)
    logger.info(f"Normalized current rows inserted/updated: {n}")
    return n
