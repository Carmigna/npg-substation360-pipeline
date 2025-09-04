# NPG Substation360 Pipeline Demo

**Goal:** Stand up a production‑shaped data pipeline that authenticates to EA Technology’s **Substation360 Integration API**, discovers **Instruments**, fetches **30‑minute telemetry** (e.g., Voltage/Current mean), lands raw payloads into Postgres (**bronze**), and normalizes into query‑ready tables (**silver**). The repo supports **VS Code (local)** and **GitHub Codespaces (zero‑install)**.

> **Granularity:** The Integration API exposes **30‑minute capture** for core telemetry (e.g., voltage/current mean). Endpoints are called as **HTTP GET** with `from`/`to` query parameters and a **JSON body of instrument IDs**—an unusual but documented pattern we mirror exactly.&#x20;

---

## Table of Contents

* [Architecture](#architecture)
* [Repo Structure](#repo-structure)
* [Prerequisites](#prerequisites)
* [Quickstart (VS Code)](#quickstart-vs-code)
* [Quickstart (Codespaces)](#quickstart-codespaces)
* [Configuration (.env)](#configuration-env)
* [TLS / Certificates](#tls--certificates)
* [Database](#database)
* [Runbook: End-to-End Demo](#runbook-end-to-end-demo)
* [API Surface (FastAPI)](#api-surface-fastapi)
* [Cloud Sink (Optional Replication)](#cloud-sink-optional-replication)
* [Troubleshooting](#troubleshooting)
* [Security Notes](#security-notes)
* [Roadmap](#roadmap)
* [References](#references)
* [License](#license)

---

## Architecture

**Data flow**

1. **Auth** → `POST /api/token` (Substation360 Auth).
2. **Discover** → `GET /api/instrument` (list instruments you can access).
3. **Ingest** → e.g. `GET /api/voltage/mean/10min?from=...&to=...` with **JSON body = \[instrumentIds]**.&#x20;
4. **Land (bronze)** → store exact JSON rows in `raw_measurement`.
5. **Normalize (silver)** → extract canonical fields into `voltage_mean_10m`, `current_mean_10m`.
6. **(Optional) Replicate** → push silver tables to a **cloud Postgres** (RDS/Azure/etc.) for analytics/ML feature pipelines.

> The Postman collection shows **multipart/form‑data** auth and the **GET + JSON body** telemetry calls we implement 1:1.&#x20;

---

## Repo Structure

```
npg-substation360-pipeline/
├─ .devcontainer/
│  ├─ devcontainer.json             # Dev Container for VS Code/Codespaces
│  └─ docker-compose.yml            # Postgres service (ports 5432:5432)
├─ certs/                           # place vendor CA file here (see TLS)
├─ src/
│  └─ app/
│     ├─ main.py                    # FastAPI app (health, ingest, metrics, cloud)
│     ├─ config.py                  # Settings (pydantic-settings reads .env)
│     ├─ clients/
│     │  └─ substation360.py        # HTTP client (auth, list, voltage/current)
│     ├─ db/
│     │  ├─ models.py               # ORM (Instrument, RawMeasurement, silver)
│     │  └─ session.py              # SQLAlchemy engines/sessions (local + cloud)
│     ├─ ingest/
│     │  ├─ normalize.py            # Bronze → Silver normalization (robust)
│     │  └─ run_ingest.py           # (optional) CLI helpers
│     └─ sync/
│        └─ cloud.py                # Optional cloud replication module
├─ docs/
│  ├─ Substation360 API Integration - Customer Instructions.pdf
│  └─ Integration APIs.postman_collection.json
├─ tests/                           # (optional) pytest
├─ .env.template
├─ .gitignore
├─ Makefile                         # common tasks (run, db-init)
├─ requirements.txt
└─ README.md
```

---

## Prerequisites

* **VS Code** (recommended) or **GitHub Codespaces**
* **Docker** (for local Postgres via Dev Container compose; optional)
* **Python 3.11+**
* **Git**
* **Substation360 credentials** (username/password)
* **Vendor CA certificate** for TLS (see [TLS / Certificates](#tls--certificates))

---

## Quickstart (VS Code)

> You can run **without Docker** (using a local Postgres) or with the included **Dev Container** Postgres. Both paths are shown.

### 0) Clone

```bash
git clone https://github.com/carmigna/npg-substation360-pipeline.git
cd npg-substation360-pipeline
```

### 1) Configure environment

```bash
cp .env.template .env
# open .env and set:
#   S360_USERNAME, S360_PASSWORD
#   S360_CA_CERT_PATH=certs/substation360ig.co.uk.fullchain.complete.crt
#   (optional) ENABLE_CLOUD_SINK + CLOUD_DB_URL
```

> **Never commit** your `.env`. It’s in `.gitignore`.

### 2A) (Option A) Use local Postgres (already running on your machine)

* Ensure a Postgres is reachable at `DATABASE_URL` (default is `postgresql+psycopg://app:app@localhost:5432/s360`).
* Create DB `s360` if not present:

  ```bash
  psql "host=localhost user=app password=app dbname=postgres" -c "CREATE DATABASE s360;"
  ```

### 2B) (Option B) Start Postgres with Docker Compose (from the repo)

```bash
docker compose -f .devcontainer/docker-compose.yml up -d db
# Verify it's up:
docker ps --format "table {{.Names}}\t{{.Ports}}\t{{.Status}}"
```

> If you see docker socket permission errors:
> `sudo usermod -aG docker $USER && newgrp docker` (then open a new terminal).

### 3) Python deps + DB init

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Create tables (Instrument / RawMeasurement / silver tables)
make db-init
```

### 4) Run the API

```bash
make run
# In another terminal:
curl -s http://127.0.0.1:8000/healthz
# → {"status":"ok"}
```

Open the **Swagger UI** at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## Quickstart (Codespaces)

1. GitHub → your repo → **Code** → **Codespaces** → **Create codespace**
2. In the Codespace terminal:

```bash
cp .env.template .env
# edit .env (username/password/cert path)
pip install -r requirements.txt
make db-init
make run
```

Open Ports → expose `8000` → click to open the FastAPI docs.

---

## Configuration (.env)

```ini
# -------- Local DB --------
DATABASE_URL=postgresql+psycopg://app:app@localhost:5432/s360
DB_ECHO=false

# -------- Substation360 --------
S360_AUTH_URL=https://auth.substation360ig.co.uk/api/token
S360_BASE_URL=https://integration.substation360ig.co.uk/api
S360_USERNAME=__set_me__
S360_PASSWORD=__set_me__

# TLS (see "TLS / Certificates")
S360_VERIFY_SSL=true
S360_CA_CERT_PATH=certs/substation360ig.co.uk.fullchain.complete.crt
# DEV ONLY: if SAN/hostname issues persist while vendor updates certs:
S360_TLS_RELAX_HOSTNAME=true

# -------- Optional Cloud Sink --------
ENABLE_CLOUD_SINK=false
# Example when enabled (local stand‑in for RDS/Azure):
# CLOUD_DB_URL=postgresql+psycopg://app:app@localhost:5432/s360_cloud
CLOUD_DB_ECHO=false
```

> **Auth pattern**: The Postman collection shows `POST /api/token` with **multipart/form‑data** (`grant_type=password`, `clienttype=user`, `username`, `password`). We implement the same and reuse the **Bearer token** on telemetry endpoints.&#x20;

---

## TLS / Certificates

EA Technology provides a **self‑signed chain**. You have three options:

1. **Preferred** (even for dev): point `S360_CA_CERT_PATH` to the vendor’s **full chain** file and keep `S360_VERIFY_SSL=true`.
2. **If hostname/SAN mismatch during vendor transition**: set `S360_TLS_RELAX_HOSTNAME=true` **only in local dev** to skip hostname checks.
3. **Last resort for initial connectivity**: `S360_VERIFY_SSL=false` (dev only; never in shared environments).

**Where to place the file**: put the provided file (e.g., `substation360ig.co.uk.fullchain.complete.crt`) into `./certs/` and reference it via `S360_CA_CERT_PATH`.

---

## Database

We use SQLAlchemy models with a bronze/silver split:

* **`instrument`**
  `id BIGINT PRIMARY KEY`, `name TEXT`, `commissioned BOOLEAN`, `meta JSONB`
  (If you created the DB before `meta` existed, add it:
  `ALTER TABLE instrument ADD COLUMN IF NOT EXISTS meta JSONB;`)

* **`raw_measurement`** (bronze)
  `id SERIAL PK`, `endpoint TEXT`, `instrument_id BIGINT`, `payload JSONB`, `created_at TIMESTAMPTZ DEFAULT now()`

* **Silver tables** (query‑ready)

  * `voltage_mean_10m(instrument_id, ts_utc, phase, value, unit)`
  * `current_mean_10m(instrument_id, ts_utc, phase, value, unit)`
    with **unique indexes** for idempotent upsert:

  ```sql
  CREATE UNIQUE INDEX IF NOT EXISTS uq_voltage_mean_10m  ON voltage_mean_10m (instrument_id, ts_utc, phase);
  CREATE UNIQUE INDEX IF NOT EXISTS uq_current_mean_10m  ON current_mean_10m (instrument_id, ts_utc, phase);
  ```

**Normalization details:** payloads can be **nested** and vary by tenant. Our normalizer flattens common shapes and specifically maps:

* **`subjectAssetName`** ∈ {`L1`,`L2`,`L3`} → **phase** {A,B,C} (or configurable to `{L1,L2,L3}`)
* **`numericData`** (or related numeric fields) → **value**
* **`time`/`timestamp*`** → **ts\_utc**
  

---

## Runbook: End‑to‑End Demo

> You can run these either via **Swagger** ([http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)) or **curl**.

### 1) Health

```bash
curl -s http://127.0.0.1:8000/healthz
# {"status":"ok"}
```

### 2) Ingest Instruments

```bash
curl -s -X POST http://127.0.0.1:8000/ingest/instruments | jq .
# {"received": N, "upserted": N}
```

Check in DB:

```bash
psql "host=localhost port=5432 dbname=s360 user=app password=app" \
  -c "select id,name,commissioned from instrument order by id limit 10;"
```

### 3) Ingest Voltage / Current (last 2 hours, up to 3 instruments)

```bash
curl -s -X POST "http://127.0.0.1:8000/ingest/voltage-mean-10m?hours=2&limit=3" | jq .
# {"instrument_ids":[...], "fetched": X, "normalized": Y}

curl -s -X POST "http://127.0.0.1:8000/ingest/current-mean-10m?hours=2&limit=3" | jq .
# {"instrument_ids":[...], "fetched": X, "normalized": Y}
```

**Verify silver tables:**

```bash
psql "host=localhost port=5432 dbname=s360 user=app password=app" \
  -c "select count(*) from voltage_mean_10m; \
      select count(*) from current_mean_10m; \
      select * from voltage_mean_10m order by ts_utc desc limit 5;"
```

### 4) Summary metrics

```bash
curl -s "http://127.0.0.1:8000/metrics/ingest-summary?hours=24" | jq .
# {"since_hours":24,"tables":[{"table":"voltage_mean_10m","rows":...},{"table":"current_mean_10m","rows":...}]}
```

---

## API Surface (FastAPI)

* `GET /healthz` — liveness
* `POST /ingest/instruments` — fetch + upsert instruments
* `POST /ingest/voltage-mean-10m?hours=&limit=` — fetch, land (bronze), normalize (silver)
* `POST /ingest/current-mean-10m?hours=&limit=` — same for current
* `GET /metrics/ingest-summary?hours=` — row counts in last N hours

**Cloud sink (optional):**

* `GET /cloud/healthz` — verifies cloud DB connectivity
* `POST /cloud/init` — creates cloud tables/indexes (idempotent)
* `POST /cloud/sync?tables=instrument,voltage_mean_10m,current_mean_10m&since_hours=24` — replicate recent rows

Open the interactive docs at **`/docs`** and try these endpoints in order.

---

## Cloud Sink (Optional Replication)

You can replicate `instrument`, `voltage_mean_10m`, and `current_mean_10m` to a **second database** (e.g., cloud Postgres). It’s off by default.

### 1) Enable in `.env`

```ini
ENABLE_CLOUD_SINK=true
CLOUD_DB_URL=postgresql+psycopg://app:app@localhost:5432/s360_cloud
```

Create the target DB (for the demo):

```bash
psql "host=localhost port=5432 dbname=postgres user=app password=app" \
  -c "CREATE DATABASE s360_cloud;"
```

### 2) Provision cloud schema

```bash
curl -s -X POST http://127.0.0.1:8000/cloud/init | jq .
# {"ok": true}
```

### 3) Sync recent data

```bash
curl -s -X POST \
  "http://127.0.0.1:8000/cloud/sync?tables=instrument,voltage_mean_10m,current_mean_10m&since_hours=24" \
  | jq .
# {"tables":[...],"since_hours":24,"copied_rows":{"instrument":N,"voltage_mean_10m":X,"current_mean_10m":Y}}
```

### 4) Verify in cloud DB

```bash
psql "host=localhost port=5432 dbname=s360_cloud user=app password=app" \
  -c "select count(*) from instrument; \
      select count(*) from voltage_mean_10m; \
      select count(*) from current_mean_10m;"
```

> The sync path is idempotent and hardens for schema drift (e.g., it will **add `instrument.meta`** to the target if missing and selects `NULL::jsonb AS meta` from the source if absent).

---

## Troubleshooting

**SSL: `CERTIFICATE_VERIFY_FAILED` (self‑signed / chain)**

* Ensure `S360_CA_CERT_PATH` points to the provided CA file and `S360_VERIFY_SSL=true`.
* For dev only, if you hit **hostname/SAN mismatch** while EA updates certs, set `S360_TLS_RELAX_HOSTNAME=true` to ignore host checks.

**Auth succeeds, telemetry returns nothing**

* Make sure you are calling telemetry endpoints with **GET + JSON body** of instrument IDs and `from`/`to` in the query. This is how the Integration API is designed (per Postman).&#x20;

**Fetched > 0 but Normalized = 0**

* Your tenant likely returns per‑phase rows like:

  ```json
  {"time":"...Z","subjectAssetName":"L3","numericData":243.131,"instrumentId":"..."}
  ```

  Our normalizer maps `subjectAssetName` → A/B/C (or L1/L2/L3) and `numericData` → value. If still zero, inspect a bronze row:

  ```bash
  psql "host=localhost port=5432 dbname=s360 user=app password=app" \
    -c "select jsonb_pretty(payload) from raw_measurement order by id desc limit 1;"
  ```

  Share the keys you see (we can add a one‑liner mapper).

**`UndefinedColumn: column "meta" does not exist` during /cloud/sync**

* Add the column in source/target (idempotent):

  ```bash
  psql "... s360 ..."       -c "ALTER TABLE instrument ADD COLUMN IF NOT EXISTS meta JSONB;"
  psql "... s360_cloud ..." -c "ALTER TABLE instrument ADD COLUMN IF NOT EXISTS meta JSONB;"
  ```

  (The sync path now also auto‑adapts.)

**Docker: permission denied to docker.sock**

* Linux: `sudo usermod -aG docker $USER && newgrp docker` and re‑try `docker compose ...`.

**Python (PEP 668) “externally‑managed‑environment”**

* Use a **virtualenv**: `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`

---

## Security Notes

* Keep `.env` **out of Git**; rotate credentials if they leak.
* Use **trusted CA** verification in any shared/staging/prod environment. The `S360_TLS_RELAX_HOSTNAME` switch is **dev‑only**.
* Scope Substation360 access (Basic/Enhanced/Premium) to the least privilege needed.

---

## Roadmap

* Add more telemetry endpoints: Active/Reactive/ Apparent Power means, Voltage min/max, THD, Transformer temperature (30‑minute capture).
* Idempotent **backfill** tooling + gap detection.
* Views for ML feature extraction; export to Parquet.
* CI/CD + scheduled jobs + observability (metrics/logs).

---

## References

* **Postman collection** (Auth, Instruments, telemetry GET with JSON body): *Integration APIs.postman\_collection.json*.&#x20;
* **Customer PDF** (auth flow, TLS notes, examples): *Substation360 API Integration – Customer Instructions* (see `/docs`).

---

## License

This project is licensed under the MIT License – see the [LICENSE](LICENSE) file for details.

---

### Tip for reviewers

Open **`/docs`**, run **`POST /ingest/instruments`**, then **`POST /ingest/voltage-mean-10m`** and **`/ingest/current-mean-10m`**, then **`GET /metrics/ingest-summary`**. If the vendor certs are still in flux, use the provided CA file and `S360_TLS_RELAX_HOSTNAME=true` *for local dev only*.
