# npg-substation360-pipeline
# NPG Substation360 Pipeline Demo

**Goal:** Stand up a small, production‑shaped data pipeline that authenticates to EA Technology’s **Substation360 Integration API**, discovers **Instruments**, fetches **30‑minute captured telemetry** (e.g., voltage/current mean), lands raw payloads into Postgres (bronze), and normalizes into query‑ready tables (silver). This repo is designed for **VS Code** (local) and **GitHub Codespaces** (zero‑install) workflows.

> ℹ️ **Granularity:** The Integration API exposes *30‑minute capture* for core telemetry. Examples include *Voltage min/mean/max*, *Current mean*, *Power (active/reactive) arithmetic mean*, *THD*, and *Transformer temperature*. Second‑level or 10‑minute endpoints are **not** in this Integration API. See “Available APIs” in the manual.

---

## Table of contents

* [Architecture](#architecture)
* [Repo structure](#repo-structure)
* [Prerequisites](#prerequisites)
* [Quickstart (VS Code)](#quickstart-vs-code)
* [Quickstart (Codespaces)](#quickstart-codespaces)
* [Configuration (.env)](#configuration-env)
* [TLS / Certificates](#tls--certificates)
* [Database](#database)
* [Runbook](#runbook)
* [API surface (FastAPI)](#api-surface-fastapi)
* [Troubleshooting](#troubleshooting)
* [Security notes](#security-notes)
* [Roadmap](#roadmap)
* [References](#references)
* [License](#license)

---

## Architecture

**Data flow**

1. **Auth** → `POST /api/token` (Substation360 Auth).
2. **Discover** → `GET /api/instrument` (list VisNet instruments you can access).
3. **Ingest** → e.g. `GET /api/voltage/mean/30min?from=...&to=...` with **JSON body = \[instrumentIds]**.
4. **Land raw** → store exact JSON rows in `raw_measurement` (bronze).
5. **Normalize** → extract canonical fields into `voltage_mean_30m`, `current_mean_30m` (silver).
6. **Serve** → views for analytics/ML feature extraction.

> The manual and Postman collection show the **Auth** endpoint and the **Instruments** + telemetry endpoints, including the unusual **GET with JSON body** pattern and the typical **30‑day look‑back** for `from`.

---

## Repo structure

```
npg-substation360-pipeline/
├─ .devcontainer/
│  ├─ devcontainer.json          # Dev Container for VS Code/Codespaces
│  └─ docker-compose.yml         # Postgres service
├─ src/
│  ├─ app/
│  │  ├─ main.py                 # FastAPI app (health & ingest handlers)
│  │  ├─ config.py               # Settings (.env via pydantic-settings)
│  │  ├─ clients/substation360.py# HTTP client (auth, list instruments, pulls)
│  │  ├─ db/session.py           # SQLAlchemy engine/session
│  │  ├─ db/models.py            # ORM models (Instrument, RawMeasurement)
│  │  ├─ ingest/run_ingest.py    # CLI: auth/instruments/ingest demos
│  │  └─ ingest/normalize.py     # Bronze → Silver normalization
├─ tests/                        # (optional) pytest
├─ docs/
│  ├─ Substation360 API Integration - Customer Instructions.pdf
│  └─ Integration APIs.postman_collection.json
├─ requirements.txt
├─ Makefile
├─ .env.template
└─ README.md
```

---

## Prerequisites

* **VS Code** and **Docker Desktop** (for Dev Containers), or **GitHub Codespaces**.
* **Python 3.11+**
* **Git** and a GitHub repo (private or public).

---

## Quickstart (VS Code)

1. **Clone and open**

```bash
git clone https://github.com/carmigna/npg-substation360-pipeline.git
cd npg-substation360-pipeline
```

2. **Create your env file**

```bash
cp .env.template .env
# then edit .env (see .env section below)
```

3. **(Optional) Reopen in Dev Container**
   VS Code → Command Palette → *Dev Containers: Reopen in Container*.
   This spins up Python & Postgres per `.devcontainer/docker-compose.yml`.

4. **Install & init DB**

```bash
pip install -r requirements.txt
make db-init
```

5. **Run the app**

```bash
make run
# Health check
curl -s localhost:8000/healthz
```

**Expected:** `{"status":"ok"}`

---

## Quickstart (Codespaces)

* GitHub → your repo → **Code** → **Codespaces** → **Create codespace**.
* In the Codespace terminal:

  ```bash
  cp .env.template .env
  # set S360_USERNAME/S360_PASSWORD in .env
  make setup
  make db-init
  make run
  ```

---

## Configuration (.env)

```ini
# Substation360 Integration API
S360_AUTH_URL=https://auth.substation360ig.co.uk/api/token
S360_BASE_URL=https://integration.substation360ig.co.uk/api
S360_USERNAME=__set_me__
S360_PASSWORD=__set_me__
# TLS (see “TLS / Certificates” below)
S360_VERIFY_SSL=true
S360_CA_CERT_PATH=

# Database (local dev example)
DATABASE_URL=postgresql+psycopg://app:app@localhost:5432/s360
```

* **S360\_AUTH\_URL / S360\_BASE\_URL** — fixed per the Integration API.
* **S360\_USERNAME / S360\_PASSWORD** — Substation360 credentials (obtained from EA Technology). The manual shows the **token grant** flow used to acquire the bearer token.
* **S360\_VERIFY\_SSL / S360\_CA\_CERT\_PATH** — see [TLS / Certificates](#tls--certificates).

---

## TLS / Certificates

The Integration API uses **EA Technology self‑signed certificates**. For local tools you can either:

* **Import the EA root CA** into your machine’s **Trusted Root Certification Authorities**, or
* Temporarily **disable SSL verification** in tooling while testing (not for production).

The manual includes step‑by‑step import screenshots and notes on Postman’s “Disable SSL verification” toggle. This repo supports both: set `S360_CA_CERT_PATH` to the CA file, or set `S360_VERIFY_SSL=false` during initial connectivity tests.

---

## Database

* **Bronze**: `raw_measurement` stores the **exact JSON** returned by Substation360 per endpoint.
* **Silver**: canonical tables (e.g., `voltage_mean_30m`, `current_mean_30m`) with:

  * `instrument_id`, `ts_utc`, `phase` (A/B/C/TOTAL), `value`, `unit`
  * **PK** on `(instrument_id, ts_utc, phase)` for idempotent upserts.

> You can request data with `from` up to **30 days ago**, passing *Instrument IDs* in a **JSON array body** and specifying `from`/`to` in the query string. The manual demonstrates this pattern and shows *Instruments* being called first to discover IDs.

---

## Runbook

### 1) Smoke test auth

```bash
make auth-smoke
```

* Calls `POST /api/token` with `grant_type=password`, `clienttype=user`, `username`, `password`.
* **Pass:** “Auth OK (token acquired)”. (See Postman “01 - Auth API”.)&#x20;

### 2) Discover instruments + persist metadata

```bash
make instruments-smoke
```

* Calls `GET /api/instrument` with Bearer token; upserts to `instrument` table. (Postman “02 - Instruments”.)&#x20;

### 3) (Optional) Ingest a small demo window

```bash
# Example: voltage mean, last 2 hours, first 3 instruments
python -m src.app.ingest.run_ingest voltage_mean_30min --hours 2 --limit 3
```

* Calls `GET /api/voltage/mean/30min?from=...&to=...` with **JSON body = \[instrumentId, ...]**.
* Lands raw rows → normalizes into `voltage_mean_30m`. (See Postman request and manual screenshots.)

---

## API surface (FastAPI)

When `make run` is active:

* `GET /healthz` — liveness probe.
* *(If included in your branch)* `POST /ingest/voltage-mean-30m?hours=2&limit=3` — fetch, land, normalize (demo).

---

## Troubleshooting

* **SSL / certificate errors**
  Import the EA root CA into **Trusted Root Certification Authorities** (Windows wizard shown in manual), or set `S360_VERIFY_SSL=false` temporarily.&#x20;

* **401/403 after auth**
  Ensure you are passing the **Bearer** token returned from `/api/token`. In Postman, the manual shows setting an **environment variable `token`** from the auth response and reusing it in subsequent calls.

* **No data returned**
  Verify your **access level** (Basic/Enhanced/Premium) grants you the requested endpoints, and keep your `from` within the **30‑day window**. See *Available APIs* and *Access Levels*.&#x20;

* **GET with body?**
  Yes—per Integration API examples, telemetry endpoints accept **instrument IDs in the JSON body** and `from`/`to` as query params. Match the Postman collection exactly.

---

## Security notes

* **Never commit** real secrets. Use `.env` locally; keep `.env` out of Git.
* Prefer **trusted CA import** over disabling SSL in production.&#x20;
* Scope API credentials to only required access (Basic/Enhanced/Premium per your contract).&#x20;

---

## Roadmap

* Add additional endpoints: **power/active/mean/30min**, **power/reactive/mean/30min**, **THD**, **transformer temperature** (all 30‑minute capture).&#x20;
* Idempotent **backfill** tooling with gap detection.
* **Views** for ML feature extraction and export to Parquet.
* **Scheduler** (cron/K8s) + observability (metrics/logging) for productionization.

---

## References

* **Manual:** *Substation360 API Integration — Customer Instructions* (Auth flow, TLS, Postman usage, 30‑minute capture, Swagger).
* **Postman collection:** *Integration APIs.postman\_collection.json* (Auth token endpoint, Instruments endpoint, example telemetry calls).

---

## License

choose one for your repo.

---

### Badges (optional)

Add CI badges here once you wire up GitHub Actions.

---

**Tip for reviewers:** Start at **Runbook → 1) Auth**, then **2) Instruments**, then trigger a **small ingest** and query `voltage_mean_30m` to verify end‑to‑end. The **30‑minute** cadence is by design per the Integration API.&#x20;
