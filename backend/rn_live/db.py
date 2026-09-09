from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, create_engine, event
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


def database(url):
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    return engine, sessionmaker(engine, expire_on_commit=False)
