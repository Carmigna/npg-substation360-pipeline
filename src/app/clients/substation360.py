import os
import ssl
import datetime as dt
import httpx
from loguru import logger
from src.app.config import settings
import json as _json

def _verify_arg():
    """
    Returns one of:
      - SSLContext with hostname relaxed (dev only), or
      - CA bundle path, or
      - bool verify flag
    """
    ca_path = settings.S360_CA_CERT_PATH if (settings.S360_CA_CERT_PATH and os.path.exists(settings.S360_CA_CERT_PATH)) else None
    if getattr(settings, "S360_TLS_RELAX_HOSTNAME", False):
        ctx = ssl.create_default_context(cafile=ca_path)
        ctx.check_hostname = False
        return ctx
    return ca_path if ca_path else settings.S360_VERIFY_SSL

def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

def _iso_z(value) -> str:
    """Return ISO-8601 with .000Z (Postman style) if given a datetime; pass through strings."""
    if isinstance(value, dt.datetime):
        # Assume UTC-aware or naive UTC; format with milliseconds .000Z
        return value.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return str(value)

def get_token() -> str:
    """
    POST /api/token with multipart form-data (as in Postman).
    Falls back to x-www-form-urlencoded if the server rejects multipart.
    """
    payload = {
        "grant_type": "password",
        "clienttype": "user",
        "username": settings.S360_USERNAME,
        "password": settings.S360_PASSWORD.get_secret_value(),
    }
    verify = _verify_arg()
    with httpx.Client(verify=verify, timeout=30) as client:
        # 1) Try multipart/form-data (Postman behavior)
        files = {k: (None, v) for k, v in payload.items()}
        r = client.post(str(settings.S360_AUTH_URL), files=files)
        if r.status_code == 415 or ("Unsupported Media Type" in r.text):
            # 2) Fallback: application/x-www-form-urlencoded
            r = client.post(str(settings.S360_AUTH_URL), data=payload)
        r.raise_for_status()
        data = r.json()
        token = data.get("token") or data.get("access_token")
        if not token:
            raise RuntimeError(f"Auth OK but no token in response keys={list(data.keys())}")
        logger.info("S360 token acquired")
        return token

def list_instruments(token: str):
    """
    GET /api/instrument (Bearer).
    Accepts wrapper dicts like {items:[...]} or returns raw list.
    """
    url = f"{settings.S360_BASE_URL}/instrument"
    with httpx.Client(verify=_verify_arg(), timeout=60) as client:
        r = client.get(url, headers=_auth_headers(token))
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            for k in ("items", "data", "results", "instruments"):
                if k in data and isinstance(data[k], list):
                    return data[k]
        return data

def voltage_mean_30min(token: str, instrument_ids: list[int], from_dt, to_dt):
    """
    GET /api/voltage/mean/30min?from=...&to=...
    Body: JSON array of instrument IDs (Content-Type: application/json).
    Uses client.request() because some httpx versions don't accept json= on .get().
    """
    url = f"{settings.S360_BASE_URL}/voltage/mean/30min"
    params = {"from": _iso_z(from_dt), "to": _iso_z(to_dt)}
    headers = _auth_headers(token) | {"Content-Type": "application/json"}
    verify = _verify_arg()
    payload = list(instrument_ids)

    with httpx.Client(verify=verify, timeout=60) as client:
        # Method A: request() with json=
        try:
            r = client.request("GET", url, headers=headers, params=params, json=payload)
        except TypeError:
            # Very old httpx: fallback to build_request + send
            req = client.build_request(
                "GET", url, headers=headers, params=params, content=_json.dumps(payload)
            )
            r = client.send(req)
        r.raise_for_status()
        return r.json()

def current_mean_30min(token: str, instrument_ids: list[int], from_dt, to_dt):
    """
    GET /api/current/mean/30min?from=...&to=...
    Body: JSON array of instrument IDs (Content-Type: application/json).
    """
    url = f"{settings.S360_BASE_URL}/current/mean/30min"
    params = {"from": _iso_z(from_dt), "to": _iso_z(to_dt)}
    headers = _auth_headers(token) | {"Content-Type": "application/json"}
    verify = _verify_arg()
    payload = list(instrument_ids)

    with httpx.Client(verify=verify, timeout=60) as client:
        try:
            r = client.request("GET", url, headers=headers, params=params, json=payload)
        except TypeError:
            req = client.build_request(
                "GET", url, headers=headers, params=params, content=_json.dumps(payload)
            )
            r = client.send(req)
        r.raise_for_status()
        return r.json()
