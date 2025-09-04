from sqlalchemy import Column, Integer, String, Boolean, JSON, DateTime, BigInteger, Index, Float
from sqlalchemy.sql import func
from src.app.db.session import Base

class Instrument(Base):
    __tablename__ = "instrument"
    id = Column(BigInteger, primary_key=True)
    name = Column(String, nullable=True)
    commissioned = Column(Boolean, nullable=True)
    # OLD (bad): metadata = Column(JSON)
    # NEW (good): Python attr 'meta' mapped to DB column 'metadata'
    meta = Column("metadata", JSON)

class RawMeasurement(Base):
    __tablename__ = "raw_measurement"
    id = Column(Integer, primary_key=True, autoincrement=True)
    endpoint = Column(String, nullable=False)
    instrument_id = Column(BigInteger, nullable=False)
    payload = Column(JSON, nullable=False)
    ingested_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index("ix_raw_instr_endpoint", "instrument_id", "endpoint"),)

class VoltageMean10m(Base):
    __tablename__ = "voltage_mean_10m"
    instrument_id = Column(BigInteger, primary_key=True)
    ts_utc = Column(DateTime(timezone=True), primary_key=True)
    phase = Column(String, primary_key=True)        # 'A','B','C','TOTAL'
    value = Column(Float)
    unit = Column(String)

class CurrentMean10m(Base):
    __tablename__ = "current_mean_10m"
    instrument_id = Column(BigInteger, primary_key=True)
    ts_utc = Column(DateTime(timezone=True), primary_key=True)
    phase = Column(String, primary_key=True)
    value = Column(Float)
    unit = Column(String)
