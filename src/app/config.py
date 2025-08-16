from pydantic_settings import BaseSettings
from pydantic import AnyHttpUrl, SecretStr

class Settings(BaseSettings):
    S360_AUTH_URL: AnyHttpUrl = "https://auth.substation360ig.co.uk/api/token"
    S360_BASE_URL: AnyHttpUrl = "https://integration.substation360ig.co.uk/api"
    S360_USERNAME: str
    S360_PASSWORD: SecretStr
    S360_VERIFY_SSL: bool = True
    S360_CA_CERT_PATH: str | None = None
    S360_TLS_RELAX_HOSTNAME: bool = False
    DATABASE_URL: str

    class Config:
        env_file = ".env"

settings = Settings()
