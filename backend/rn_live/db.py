from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, create_engine, event, inspect, select, text, update
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Recording(Base):
    __tablename__ = "recordings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))
    speaker_count: Mapped[int] = mapped_column(Integer)
    content_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    scope: Mapped[str] = mapped_column(String(200), default="")
    filename: Mapped[str] = mapped_column(String(255))
    suffix: Mapped[str] = mapped_column(String(5))
    duration_ms: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="received")
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    speakers: Mapped[list] = mapped_column(JSON, default=list)
    segments: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.id", ondelete="CASCADE"), index=True)
    recording_revision: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30), default="claim_extraction")
    status: Mapped[str] = mapped_column(String(20), default="queued")
    provider: Mapped[str] = mapped_column(String(30), default="openrouter")
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(30), default="claims-v1")
    usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    unreviewed_segment_count: Mapped[int] = mapped_column(Integer, default=0)
    token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Claim(Base):
    __tablename__ = "claims"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True)
    normalized_text: Mapped[str] = mapped_column(String(2000))
    original_quote: Mapped[str] = mapped_column(String(4000))
    category: Mapped[str] = mapped_column(String(30))
    verifiable: Mapped[bool] = mapped_column(default=True)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    ambiguity_notes: Mapped[list] = mapped_column(JSON, default=list)
    missing_context: Mapped[list] = mapped_column(JSON, default=list)
    position: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    revision: Mapped[int] = mapped_column(Integer, default=0)


class ClaimSegment(Base):
    __tablename__ = "claim_segments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    segment_id: Mapped[str] = mapped_column(String(36))
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    speaker_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    speaker_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)


def mark_claims_stale(session, recording_id, reason="La revisión del transcript cambió"):
    affected_runs = select(AnalysisRun.id).where(
        AnalysisRun.recording_id == recording_id,
        AnalysisRun.status.in_(("queued", "running", "completed")),
    )
    session.execute(
        update(Claim)
        .where(Claim.analysis_run_id.in_(affected_runs), Claim.status != "stale")
        .values(status="stale", revision=Claim.revision + 1)
    )
    session.execute(
        update(AnalysisRun)
        .where(
            AnalysisRun.recording_id == recording_id,
            AnalysisRun.status.in_(("queued", "running", "completed")),
        )
        .values(status="stale", error=reason, completed_at=now(), token=None, lease_until=None)
    )


def database(url):
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    return engine, sessionmaker(engine, expire_on_commit=False)


def initialize_database(engine):
    Base.metadata.create_all(engine)
    additions = {
        "analysis_runs": {
            "unreviewed_segment_count": "INTEGER NOT NULL DEFAULT 0",
            "token": "VARCHAR(36)",
            "lease_until": "TIMESTAMP",
            "attempts": "INTEGER NOT NULL DEFAULT 0",
        },
        "claims": {
            "status": "VARCHAR(20) NOT NULL DEFAULT 'proposed'",
            "revision": "INTEGER NOT NULL DEFAULT 0",
        },
        "claim_segments": {"speaker_name": "VARCHAR(100)"},
    }
    inspector = inspect(engine)
    with engine.begin() as connection:
        for table_name, definitions in additions.items():
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, definition in definitions.items():
                if column_name not in existing:
                    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))
