import json, argparse, datetime as dt
from dateutil import tz
from loguru import logger
from src.app.clients.substation360 import get_token, list_instruments
from src.app.db.session import SessionLocal
from src.app.db.models import Instrument as DBInstrument

def _iso_utc(dt_obj): return dt_obj.replace(tzinfo=tz.UTC).isoformat().replace("+00:00","Z")

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("auth")
    sub.add_parser("instruments")
    args = parser.parse_args()

    token = get_token()

    if args.cmd == "auth":
        logger.success("Auth OK (token acquired)")
        return

    if args.cmd == "instruments":
        inst = list_instruments(token)
        with SessionLocal() as s:
            for i in inst:
                rec = s.get(DBInstrument, int(i["id"])) or DBInstrument(id=int(i["id"]))
                rec.name = i.get("name")
                rec.commissioned = i.get("commissioned")
                rec.meta = i
                s.add(rec)
            s.commit()
        logger.success(f"Upserted {len(inst)} instruments to DB")
        print(json.dumps(inst[:5], indent=2))

if __name__ == "__main__":
    main()
