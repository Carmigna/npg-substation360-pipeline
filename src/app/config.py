# src/app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr

class Settings(BaseSettings):
    # load .env and ignore unexpected keys
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Primary local DB (your demo DB) ---
    DATABASE_URL: str = "postgresql+psycopg://app:app@localhost:5432/s360"
    DB_ECHO: bool = False

    # --- Substation360 endpoints & TLS ---
    S360_AUTH_URL: str = "https://auth.substation360ig.co.uk/api/token"
    S360_BASE_URL: str = "https://integration.substation360ig.co.uk/api"
    S360_USERNAME: str = ""
    S360_PASSWORD: SecretStr = SecretStr("")
    S360_VERIFY_SSL: bool = True
    S360_CA_CERT_PATH: str | None = None
    S360_TLS_RELAX_HOSTNAME: bool = False  # dev-only toggle

    # --- Optional cloud sink (replication target) ---
    ENABLE_CLOUD_SINK: bool = False
    CLOUD_DB_URL: str | None = None
    CLOUD_DB_ECHO: bool = False

settings = Settings()
