"""Resumable privacy operations. All app writes serialize with the owner's privacy lock.

Suppression hashes name one activity inside a source account, not a whole digest email.
Deleting source evidence never erases work backed by a different connection or student.
"""

import hashlib
import hmac
import uuid
from datetime import timedelta

from sqlalchemy import String, cast, delete, exists, select, text, update

from . import auth, google
from .config import settings
from .db import transaction
from .errors import ApiError
from .models import (
    AccountDeletion,
    Activity,
    Base,
    Connection,
    GoogleAccount,
    History,
    MergeOperation,
    OAuthGrant,
    OAuthState,
    Operation,
    PrivacyJob,
    ReviewItem,
    SourceEvent,
    SourceRecord,
    Suppression,
    Task,
    TaskEvidence,
    WebSession,
    now,
)


def owner_lock(db, uid):
    db.execute(text("select pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": f"privacy:{uid}"})


def namespace(db, conn):
    account = db.get(GoogleAccount, conn.account_id)
    return hashlib.sha256(f"{conn.service}:{account.google_sub}".encode()).hexdigest()


def identity_hash(key):
    return hashlib.sha256(key.encode()).hexdigest()


def suppressed(db, conn, key):
    return bool(
        key
        and db.scalar(
            select(Suppression.id).where(
                Suppression.user_id == conn.user_id,
                Suppression.namespace == namespace(db, conn),
                Suppression.identity_hash == identity_hash(key),
                Suppression.restored_at.is_(None),
            )
        )
    )


def suppress(db, conn, key):
    if not key:
        return
    ns, hashed = namespace(db, conn), identity_hash(key)
    row = db.scalar(
        select(Suppression).where(
            Suppression.user_id == conn.user_id,
            Suppression.namespace == ns,
            Suppression.identity_hash == hashed,
        )
    )
    if row:
        row.restored_at, row.updated_at = None, now()
        row.revision += 1
    else:
        db.add(Suppression(user_id=conn.user_id, namespace=ns, identity_hash=hashed))
    db.flush()


def task_suppression(db, task):
    rows = db.execute(
        select(SourceEvent, SourceRecord, Connection)
        .join(TaskEvidence, TaskEvidence.event_id == SourceEvent.id)
        .join(SourceRecord, SourceRecord.id == SourceEvent.source_record_id)
        .join(Connection, Connection.id == SourceRecord.connection_id)
        .where(TaskEvidence.task_id == task.id)
    ).all()
    for event, record, conn in rows:
        suppress(db, conn, event.identity_key or record.provider_id)
    # Detach stale references; do not resurrect a deleted task through reprocessing.
    db.execute(delete(ReviewItem).where(ReviewItem.task_id == task.id))
    db.execute(delete(Activity).where(Activity.target_type == "task", Activity.target_id == task.id))
    db.execute(
        update(Operation)
        .where(Operation.user_id == task.user_id, cast(Operation.result, String).contains(str(task.id)))
        .values(result={"privacyErased": True})
    )
    for event, _, _ in rows:
        event.task_id = None
    db.flush()


def cleanup(db, uid):
    """Bounded activity-driven purge; accepted evidence and active checkpoints never expire."""
    linked = exists(
        select(TaskEvidence.id)
        .join(SourceEvent, SourceEvent.id == TaskEvidence.event_id)
        .where(SourceEvent.source_record_id == SourceRecord.id)
    )
    ids = list(
        db.scalars(
            select(SourceRecord.id)
            .where(SourceRecord.user_id == uid, SourceRecord.expires_at <= now(), ~linked)
            .order_by(SourceRecord.id)
            .limit(100)
        )
    )
    if ids:
        review_ids = select(ReviewItem.id).where(ReviewItem.source_record_id.in_(ids))
        db.execute(
            delete(Activity).where(Activity.target_type == "review", Activity.target_id.in_(review_ids))
        )
        db.execute(delete(SourceRecord).where(SourceRecord.id.in_(ids)))
    old = now() - timedelta(days=30)
    receipts = list(
        db.scalars(
            select(AccountDeletion.id)
            .where(AccountDeletion.status == "completed", AccountDeletion.completed_at <= old)
            .limit(20)
        )
    )
    if receipts:
        db.execute(delete(AccountDeletion).where(AccountDeletion.id.in_(receipts)))


def job_out(job):
    return {
        "id": str(job.id),
        "kind": job.kind,
        "connectionId": str(job.connection_id),
        "status": job.status,
        "stage": job.stage,
        "progress": job.data,
        "errorCode": job.error_code,
        "revision": job.revision,
    }


def start_source(db, conn, kind):
    from .sync import cancel_jobs

    active = db.scalar(
        select(PrivacyJob).where(PrivacyJob.connection_id == conn.id, PrivacyJob.status != "completed")
    )
    if active:
        if active.kind != kind:
            raise ApiError(409, "PRIVACY_IN_PROGRESS", "Finish the existing privacy operation first")
        return active
    cancel_jobs(db, conn.id, "PRIVACY_REQUEST")
    if kind == "source_data":
        # Cached write responses can contain erased excerpts and source links. Keep only the
        # idempotency fingerprint, so an old retry cannot reveal a deleted response or repeat a write.
        from sqlalchemy import update

        db.execute(
            update(Operation).where(Operation.user_id == conn.user_id).values(result={"privacyErased": True})
        )
    job = PrivacyJob(
        user_id=conn.user_id,
        connection_id=conn.id,
        kind=kind,
        stage="revoke" if kind == "disconnect" else "tasks",
        data={},
    )
    db.add(job)
    db.flush()
    conn.data = {**conn.data, "privacyJobId": str(job.id)}
    conn.revision += 1
    if kind == "disconnect":
        conn.status, conn.checkpoint, conn.retry_at = "disconnected", {}, None
    return job


def revoke_grant(grant):
    if grant and (grant.refresh_token or grant.access_token):
        token = google.vault().decrypt(grant.refresh_token or grant.access_token, grant.key_version)
        try:
            google.provider.revoke(token)
        except google.SourceError as exc:
            if exc.kind == "retryable":
                return False
        grant.refresh_token = grant.access_token = grant.access_expires_at = None
        grant.status, grant.scopes = "revoked", []
    return True


def advance_source(db, job, conn):
    if job.status == "completed":
        return job_out(job)
    job.error_code = None
    job.data = {k: v for k, v in job.data.items() if k != "nextRetryAt"}
    if job.kind == "disconnect":
        remaining = db.scalar(
            select(Connection.id)
            .where(
                Connection.account_id == conn.account_id,
                Connection.id != conn.id,
                Connection.status != "disconnected",
            )
            .limit(1)
        )
        grant = db.scalar(
            select(OAuthGrant).where(OAuthGrant.account_id == conn.account_id).with_for_update()
        )
        if not remaining and not revoke_grant(grant):
            job.status, job.error_code = "waiting_retry", "GOOGLE_REVOCATION_RETRY"
            job.data = {**job.data, "nextRetryAt": (now() + timedelta(seconds=30)).isoformat()}
            job.revision += 1
            return job_out(job)
        job.data = {"googleAccessRevoked": not bool(remaining)}
        job.stage = "finish"
    elif job.stage == "tasks":
        # One task per request, so a large account can resume without long function invocations.
        stmt = (
            select(Task)
            .join(TaskEvidence, TaskEvidence.task_id == Task.id)
            .join(SourceEvent, SourceEvent.id == TaskEvidence.event_id)
            .join(SourceRecord, SourceRecord.id == SourceEvent.source_record_id)
            .where(SourceRecord.connection_id == conn.id)
            .order_by(Task.id)
            .limit(1)
            .with_for_update(of=Task)
        )
        task = db.scalar(stmt)
        if task:
            events = list(
                db.scalars(
                    select(SourceEvent)
                    .join(TaskEvidence, TaskEvidence.event_id == SourceEvent.id)
                    .join(SourceRecord, SourceRecord.id == SourceEvent.source_record_id)
                    .where(TaskEvidence.task_id == task.id, SourceRecord.connection_id == conn.id)
                    .order_by(SourceEvent.id)
                    .limit(25)
                )
            )
            for event in events:
                record = db.get(SourceRecord, event.source_record_id)
                suppress(db, conn, event.identity_key or record.provider_id)
            event_ids = [e.id for e in events]
            db.execute(
                delete(TaskEvidence).where(
                    TaskEvidence.task_id == task.id, TaskEvidence.event_id.in_(event_ids)
                )
            )
            db.execute(
                delete(History).where(
                    History.task_id == task.id,
                    History.changes["_eventId"].astext.in_([str(e) for e in event_ids]),
                )
            )
            # Merge snapshots may contain removed source content; removing snapshots makes undo unavailable.
            db.execute(
                delete(MergeOperation).where(
                    (MergeOperation.surviving_task_id == task.id)
                    | (MergeOperation.absorbed_task_id == task.id)
                )
            )
            if db.scalar(
                select(TaskEvidence.id)
                .join(SourceEvent, SourceEvent.id == TaskEvidence.event_id)
                .join(SourceRecord, SourceRecord.id == SourceEvent.source_record_id)
                .where(TaskEvidence.task_id == task.id, SourceRecord.connection_id == conn.id)
                .limit(1)
            ):
                job.status, job.revision = "pending", job.revision + 1
                return job_out(job)
            remaining = list(
                db.scalars(
                    select(Connection.service)
                    .join(SourceRecord, SourceRecord.connection_id == Connection.id)
                    .join(SourceEvent, SourceEvent.source_record_id == SourceRecord.id)
                    .join(TaskEvidence, TaskEvidence.event_id == SourceEvent.id)
                    .where(TaskEvidence.task_id == task.id, TaskEvidence.state == "active")
                )
            )
            edited = bool(task.data.get("manualFieldOverrides") or task.data.get("latestManualDecision"))
            manual = "manual" in task.data.get("sources", ["manual"])
            if remaining or edited or manual:
                # Keep accepted fields and student work, remove source attribution and links.
                data = {
                    k: v
                    for k, v in task.data.items()
                    if k not in ("sourceLinks", "timingProvenance", "observedTargeting", "completion")
                }
                data["sources"] = sorted(
                    set(remaining) | ({"manual"} if manual or edited or not remaining else set())
                )
                if task.completed_at:
                    data["completion"] = {
                        "origin": "manual" if not remaining else "retained",
                        "recordedAt": now().isoformat(),
                    }
                task.data, task.revision = data, task.revision + 1
                db.add(
                    History(user_id=task.user_id, task_id=task.id, action="source_data_removed", changes={})
                )
                counter = "preservedTasks"
            else:
                task_suppression(db, task)
                db.delete(task)
                counter = "deletedTasks"
            job.data = {**job.data, counter: job.data.get(counter, 0) + 1}
            db.flush()
        else:
            job.stage = "records"
    elif job.stage == "records":
        rows = list(
            db.scalars(
                select(SourceRecord)
                .where(SourceRecord.connection_id == conn.id)
                .order_by(SourceRecord.id)
                .limit(10)
                .with_for_update()
            )
        )
        if rows:
            ids = [r.id for r in rows]
            # Suppress unresolved activities too. Never suppress an entire multi-item digest with known identities.
            for row in rows:
                keys = list(
                    db.scalars(
                        select(SourceEvent.identity_key).where(
                            SourceEvent.source_record_id == row.id, SourceEvent.identity_key.is_not(None)
                        )
                    )
                )
                for key in keys or [row.provider_id]:
                    suppress(db, conn, key)
            review_ids = select(ReviewItem.id).where(ReviewItem.source_record_id.in_(ids))
            db.execute(
                delete(Activity).where(Activity.target_type == "review", Activity.target_id.in_(review_ids))
            )
            db.execute(delete(SourceRecord).where(SourceRecord.id.in_(ids)))
            job.data = {**job.data, "deletedRecords": job.data.get("deletedRecords", 0) + len(ids)}
        else:
            job.stage = "finish"
    if job.stage == "finish":
        job.status = "completed"
        conn.checkpoint, conn.retry_at = {}, None
        conn.data = {k: v for k, v in conn.data.items() if k not in ("privacyJobId", "lastError")}
    else:
        job.status = "pending"
    job.revision += 1
    return job_out(job)


def deletion_token(id):
    return hmac.new(settings().session_encryption_key.encode(), str(id).encode(), hashlib.sha256).hexdigest()


def account_out(job):
    return {"id": str(job.id), "status": job.status, "stage": job.stage, "errorCode": job.error_code}


def start_account(db, uid):
    from .sync import cancel_jobs

    job = db.scalar(select(AccountDeletion).where(AccountDeletion.user_id == uid).with_for_update())
    if not job:
        job = AccountDeletion(id=uuid.uuid4(), user_id=uuid.UUID(str(uid)))
        job.token_hash = auth.digest(deletion_token(job.id))
        db.add(job)
        db.flush()
        for conn in db.scalars(select(Connection).where(Connection.user_id == uid).with_for_update()):
            cancel_jobs(db, conn.id, "ACCOUNT_DELETION")
            conn.status, conn.retry_at, conn.checkpoint = "disconnected", None, {}
    return {**account_out(job), "resumeToken": deletion_token(job.id)}


def resume_account(token, advance):
    with transaction() as db:
        job = db.scalar(select(AccountDeletion).where(AccountDeletion.token_hash == auth.digest(token)))
        if not job:
            raise ApiError(404, "NOT_FOUND", "Deletion request is unavailable")
        if job.status == "completed" or not advance:
            return account_out(job)
        uid = job.user_id
        owner_lock(db, uid)
        job = db.scalar(
            select(AccountDeletion)
            .where(AccountDeletion.id == job.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if job.status == "completed":
            return account_out(job)
        db.execute(text("select set_config('app.user_id', :id, true)"), {"id": str(uid)})
        job.error_code, job.status = None, "pending"
        job.next_retry_at = None
        if job.stage == "revoke":
            grant = db.scalar(
                select(OAuthGrant)
                .where(OAuthGrant.user_id == uid, OAuthGrant.status != "revoked")
                .order_by(OAuthGrant.id)
                .limit(1)
                .with_for_update()
            )
            if grant:
                if not revoke_grant(grant):
                    job.status, job.error_code = "waiting_retry", "GOOGLE_REVOCATION_RETRY"
                    job.next_retry_at = now() + timedelta(seconds=30)
            else:
                job.stage = "data"
        elif job.stage == "data":
            # Reverse dependency order; each request erases at most 100 rows in one table.
            for table in reversed(Base.metadata.sorted_tables):
                if table.schema != "duecare" or "user_id" not in table.c:
                    continue
                pk = table.c.id if "id" in table.c else table.c.user_id
                ids = list(db.scalars(select(pk).where(table.c.user_id == uid).limit(100)))
                if ids:
                    db.execute(delete(table).where(pk.in_(ids)))
                    break
            else:
                db.execute(delete(OAuthState).where(OAuthState.user_id == uid))
                job.stage = "auth"
        elif job.stage == "auth":
            # Private privileged function checks the durable self-deletion checkpoint and owner context.
            db.execute(text("select duecare_internal.delete_own_auth_account(:id)"), {"id": str(uid)})
            db.execute(delete(WebSession).where(WebSession.user_id == uid))
            job.status, job.stage, job.completed_at, job.user_id = "completed", "complete", now(), None
        result = account_out(job)
        db.commit()
        return result
