from typing import Sequence
from loguru import logger
from sqlalchemy import text
from src.app.db.session import SessionLocal, CloudSessionLocal, cloud_engine
from src.app.db.session import Base  # your metadata

def cloud_health() -> tuple[bool, str]:
    if not cloud_engine:
        return (False, "disabled")
    try:
        with cloud_engine.connect() as c:
            c.execute(text("select 1"))
        return (True, "ok")
    except Exception as e:
        return (False, str(e))

def cloud_init() -> None:
    if not cloud_engine:
        raise RuntimeError("Cloud sink not configured")
    Base.metadata.create_all(bind=cloud_engine)
    with cloud_engine.begin() as conn:
        conn.execute(text("ALTER TABLE instrument ADD COLUMN IF NOT EXISTS meta JSONB;"))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_voltage_mean_10m
            ON voltage_mean_10m (instrument_id, ts_utc, phase);
        """))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_current_mean_10m
            ON current_mean_10m (instrument_id, ts_utc, phase);
        """))

def _sync_one(table: str, since_hours: int) -> int:
    if not CloudSessionLocal:
        raise RuntimeError("Cloud sink not configured")

    if table == "instrument":
        # detect whether source has 'meta' column
        with SessionLocal() as src:
            has_meta = src.execute(text("""
                SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='instrument' AND column_name='meta'
                ) AS ok
            """)).scalar()

        sel = text(
            "SELECT id, name, commissioned, meta FROM instrument"
            if has_meta else
            "SELECT id, name, commissioned, NULL::jsonb AS meta FROM instrument"
        )

        ins = text("""
            INSERT INTO instrument (id, name, commissioned, meta)
            VALUES (:id, :name, :commissioned, :meta)
            ON CONFLICT (id) DO UPDATE
            SET name=EXCLUDED.name,
                commissioned=EXCLUDED.commissioned,
                meta=EXCLUDED.meta;
        """)

        # ensure target has 'meta'
        with CloudSessionLocal() as dst:
            dst.execute(text("ALTER TABLE instrument ADD COLUMN IF NOT EXISTS meta JSONB;"))
            dst.commit()

        with SessionLocal() as src, CloudSessionLocal() as dst:
            rows = src.execute(sel).mappings().all()
            if not rows:
                return 0
            dst.execute(ins, rows)
            dst.commit()
            return len(rows)
    elif table == "voltage_mean_10m":
        sel = text("""
            select instrument_id, ts_utc, phase, value, unit
            from voltage_mean_10m
            where ts_utc >= now() - (:h || ' hours')::interval
        """)
        ins = text("""
            INSERT INTO voltage_mean_10m (instrument_id, ts_utc, phase, value, unit)
            VALUES (:instrument_id, :ts_utc, :phase, :value, :unit)
            ON CONFLICT (instrument_id, ts_utc, phase) DO UPDATE
            SET value=EXCLUDED.value, unit=EXCLUDED.unit;
        """)
    elif table == "current_mean_10m":
        sel = text("""
            select instrument_id, ts_utc, phase, value, unit
            from current_mean_10m
            where ts_utc >= now() - (:h || ' hours')::interval
        """)
        ins = text("""
            INSERT INTO current_mean_10m (instrument_id, ts_utc, phase, value, unit)
            VALUES (:instrument_id, :ts_utc, :phase, :value, :unit)
            ON CONFLICT (instrument_id, ts_utc, phase) DO UPDATE
            SET value=EXCLUDED.value, unit=EXCLUDED.unit;
        """)
    else:
        raise ValueError(f"Unsupported table: {table}")

    with SessionLocal() as src, CloudSessionLocal() as dst:
        rows = src.execute(sel, {"h": since_hours}).mappings().all()
        if not rows:
            return 0
        dst.execute(ins, rows)
        dst.commit()
        return len(rows)

def sync(tables: Sequence[str], since_hours: int = 24) -> dict[str, int]:
    out = {}
    for t in tables:
        out[t] = _sync_one(t, since_hours)
    return out
