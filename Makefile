PY=python

setup:
	$(PY) -m pip install -r requirements.txt

run:
	uvicorn src.app.main:app --host 0.0.0.0 --port 8000 --reload

test:
	pytest -q

db-init:
	$(PY) -c "from src.app.db.session import Base,engine; Base.metadata.create_all(bind=engine)"

auth-smoke:
	$(PY) -m src.app.ingest.run_ingest auth

instruments-smoke:
	$(PY) -m src.app.ingest.run_ingest instruments

ingest-demo:
	$(PY) -m src.app.ingest.run_ingest voltage_mean_30min --hours 2 --limit 3
