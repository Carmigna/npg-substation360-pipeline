from typing import Any, Iterable
import httpx, os
from loguru import logger
from . import typing as _t  # optional: create typing stubs if you like
from src.app.config import settings

def _verify_arg():
    # Prefer user-provided CA path, else bool
    if settings.S360_CA_CERT_PATH and os.path.exists(settings.S360_CA_CERT_PATH):
        return settings.S360_CA_CERT_PATH
    return settings.S360_VERIFY_SSL

def get_token() -> str:
    payload = {
        "grant_type": "password",
        "clienttype": "user",
        "username": settings.S360_USERNAME,
        "password": settings.S360_PASSWORD.get_secret_value(),
    }
    # Auth is a form post per Postman collection
    with httpx.Client(verify=_verify_arg(), timeout=30) as client:
        r = client.post(str(settings.S360_AUTH_URL), data=payload)
        r.raise_for_status()
        token = r.json().get("token")
        if not token:
            raise RuntimeError("Auth succeeded but 'token' not in response")
        logger.info("Obtained S360 token")
        return token

def list_instruments(token: str) -> list[dict[str, Any]]:
    url = f"{settings.S360_BASE_URL}/instrument"
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(verify=_verify_arg(), timeout=60) as client:
        r = client.get(url, headers=headers)
        r.raise_for_status()
        data = r.json()
        return data

def voltage_mean_30min(
    token: str, instrument_ids: Iterable[int], from_iso: str, to_iso: str
) -> list[dict[str, Any]]:
    """
    GET with JSON body (array of instrument IDs) + from/to params.
    This shape mirrors the Postman request in your collection.
    """
    url = f"{settings.S360_BASE_URL}/voltage/mean/30min"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = list(instrument_ids)
    params = {"from": from_iso, "to": to_iso}
    with httpx.Client(verify=_verify_arg(), timeout=60) as client:
        r = client.get(url, headers=headers, params=params, json=body)
        r.raise_for_status()
        return r.json()
