import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


class TelemetrySample(Base):
    """Every simulated/propagated reading, recorded on every tick, for every channel."""
    __tablename__ = "telemetry_samples"
    id = Column(Integer, primary_key=True, autoincrement=True)
    satellite_id = Column(String, index=True)
    channel_id = Column(String, index=True)
    ts = Column(DateTime, default=utcnow, index=True)
    value = Column(Float)
    status = Column(String)          # nominal | watch | anomaly
    severity = Column(Integer)
    z_score = Column(Float)
    baseline_mean = Column(Float)
    baseline_std = Column(Float)


class AnomalyEvent(Base):
    """One row per continuous anomaly episode on a channel (opened when status -> anomaly,
    closed when it drops back below watch)."""
    __tablename__ = "anomaly_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    satellite_id = Column(String, index=True)
    channel_id = Column(String)
    ts_start = Column(DateTime, default=utcnow)
    ts_end = Column(DateTime, nullable=True)
    peak_severity = Column(Integer, default=0)
    peak_z = Column(Float, default=0.0)
    resolved = Column(Boolean, default=False)


class Diagnosis(Base):
    """AI-generated (or local-template-fallback) narrative for a specific anomaly event."""
    __tablename__ = "diagnoses"
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, index=True)
    narrative = Column(Text)
    source = Column(String)          # 'claude' | 'local_template'
    created_at = Column(DateTime, default=utcnow)


class FaultInjection(Base):
    """Audit trail of manually-injected test faults, separate from real detected anomalies."""
    __tablename__ = "fault_injections"
    id = Column(Integer, primary_key=True, autoincrement=True)
    satellite_id = Column(String, index=True)
    fault_type = Column(String)
    ts_start = Column(DateTime, default=utcnow)
