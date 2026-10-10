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
        CheckConstraint("status in ('due','completed','missed')", name="tasks_status_check"),
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


# Phase 2: source authorization and resumable imports.
def owner_fk(columns, table, ondelete="CASCADE"):
    return ForeignKeyConstraint(
        [columns, "user_id"], [f"duecare.{table}.id", f"duecare.{table}.user_id"], ondelete=ondelete
    )


class GoogleAccount(Owned, Base):
    __tablename__ = "google_accounts"
    __table_args__ = (
        UniqueConstraint("id", "user_id"),
        UniqueConstraint("user_id", "google_sub"),
        {"schema": "duecare"},
    )
    google_sub: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320))
    data: Mapped[dict] = mapped_column(JSONB, default=dict)


class OAuthGrant(Owned, Base):
    __tablename__ = "oauth_grants"
    __table_args__ = (
        UniqueConstraint("account_id"),
        owner_fk("account_id", "google_accounts"),
        CheckConstraint("status in ('active','revoked','invalid')"),
        {"schema": "duecare"},
    )
    account_id: Mapped[uuid.UUID] = mapped_column(UUID)
    scopes: Mapped[list] = mapped_column(JSONB, default=list)
    refresh_token: Mapped[str | None] = mapped_column(String, nullable=True)
    access_token: Mapped[str | None] = mapped_column(String, nullable=True)
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    key_version: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="active")


class Connection(Owned, Base):
    __tablename__ = "connections"
    __table_args__ = (
        UniqueConstraint("id", "user_id"),
        UniqueConstraint("account_id", "service"),
        owner_fk("account_id", "google_accounts"),
        CheckConstraint("service in ('gmail','classroom')"),
        CheckConstraint("status in ('active','needs_reauth','disconnected')"),
        {"schema": "duecare"},
    )
    account_id: Mapped[uuid.UUID] = mapped_column(UUID, index=True)
    service: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="active")
    scopes: Mapped[list] = mapped_column(JSONB, default=list)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checkpoint: Mapped[dict] = mapped_column(JSONB, default=dict)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)


class SourceCourse(Owned, Base):
    __tablename__ = "source_courses"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_course_id"),
        owner_fk("connection_id", "connections"),
        {"schema": "duecare"},
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID, index=True)
    external_course_id: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(500))
    available: Mapped[bool] = mapped_column(default=True)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)


class SubjectMapping(Owned, Base):
    __tablename__ = "subject_mappings"
    __table_args__ = (
        UniqueConstraint("subject_id", "connection_id", "external_course_id"),
        owner_fk("subject_id", "subjects"),
        owner_fk("connection_id", "connections"),
        {"schema": "duecare"},
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID, index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID, index=True)
    external_course_id: Mapped[str] = mapped_column(String(100))
    source_available: Mapped[bool] = mapped_column(default=True)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)


class SourceRecord(Owned, Base):
    __tablename__ = "source_records"
    __table_args__ = (
        UniqueConstraint("id", "user_id"),
        UniqueConstraint("connection_id", "provider_id"),
        owner_fk("connection_id", "connections"),
        CheckConstraint(
            "processing_state in ('awaiting_interpretation','duplicate','blocked','ignored','unavailable',"
            "'interpreted','needs_review')",
            name="source_records_state",
        ),
        {"schema": "duecare"},
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID, index=True)
    provider_id: Mapped[str] = mapped_column(String(600))
    kind: Mapped[str] = mapped_column(String(40))
    external_course_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sender_email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    thread_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processing_state: Mapped[str] = mapped_column(String(30))
    processing_version: Mapped[str] = mapped_column(String(50))
    targeting_outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    excerpt: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)


class SourceAttachment(Owned, Base):
    __tablename__ = "source_attachments"
    __table_args__ = (owner_fk("source_record_id", "source_records"), {"schema": "duecare"})
    source_record_id: Mapped[uuid.UUID] = mapped_column(UUID, index=True)
    kind: Mapped[str] = mapped_column(String(30))
    title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SenderPreference(Owned, Base):
    __tablename__ = "sender_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "email"),
        CheckConstraint("action in ('include','block')"),
        {"schema": "duecare"},
    )
    email: Mapped[str] = mapped_column(String(320))
    action: Mapped[str] = mapped_column(String(10))


class SyncJob(Owned, Base):
    __tablename__ = "sync_jobs"
    __table_args__ = (
        owner_fk("connection_id", "connections"),
        CheckConstraint("mode in ('import','reprocess')"),
        CheckConstraint("status in ('queued','running','waiting_retry','completed','failed','cancelled')"),
        {"schema": "duecare"},
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID, index=True)
    mode: Mapped[str] = mapped_column(String(20))
    phase: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    checkpoint: Mapped[dict] = mapped_column(JSONB, default=dict)
    progress: Mapped[dict] = mapped_column(JSONB, default=dict)
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OAuthState(Base):
    __tablename__ = "oauth_states"
    __table_args__ = {"schema": "duecare_internal"}
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID)
    service: Mapped[str] = mapped_column(String(20))
    verifier: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# Phase 3: interpretation, review, rules, evidence, and merges.
class SourceEvent(Owned, Base):
    __tablename__ = "source_events"
    __table_args__ = (
        UniqueConstraint("id", "user_id"),
        UniqueConstraint("source_record_id", "event_key"),
        owner_fk("source_record_id", "source_records"),
        CheckConstraint(
            "event_type in ('new_work','revision','due_notice','supporting','submission','unsubmission',"
            "'withdrawal','unknown')"
        ),
        {"schema": "duecare"},
    )
    source_record_id: Mapped[uuid.UUID] = mapped_column(UUID, index=True)
    event_key: Mapped[str] = mapped_column(String(200))
    event_type: Mapped[str] = mapped_column(String(20))
    identity_key: Mapped[str | None] = mapped_column(String(600), nullable=True, index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str] = mapped_column(String(30))
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID, nullable=True, index=True)
    processing_version: Mapped[str] = mapped_column(String(50))
    data: Mapped[dict] = mapped_column(JSONB, default=dict)


class TaskEvidence(Owned, Base):
    __tablename__ = "task_evidence"
    __table_args__ = (
        UniqueConstraint("id", "user_id"),
        UniqueConstraint("task_id", "event_id"),
        owner_fk("task_id", "tasks"),
        owner_fk("event_id", "source_events"),
        CheckConstraint("state in ('active','reassigned')"),
        {"schema": "duecare"},
    )
    task_id: Mapped[uuid.UUID] = mapped_column(UUID, index=True)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID, index=True)
    method: Mapped[str] = mapped_column(String(30))
    state: Mapped[str] = mapped_column(String(20), default="active")


class ReviewItem(Owned, Base):
    __tablename__ = "review_items"
    __table_args__ = (
        UniqueConstraint("id", "user_id"),
        owner_fk("source_record_id", "source_records"),
        CheckConstraint("status in ('open','resolved','dismissed','suppressed')"),
        {"schema": "duecare"},
    )
    issue_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="open")
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID, nullable=True, index=True)
    source_record_id: Mapped[uuid.UUID | None] = mapped_column(UUID, nullable=True, index=True)
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID, nullable=True)
    sender_email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    question: Mapped[str] = mapped_column(String(500))
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Rule(Owned, Base):
    __tablename__ = "rules"
    __table_args__ = (UniqueConstraint("id", "user_id"), {"schema": "duecare"})
    name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)


class MergeOperation(Owned, Base):
    __tablename__ = "merge_operations"
    __table_args__ = (
        owner_fk("surviving_task_id", "tasks"),
        owner_fk("absorbed_task_id", "tasks"),
        {"schema": "duecare"},
    )
    surviving_task_id: Mapped[uuid.UUID] = mapped_column(UUID, index=True)
    absorbed_task_id: Mapped[uuid.UUID] = mapped_column(UUID, index=True)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Activity(Owned, Base):
    __tablename__ = "activity_notifications"
    __table_args__ = (UniqueConstraint("user_id", "event_key"), {"schema": "duecare"})
    event_key: Mapped[str] = mapped_column(String(200))
    event_type: Mapped[str] = mapped_column(String(30))
    target_type: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[uuid.UUID] = mapped_column(UUID)
    message: Mapped[str] = mapped_column(String(300))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Suppression(Owned, Base):
    __tablename__ = "suppression_records"
    __table_args__ = (UniqueConstraint("user_id", "namespace", "identity_hash"), {"schema": "duecare"})
    namespace: Mapped[str] = mapped_column(String(64))
    identity_hash: Mapped[str] = mapped_column(String(64))
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PrivacyJob(Owned, Base):
    __tablename__ = "privacy_jobs"
    __table_args__ = ({"schema": "duecare"},)
    kind: Mapped[str] = mapped_column(String(30))
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    stage: Mapped[str] = mapped_column(String(20), default="tasks")
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)


class AccountDeletion(Base):
    # Private capability checkpoint survives removal of native Auth and app sessions.
    __tablename__ = "account_deletions"
    __table_args__ = {"schema": "duecare_internal"}
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID, nullable=True, unique=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    stage: Mapped[str] = mapped_column(String(20), default="revoke")
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
