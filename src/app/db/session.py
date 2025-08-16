from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from src.app.config import settings

# engine = create_engine(settings.DATABASE_URL, future=True)
# SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


# Primary (already present)
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, echo=settings.DB_ECHO)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

# Optional cloud sink
if settings.ENABLE_CLOUD_SINK and settings.CLOUD_DB_URL:
    cloud_engine = create_engine(settings.CLOUD_DB_URL, pool_pre_ping=True, echo=settings.CLOUD_DB_ECHO, future=True)
    CloudSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cloud_engine, future=True)
else:
    cloud_engine = None
    CloudSessionLocal = None

class Base(DeclarativeBase):
    pass
