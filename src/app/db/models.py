from sqlalchemy import Column, Integer, String, Boolean, JSON, DateTime, BigInteger, Index
from sqlalchemy.sql import func
from src.app.db.session import Base

class Instrument(Base):
    __tablename__ = "instrument"
    id = Column(BigInteger, primary_key=True)   # from Substation360
    name = Column(String, nullable=True)
    commissioned = Column(Boolean, nullable=True)
    metadata = Column(JSON)

class RawMeasurement(Base):
    __tablename__ = "raw_measurement"
    id = Column(Integer, primary_key=True, autoincrement=True)
    endpoint = Column(String, nullable=False)   # e.g., voltage/mean/30min
    instrument_id = Column(BigInteger, nullable=False)
    payload = Column(JSON, nullable=False)      # exact server row
    ingested_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index("ix_raw_instr_endpoint", "instrument_id", "endpoint"),)
