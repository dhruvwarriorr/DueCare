import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def now():
    return datetime.now(UTC)


class Owned:
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID, index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Profile(Base):
    __tablename__ = "profiles"
    __table_args__ = {"schema": "duecare"}
    user_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Subject(Owned, Base):
    __tablename__ = "subjects"
    __table_args__ = (
        UniqueConstraint("id", "user_id"),
        CheckConstraint("kind in ('theory','lab','tutorial')"),
        {"schema": "duecare"},
    )
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))
    data: Mapped[dict] = mapped_column(JSONB, default=dict)


class Slot(Owned, Base):
    __tablename__ = "subject_timetable_slots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["subject_id", "user_id"], ["duecare.subjects.id", "duecare.subjects.user_id"], ondelete="CASCADE"
        ),
        {"schema": "duecare"},
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID, index=True)
    data: Mapped[dict] = mapped_column(JSONB)


class Task(Owned, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("id", "user_id"),
        ForeignKeyConstraint(["subject_id", "user_id"], ["duecare.subjects.id", "duecare.subjects.user_id"]),
        CheckConstraint("type in ('assignment','test')"),
        CheckConstraint("status in ('due','completed','overdue','missed')"),
        CheckConstraint("status != 'overdue' or type = 'assignment'"),
        CheckConstraint("status != 'missed' or type = 'test'"),
        {"schema": "duecare"},
    )
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID, nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    type: Mapped[str] = mapped_column(String(20))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="due")
    data: Mapped[dict] = mapped_column(JSONB, default=dict)


class History(Owned, Base):
    __tablename__ = "task_history"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "user_id"], ["duecare.tasks.id", "duecare.tasks.user_id"], ondelete="CASCADE"
        ),
        {"schema": "duecare"},
    )
    task_id: Mapped[uuid.UUID] = mapped_column(UUID, index=True)
    action: Mapped[str] = mapped_column(String(30))
    changes: Mapped[dict] = mapped_column(JSONB)


class WebSession(Base):
    __tablename__ = "web_sessions"
    __table_args__ = {"schema": "duecare_internal"}
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID)
    tokens: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LoginState(Base):
    __tablename__ = "login_states"
    __table_args__ = {"schema": "duecare_internal"}
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    verifier: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Operation(Owned, Base):
    __tablename__ = "operations"
    __table_args__ = (UniqueConstraint("user_id", "key"), {"schema": "duecare"})
    key: Mapped[str] = mapped_column(String(100))
    fingerprint: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSONB)
