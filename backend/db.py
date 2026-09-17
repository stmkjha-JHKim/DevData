"""backend/db.py -- local metadata store (SQLite via SQLAlchemy) for
everything that ISN'T an Oracle credential: backup policies, job run
history, recovery-check history. Oracle credentials themselves live in
registered_dbs.py's separate encrypted file store instead (see that
module's docstring) -- this file only ever holds a `db_id` reference to
one of those records, never a password.

This mirrors the earlier OraVault Backup design decision (see project
memory / the RMAN-based prototype this one supersedes): SQLAlchemy +
SQLite for policy/schedule/history metadata, single-admin, no multi-user
model yet.
"""

import time
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from paths import ensure_data_dir

Base = declarative_base()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"


class BackupPolicy(Base):
    __tablename__ = "backup_policies"

    id = Column(String, primary_key=True, default=lambda: _new_id("pol"))
    name = Column(String, nullable=False)
    db_id = Column(String, nullable=False)

    # FULL / SCHEMA / TABLE -- see backend/datapump.py's job_mode mapping.
    scope = Column(String, nullable=False, default="FULL")
    # SCHEMA: comma-separated schema list, e.g. "MES,MES_HIST".
    # TABLE: "SCHEMA:TABLE1,TABLE2" -- a single owning schema plus its
    # table list (see datapump.py's known limitation on this).
    scope_value = Column(String, nullable=True)

    directory_object = Column(String, nullable=False, default="DATA_PUMP_DIR")
    dump_file_pattern = Column(String, nullable=False, default="%POLICY%_%DATE%.dmp")
    # DBMS_DATAPUMP's actual COMPRESSION values -- NOT the BASIC/LOW/MEDIUM/
    # HIGH scale (that's the separate, Advanced-Compression-licensed
    # COMPRESSION_ALGORITHM parameter this app doesn't set).
    compression = Column(String, nullable=False, default="METADATA_ONLY")  # NONE/DATA_ONLY/METADATA_ONLY/ALL
    parallel_degree = Column(Integer, nullable=False, default=1)
    content = Column(String, nullable=False, default="ALL")  # ALL/DATA_ONLY/METADATA_ONLY

    # DAILY (schedule_time="HH:MM"), WEEKLY (+ schedule_weekday 0=Mon),
    # INTERVAL_HOURS (interval_hours=N). See backend/scheduler.py.
    schedule_kind = Column(String, nullable=False, default="DAILY")
    schedule_time = Column(String, nullable=True)
    schedule_weekday = Column(Integer, nullable=True)
    interval_hours = Column(Integer, nullable=True)

    retention_days = Column(Integer, nullable=False, default=14)
    rpo_tier = Column(String, nullable=False, default="TIER2")  # TIER1 (<=1h/<=4h) / TIER2 (<=24h/<=24h)
    notify_email = Column(String, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class JobRun(Base):
    __tablename__ = "job_runs"

    id = Column(String, primary_key=True, default=lambda: _new_id("run"))
    policy_id = Column(String, nullable=True)
    policy_name = Column(String, nullable=False)  # denormalized: survives policy deletion
    db_id = Column(String, nullable=False)
    db_name = Column(String, nullable=False)

    run_type = Column(String, nullable=False, default="EXPORT")  # EXPORT / IMPORT
    status = Column(String, nullable=False, default="RUNNING")  # RUNNING / SUCCESS / FAILED
    trigger = Column(String, nullable=False, default="MANUAL")  # MANUAL / SCHEDULED

    # The actual DBMS_DATAPUMP job name, set as soon as START_JOB succeeds --
    # lets a still-RUNNING row be polled for live progress against Oracle's
    # own USER_DATAPUMP_JOBS/V$SESSION_LONGOPS (see datapump.query_job_progress)
    # without needing to keep the export connection open for the whole job.
    job_name = Column(String, nullable=True)

    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)

    dump_file = Column(String, nullable=True)
    dump_size_bytes = Column(Integer, nullable=True)
    log_text = Column(Text, nullable=True)
    error_text = Column(Text, nullable=True)


class RecoveryCheck(Base):
    __tablename__ = "recovery_checks"

    id = Column(String, primary_key=True, default=lambda: _new_id("rcv"))
    db_id = Column(String, nullable=False)
    db_name = Column(String, nullable=False)
    source_run_id = Column(String, nullable=True)

    checked_at = Column(DateTime, default=datetime.utcnow)
    result = Column(String, nullable=False, default="PENDING")  # PENDING / SUCCESS / FAILED
    measured_rto_seconds = Column(Float, nullable=True)
    note = Column(Text, nullable=True)


_engine = None
SessionLocal = None


def init_db():
    global _engine, SessionLocal
    if _engine is not None:
        return
    data_dir = ensure_data_dir()
    _engine = create_engine(
        f"sqlite:///{data_dir}/metadata.db",
        connect_args={"check_same_thread": False},
    )
    SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(_engine)


def get_session():
    if SessionLocal is None:
        init_db()
    return SessionLocal()
