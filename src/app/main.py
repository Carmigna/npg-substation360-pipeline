from fastapi import FastAPI
from src.app.clients.substation360 import get_token

app = FastAPI(title="NPG Substation360 Pipeline Demo")

@app.get("/healthz")
def healthz():
    # simple "does auth config parse?" liveness
    return {"status": "ok"}
