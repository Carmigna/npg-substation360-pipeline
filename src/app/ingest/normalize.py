# src/app/ingest/normalize.py
from typing import Iterable, Iterator, Any
from loguru import logger
from sqlalchemy import text
import re

from src.app.db.session import SessionLocal

# ---------- helpers

def _upsert(sql: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    with SessionLocal() as s:
        for p in rows:
            s.execute(text(sql), p)
        s.commit()
    return len(rows)

def _as_list(obj: Any) -> list:
    if obj is None:
        return []
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        # common wrappers
        for k in ("items", "data", "results", "values", "series"):
            v = obj.get(k)
            if isinstance(v, list):
                return v
        return [obj]
    return [obj]

def _flatten_points(rows: Iterable[dict]) -> Iterator[dict]:
    """
    Yield point-level dicts. If a parent has instrumentId and a 'values' list,
    propagate instrumentId down into each child value row.
    """
    for r in rows:
        if not isinstance(r, dict):
            continue
        base_iid = r.get("instrumentId") or r.get("instrument_id") or r.get("id")
        # Typical nesting: r = {instrumentId: ..., values: [ {...}, {...} ]}
        for bucket_key in ("values", "data", "points", "rows"):
            if bucket_key in r and isinstance(r[bucket_key], list):
                for v in r[bucket_key]:
                    if isinstance(v, dict):
                        if base_iid is not None and "instrumentId" not in v:
                            v = {"instrumentId": base_iid, **v}
                        yield v
                break
        else:
            # no nested array → treat r as a point row itself
            yield r

_TS_KEYS = (
    "timestamp", "timeUtc", "timestampUtc", "timeUTC", "ts", "time",
    "endTimeUtc", "startTimeUtc", "periodEndUtc", "periodStartUtc",
)

# flexible phase key mapping
_PHASE_PATTERNS = {
    "A": [r"(^|[_-])a($|[_-])", r"(^|[_-])l1($|[_-])", r"phase\s*a", r"voltage.*a", r"current.*a", r"\bva\b", r"\bia\b"],
    "B": [r"(^|[_-])b($|[_-])", r"(^|[_-])l2($|[_-])", r"phase\s*b", r"voltage.*b", r"current.*b", r"\bvb\b", r"\bib\b"],
    "C": [r"(^|[_-])c($|[_-])", r"(^|[_-])l3($|[_-])", r"phase\s*c", r"voltage.*c", r"current.*c", r"\bvc\b", r"\bic\b"],
}
_PHASE_REGEX = {ph: [re.compile(pat, re.I) for pat in pats] for ph, pats in _PHASE_PATTERNS.items()}

def _detect_ts(d: dict) -> str | None:
    for k in _TS_KEYS:
        v = d.get(k)
        if v:
            return str(v)
    return None

def _phase_values(d: dict) -> list[tuple[str, float]]:
    """
    Return list of (phase, value) detected in dict d.
    Supports keys like a/b/c, l1/l2/l3, voltageA/currentA, etc.
    Also supports ('phase', 'value') pairs.
    """
    out: list[tuple[str, float]] = []

    # 1) explicit 'phase' + 'value'
    ph = d.get("phase") or d.get("Phase") or d.get("PHASE")
    if ph and ("value" in d or "mean" in d or "avg" in d or "average" in d or "meanValue" in d):
        val = d.get("value", d.get("mean", d.get("avg", d.get("average", d.get("meanValue")))))
        try:
            out.append((str(ph).strip().upper().replace("L", ""), float(val)))
            return out
        except Exception:
            pass

    # 2) scan keys heuristically
    for key, raw in d.items():
        if raw is None:
            continue
        try:
            f = float(raw)
        except Exception:
            continue
        k = str(key)
        k_norm = k.lower()

        for ph, regs in _PHASE_REGEX.items():
            if any(r.search(k) for r in regs):
                out.append((ph, f))
                break

    # 3) fallback: single numeric 'value' → TOTAL
    if not out and any(k in d for k in ("value", "mean", "avg", "average", "meanValue")):
        val = d.get("value", d.get("mean", d.get("avg", d.get("average", d.get("meanValue")))))
        try:
            out.append(("TOTAL", float(val)))
        except Exception:
            pass

    return out

# ---------- normalizers

def normalize_voltage_mean_30min(rows: Iterable[dict]) -> int:
    points = list(_flatten_points(rows))
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
    points = list(_flatten_points(rows))
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
