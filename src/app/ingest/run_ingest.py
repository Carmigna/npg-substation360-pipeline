import sys, json, argparse, datetime as dt
from loguru import logger
from dateutil import tz
from src.app.clients.substation360 import get_token, list_instruments, voltage_mean_30min

# # add near imports
# from src.app.db.session import SessionLocal
# from src.app.db.models import Instrument as DBInstrument, RawMeasurement

# # ... in 'instruments' branch:
# with SessionLocal() as s:
#     for i in inst:
#         rec = s.get(DBInstrument, int(i["id"])) or DBInstrument(id=int(i["id"]))
#         rec.name = i.get("name")
#         rec.commissioned = i.get("commissioned")
#         rec.metadata = i
#         s.add(rec)
#     s.commit()
#     logger.success(f"Upserted {len(inst)} instruments to DB")

# # ... in 'voltage_mean_30min' branch after 'data = ...':
# with SessionLocal() as s:
#     for row in data:
#         rid = int(row.get("instrumentId") or row.get("instrument_id") or ids[0])  # conservative
#         s.add(RawMeasurement(endpoint="voltage/mean/30min", instrument_id=rid, payload=row))
#     s.commit()
#     logger.success(f"Inserted {len(data)} raw rows")


def _iso_utc(dt_obj): return dt_obj.replace(tzinfo=tz.UTC).isoformat().replace("+00:00","Z")

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("auth")
    sub.add_parser("instruments")
    v = sub.add_parser("voltage_mean_30min")
    v.add_argument("--hours", type=int, default=2)
    v.add_argument("--limit", type=int, default=3)

    args = parser.parse_args()
    token = get_token()

    if args.cmd == "auth":
        logger.success("Auth OK (token acquired)")
        return

    if args.cmd == "instruments":
        inst = list_instruments(token)
        logger.info(f"Found {len(inst)} instruments")
        print(json.dumps(inst[:5], indent=2))
        return

    if args.cmd == "voltage_mean_30min":
        inst = list_instruments(token)
        ids = [int(i["id"]) for i in inst[: args.limit]]
        to_ts = dt.datetime.utcnow()
        from_ts = to_ts - dt.timedelta(hours=args.hours)
        data = voltage_mean_30min(token, ids, _iso_utc(from_ts), _iso_utc(to_ts))
        logger.info(f"Received {len(data)} rows")
        print(json.dumps(data[:3], indent=2))

if __name__ == "__main__":
    main()
