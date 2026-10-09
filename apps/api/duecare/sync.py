"""Bounded, resumable, leased source imports advanced by the API worker.

Each advance request holds a lease and performs small units of work until its work budget
ends. Google calls run outside database transactions; each unit then commits its results and
the advanced checkpoint together, only if the lease and saved checkpoint are unchanged. A
checkpoint therefore never moves past unpersisted work, and an interrupted request resumes
from the last committed unit.
"""

import base64
import binascii
import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace

from sqlalchemy import delete, exists, func, select, text, update
from sqlalchemy.exc import IntegrityError

from . import ai, google, interpret, mail, subject_link
from .classroom_time import due_at
from .common import owned, work
from .config import GMAIL_LOOKBACK, settings
from .errors import ApiError
from .models import (
    Connection,
    GoogleAccount,
    OAuthGrant,
    ReviewItem,
    SenderPreference,
    SourceAttachment,
    SourceCourse,
    SourceEvent,
    SourceRecord,
    Subject,
    SubjectMapping,
    SyncJob,
    TaskEvidence,
    now,
)

log = logging.getLogger("duecare.sync")
VERSION = "phase2-import-1"
ACTIVE = ("queued", "running", "waiting_retry")
TERMINAL = ("completed", "failed", "cancelled")
LOOKBACK = timedelta(days=90)
IGNORED_EXPIRY = timedelta(days=30)
FOCUS_INTERVAL = timedelta(minutes=15)
LEASE_GRACE = timedelta(seconds=120)
WATERMARK_OVERLAP = timedelta(hours=1)
OUTSTANDING = ("NEW", "CREATED", "RECLAIMED_BY_STUDENT")


def iso(value):
    return value.isoformat() if value else None


def parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def job_out(job):
    return {
        "id": str(job.id),
        "connectionId": str(job.connection_id),
        "mode": job.mode,
        "phase": job.phase,
        "status": job.status,
        "progress": job.progress,
        "attempts": job.attempts,
        "nextRetryAt": iso(job.next_retry_at),
        "error": job.error,
        "leased": bool(job.lease_owner and job.lease_expires_at and job.lease_expires_at > now()),
        "createdAt": iso(job.created_at),
        "updatedAt": iso(job.updated_at),
        "finishedAt": iso(job.finished_at),
        "revision": job.revision,
    }


def bump(progress, key, n=1):
    return {**progress, key: progress.get(key, 0) + n}


# --- Sender gating -----------------------------------------------------------------------------


def lock_sender(db, uid, email):
    # Serializes block/include edits with record commits for one exact sender mailbox.
    db.execute(text("select pg_advisory_xact_lock(hashtextextended(:k,0))"), {"k": f"{uid}:sender:{email}"})


def academic_domain(email):
    domain = email.rsplit("@", 1)[1]
    domains = [d.strip().lower() for d in settings().academic_sender_domains.split(",") if d.strip()]
    return any(domain == d or domain.endswith("." + d) for d in domains)


def sender_decision(db, uid, email):
    """Complete blocks first, then inclusion, then the academic sender prefilter."""
    if not email:
        return "ignored", "sender_missing"
    action = db.scalar(
        select(SenderPreference.action).where(
            SenderPreference.user_id == uid, SenderPreference.email == email
        )
    )
    if action == "block":
        return "blocked", "sender_blocked"
    from .faculty import approved

    if approved(db, uid, email):
        return "eligible", "faculty_approved"
    if action == "include":
        return "eligible", "sender_included"
    if academic_domain(email):
        return "eligible", "sender_academic_domain"
    return "ignored", "sender_not_academic"


def minimize(db, record, state, reason):
    """Retain only identifiers, sender, and reason; no body, title, excerpt, or attachments."""
    record.processing_state, record.reason = state, reason
    record.title = record.excerpt = record.content_hash = record.message_id = record.thread_id = None
    record.sent_at = record.published_at = None
    record.data = {}
    record.expires_at = now() + IGNORED_EXPIRY
    record.processing_version = VERSION
    db.execute(delete(SourceAttachment).where(SourceAttachment.source_record_id == record.id))


def suppress_sender(db, uid, email):
    lock_sender(db, uid, email)
    rows = db.scalars(
        select(SourceRecord)
        .where(
            SourceRecord.user_id == uid,
            SourceRecord.sender_email == email,
            ~exists(
                select(TaskEvidence.id)
                .join(SourceEvent, SourceEvent.id == TaskEvidence.event_id)
                .where(SourceEvent.source_record_id == SourceRecord.id)
            ),
        )
        .with_for_update()
    ).all()
    for record in rows:
        minimize(db, record, "blocked", "sender_blocked")
        db.execute(update(SourceEvent).where(SourceEvent.source_record_id == record.id).values(data={}))
    interpret.suppress_reviews(db, uid, email)
    return len(rows)


# --- Credentials -------------------------------------------------------------------------------


def access_token(user, connection_id, force=False):
    failure = None
    with work(user) as db:
        conn = owned(db, Connection, connection_id, user["id"])
        if conn.status != "active":
            raise google.SourceError("auth", "This connection needs to be reconnected")
        grant = db.scalar(
            select(OAuthGrant).where(OAuthGrant.account_id == conn.account_id).with_for_update()
        )
        if not grant or grant.status != "active" or not grant.refresh_token:
            raise google.SourceError("auth", "This connection needs to be reconnected")
        vault = google.vault()
        if not force and grant.access_token and grant.access_expires_at and grant.access_expires_at > now():
            return vault.decrypt(grant.access_token, grant.key_version)
        try:
            refresh = vault.decrypt(grant.refresh_token, grant.key_version)
            response = google.provider.refresh(refresh)
        except google.SourceError as exc:
            if exc.kind != "auth":
                raise
            # Revoked or expired grant: every service using this account must be reconnected.
            grant.status, grant.access_token, grant.access_expires_at = "invalid", None, None
            for other in db.scalars(select(Connection).where(Connection.account_id == conn.account_id)):
                if other.status == "active":
                    other.status = "needs_reauth"
            failure = exc
        else:
            # Re-encrypt under the current key version; keep the refresh token if none is returned.
            grant.refresh_token = vault.encrypt(response.get("refresh_token") or refresh)
            grant.access_token = vault.encrypt(response["access_token"])
            grant.access_expires_at = google.expiry(response)
            grant.key_version = vault.current
            return response["access_token"]
    raise failure


# --- Jobs --------------------------------------------------------------------------------------


def ensure_job(db, uid, connection_id, mode="import", trigger="manual"):
    conn = owned(db, Connection, connection_id, uid, lock=True)
    if conn.data.get("privacyJobId"):
        raise ApiError(409, "PRIVACY_IN_PROGRESS", "Finish the source privacy operation before syncing")
    if conn.status != "active":
        raise ApiError(409, "CONNECTION_INACTIVE", "Reconnect this account before syncing")
    active = db.scalar(select(SyncJob).where(SyncJob.connection_id == conn.id, SyncJob.status.in_(ACTIVE)))
    if active:
        if mode == "reprocess" and active.mode != "reprocess":
            conn.data = {**conn.data, "reprocessRequested": True}
            conn.revision += 1
        return {"job": job_out(active), "created": False, "skipped": None}
    if (
        mode == "import"
        and trigger == "focus"
        and conn.last_attempt_at
        and now() - conn.last_attempt_at < FOCUS_INTERVAL
    ):
        return {"job": None, "created": False, "skipped": "recent"}
    job = SyncJob(
        user_id=conn.user_id,
        connection_id=conn.id,
        mode=mode,
        phase="starting",
        status="queued",
        checkpoint={"stage": "start", "trigger": trigger},
        progress={},
    )
    try:
        with db.begin_nested():
            db.add(job)
            db.flush()
    except IntegrityError:
        # Another tab created the connection's single active job first.
        active = db.scalar(
            select(SyncJob).where(SyncJob.connection_id == conn.id, SyncJob.status.in_(ACTIVE))
        )
        return {"job": job_out(active), "created": False, "skipped": None}
    return {"job": job_out(job), "created": True, "skipped": None}


def cancel_jobs(db, connection_id, reason):
    conn = db.get(Connection, connection_id)
    if conn and conn.data.get("reprocessRequested"):
        conn.data = {k: v for k, v in conn.data.items() if k != "reprocessRequested"}
        conn.revision += 1
    count = 0
    for job in db.scalars(
        select(SyncJob)
        .where(SyncJob.connection_id == connection_id, SyncJob.status.in_(ACTIVE))
        .with_for_update()
    ):
        job.status, job.lease_owner, job.lease_expires_at = "cancelled", None, None
        job.checkpoint = {k: v for k, v in job.checkpoint.items() if k != "messageFingerprints"}
        job.finished_at, job.error = now(), {"code": reason, "message": "Sync stopped"}
        job.revision += 1
        count += 1
    return count


def advance(user, job_id, stop=None):
    lease = secrets.token_hex(16)
    budget = settings().sync_work_budget_seconds
    with work(user) as db:
        job = owned(db, SyncJob, job_id, user["id"], lock=True)
        if job.status in TERMINAL:
            return job_out(job)
        if job.lease_owner and job.lease_expires_at and job.lease_expires_at > now():
            raise ApiError(409, "SYNC_IN_PROGRESS", "This connection is already syncing")
        if job.status == "waiting_retry" and job.next_retry_at and job.next_retry_at > now():
            return job_out(job)
        conn = db.scalar(select(Connection).where(Connection.id == job.connection_id).with_for_update())
        if conn.status != "active":
            job.status, job.finished_at = "cancelled", now()
            job.checkpoint = {k: v for k, v in job.checkpoint.items() if k != "messageFingerprints"}
            job.error = {"code": "CONNECTION_INACTIVE", "message": "Reconnect this account before syncing"}
            return job_out(job)
        job.lease_owner, job.lease_expires_at = lease, now() + timedelta(seconds=budget) + LEASE_GRACE
        job.status = "running"
        job.revision += 1
        conn.last_attempt_at = now()
    deadline = time.monotonic() + budget
    try:
        # Each lane owns its network calls and DB sessions. Only the importer moves the
        # checkpoint; the interpreter merges progress under the same job/owner locks.
        imported = Event()
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="duecare-interpret") as pool:
            worker = pool.submit(interpret_stream, user, job_id, lease, deadline, imported, stop)
            try:
                with ai.request_budget(deadline):
                    while (
                        time.monotonic() < deadline
                        and not (stop and stop.is_set())
                        and step(user, job_id, lease, import_only=True)
                    ):
                        pass
            finally:
                imported.set()
            worker.result()
        finish_pipeline(user, job_id, lease)
    except Exception as exc:
        log.error("sync step failed type=%s job=%s", type(exc).__name__, str(job_id))
        record_failure(
            user, job_id, lease, google.SourceError("fatal", "Sync stopped unexpectedly. Try again")
        )
    with work(user) as db:
        job = owned(db, SyncJob, job_id, user["id"], lock=True)
        if job.lease_owner == lease:
            job.lease_owner = job.lease_expires_at = None
            if job.status == "running":
                job.status = "queued"
        return job_out(job)


def record_failure(user, job_id, lease, exc):
    with work(user) as db:
        job = owned(db, SyncJob, job_id, user["id"], lock=True)
        if job.lease_owner != lease:
            return False
        conn = db.scalar(select(Connection).where(Connection.id == job.connection_id).with_for_update())
        if exc.kind == "retryable":
            job.attempts += 1
            delay = timedelta(seconds=min(15 * 2 ** (job.attempts - 1), 1800))
            job.status, job.next_retry_at = "waiting_retry", now() + delay
            conn.retry_at = job.next_retry_at
            error = {"code": "PROVIDER_TEMPORARY", "message": exc.message}
        else:
            code = {"auth": "RECONNECT_REQUIRED", "permission": "PERMISSION_REQUIRED"}.get(
                exc.kind, "SYNC_FAILED"
            )
            job.status, job.finished_at = "failed", now()
            job.checkpoint = {k: v for k, v in job.checkpoint.items() if k != "messageFingerprints"}
            if exc.kind in ("auth", "permission") and conn.status == "active":
                conn.status = "needs_reauth"
            error = {"code": code, "message": exc.message}
        error["at"] = now().isoformat()
        job.error = error
        job.lease_owner = job.lease_expires_at = None
        job.revision += 1
        conn.data = {**conn.data, "lastError": error}
        from .activity import notify

        notify(
            db,
            conn.user_id,
            "sync_issue",
            "connection",
            conn.id,
            "A source could not sync. Open Sources to retry or reconnect.",
            f"sync:{job.id}:{error['code']}",
        )
    return False


def step(user, job_id, lease, import_only=False):
    """Run one unit. Returns True while more work remains and the lease is still held."""
    with work(user) as db:
        job = owned(db, SyncJob, job_id, user["id"])
        if job.lease_owner != lease or job.status != "running":
            return False
        if import_only and job.checkpoint.get("stage") == "interpret":
            return False
        conn = db.get(Connection, job.connection_id)
        account = db.get(GoogleAccount, conn.account_id)
        snap = SimpleNamespace(
            uid=user["id"],
            job_id=job.id,
            mode=job.mode,
            checkpoint=json.loads(json.dumps(job.checkpoint)),
            connection_id=conn.id,
            service=conn.service,
            sub=account.google_sub,
            account_email=account.email.lower(),
            conn_checkpoint=json.loads(json.dumps(conn.checkpoint)),
            last_success_at=conn.last_success_at,
        )
    unit = (
        interpretation_unit
        if snap.checkpoint.get("stage") in ("interpret", "reinterpret")
        else (gmail_unit if snap.service == "gmail" else classroom_unit)
    )
    try:
        try:
            apply = unit(snap, access_token(user, snap.connection_id))
        except google.SourceError as exc:
            if exc.kind != "auth":
                raise
            apply = unit(snap, access_token(user, snap.connection_id, force=True))
    except google.SourceError as exc:
        return record_failure(user, job_id, lease, exc)
    with work(user) as db:
        job = owned(db, SyncJob, job_id, user["id"], lock=True)
        if job.lease_owner != lease or job.checkpoint != snap.checkpoint or job.status != "running":
            return False  # Lost lease or cancelled: discard this unit; nothing is persisted.
        conn = db.scalar(select(Connection).where(Connection.id == job.connection_id).with_for_update())
        if conn.status != "active":
            return False
        done = apply(db, job, conn)
        job.revision += 1
        if job.status == "running":
            job.attempts, job.next_retry_at, job.error = 0, None, None
            conn.retry_at = None
        if done:
            job.status, job.phase, job.finished_at = "completed", "done", now()
            job.lease_owner = job.lease_expires_at = None
            if job.mode == "import":
                conn.last_success_at = now()
            conn.data = {**conn.data, "lastError": None}
        return not done


def interpret_stream(user, job_id, lease, deadline, imported, stop=None):
    """Prepare distinct saved records concurrently; apply results in short, serialized transactions."""
    configured = settings()
    workers = (
        configured.openrouter_concurrency
        if configured.openrouter_api_key and configured.openrouter_model
        else 1
    )
    token = None
    inflight = {}

    def prepare_one(snap, access, record_id):
        # ContextVars are not inherited by executor threads.
        with ai.request_budget(deadline):
            try:
                return interpret.unit(snap, access, record_id=record_id)
            except google.SourceError as exc:
                if exc.kind != "auth":
                    raise
                refreshed = access_token(user, snap.connection_id, force=True)
                return interpret.unit(snap, refreshed, record_id=record_id)

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="duecare-extract") as pool:
        try:
            while (time.monotonic() < deadline and not (stop and stop.is_set())) or inflight:
                with work(user) as db:
                    job = owned(db, SyncJob, job_id, user["id"])
                    if job.lease_owner != lease or job.status != "running":
                        return
                    conn = db.get(Connection, job.connection_id)
                    if conn.status != "active":
                        return
                    account = db.get(GoogleAccount, conn.account_id)
                    stage = job.checkpoint.get("stage")
                    snap = SimpleNamespace(
                        uid=user["id"],
                        connection_id=conn.id,
                        account_email=account.email.lower(),
                        checkpoint=dict(job.checkpoint),
                    )
                    ready = job.mode != "reprocess" or stage == "interpret"
                    capacity = workers - len(inflight)
                    ids = (
                        interpret.pending_records(
                            db, conn.id, capacity, tuple(v[0] for v in inflight.values())
                        )
                        if ready and capacity and time.monotonic() < deadline and not (stop and stop.is_set())
                        else []
                    )
                if ids:
                    try:
                        if token is None:
                            token = access_token(user, snap.connection_id)
                    except google.SourceError as exc:
                        record_failure(user, job_id, lease, exc)
                        return
                    for record_id in ids:
                        future = pool.submit(prepare_one, snap, token, record_id)
                        inflight[future] = (record_id, snap)
                if not inflight:
                    if imported.is_set():
                        return
                    imported.wait(0.2)
                    continue
                finished, _ = wait(inflight, timeout=1, return_when=FIRST_COMPLETED)
                for future in finished:
                    _, prepared_snap = inflight.pop(future)
                    try:
                        apply = future.result()
                    except ai.BudgetExpired:
                        continue
                    except google.SourceError as exc:
                        record_failure(user, job_id, lease, exc)
                        return
                    if apply is None:
                        continue
                    # Already-finished results remain safe to commit under this lease even when
                    # the request budget has just ended. New work stops at the deadline above.
                    with work(user) as db:
                        job = owned(db, SyncJob, job_id, user["id"], lock=True)
                        if job.lease_owner != lease or job.status != "running":
                            return
                        if job.checkpoint.get("run", 0) != prepared_snap.checkpoint.get("run", 0):
                            continue
                        conn = db.scalar(
                            select(Connection)
                            .where(Connection.id == prepared_snap.connection_id)
                            .with_for_update()
                        )
                        if conn.status != "active":
                            return
                        phase = job.phase
                        apply(db, job, conn)
                        if job.checkpoint.get("stage") != "interpret":
                            job.phase = phase
                        job.revision += 1
        finally:
            for future in inflight:
                future.cancel()


def finish_pipeline(user, job_id, lease):
    """Complete only after importing and all currently eligible interpretations are drained."""
    with work(user) as db:
        job = owned(db, SyncJob, job_id, user["id"], lock=True)
        if job.lease_owner != lease or job.status != "running" or job.checkpoint.get("stage") != "interpret":
            return
        if interpret.pending_record(db, job.connection_id) is not None:
            return
        conn = db.scalar(select(Connection).where(Connection.id == job.connection_id).with_for_update())
        if conn.status != "active":
            return
        if wait_for_interpretation(db, job, conn):
            return
        job.status, job.phase, job.finished_at = "completed", "done", now()
        job.lease_owner = job.lease_expires_at = None
        job.attempts, job.next_retry_at, job.error = 0, None, None
        conn.retry_at = None
        job.revision += 1
        if job.mode == "import":
            conn.last_success_at = now()
        conn.data = {**conn.data, "lastError": None}


def wait_for_interpretation(db, job, conn):
    """A successful download is not a finished sync while saved records still need AI."""
    pending = db.scalars(
        select(SourceRecord).where(
            SourceRecord.connection_id == conn.id,
            SourceRecord.processing_state == "awaiting_interpretation",
            interpret.in_gmail_window(),
        )
    ).all()
    if not pending:
        return False
    stamp = now()
    retry_record = min(
        pending,
        key=lambda r: parse_time(r.data.get("aiPausedUntil")) or stamp + timedelta(seconds=60),
    )
    retry_at = parse_time(retry_record.data.get("aiPausedUntil")) or stamp + timedelta(seconds=60)
    job.status, job.phase = "waiting_retry", "interpreting"
    job.next_retry_at = max(stamp + timedelta(seconds=1), retry_at)
    job.finished_at = None
    job.lease_owner = job.lease_expires_at = None
    job.revision += 1
    code = retry_record.data.get("aiPausedCode") or "AI_UNAVAILABLE"
    job.error = {
        "code": code,
        "message": "Messages downloaded. AI is rate limited; interpretation will retry automatically."
        if code == "AI_RATE_LIMIT"
        else "Messages downloaded. AI interpretation is pending and will retry automatically.",
        "at": stamp.isoformat(),
    }
    conn.retry_at = job.next_retry_at
    conn.data = {**conn.data, "lastError": job.error}
    return True


def requeue_subject_questions(db, conn, job):
    """Items still waiting on "Which of your subjects is this for?" (asked before subjects were linked
    automatically) are interpreted again; the task they create settles the question."""
    records = db.scalars(
        select(SourceRecord).where(
            SourceRecord.connection_id == conn.id,
            SourceRecord.id.in_(
                select(ReviewItem.source_record_id).where(
                    ReviewItem.user_id == conn.user_id,
                    ReviewItem.status == "open",
                    ReviewItem.issue_type == "choose_subject",
                )
            ),
        )
    ).all()
    for record in records:
        record.processing_state, record.expires_at = "awaiting_interpretation", None
    if records:
        # A new run lets the same source revision be applied again.
        job.checkpoint = {**job.checkpoint, "run": job.checkpoint.get("run", 0) + 1}


def to_interpretation(job):
    """Finish importing and drain remaining interpretation; reprocessing first re-queues records."""
    stage = "reinterpret" if job.mode == "reprocess" else "interpret"
    checkpoint = {k: v for k, v in job.checkpoint.items() if k != "messageFingerprints"}
    set_checkpoint(job, {**checkpoint, "stage": stage}, "interpreting")
    return False


REQUEUE = ("ignored", "interpreted", "needs_review", "awaiting_interpretation")


def interpretation_unit(snap, token):
    if snap.checkpoint.get("stage") == "reinterpret":

        def requeue(db, job, conn):
            # Explicit reprocessing reconsiders ignored, unmatched, and earlier interpretations under the
            # current profile, subjects, timetable, and rules. Blocked mail stays blocked.
            run = job.checkpoint.get("run", 0) + 1
            count = 0
            for record in db.scalars(
                select(SourceRecord).where(
                    SourceRecord.connection_id == conn.id,
                    SourceRecord.processing_state.in_(REQUEUE),
                    interpret.in_gmail_window(),
                    SourceRecord.reason.is_distinct_from("sender_not_academic"),
                    SourceRecord.reason.is_distinct_from("sender_missing"),
                )
            ):
                record.processing_state, record.expires_at = "awaiting_interpretation", None
                record.data = {
                    k: v
                    for k, v in record.data.items()
                    if k not in ("aiPausedUntil", "aiPausedReason", "aiPausedCode")
                }
                count += 1
            set_checkpoint(
                job,
                {**job.checkpoint, "stage": "interpret", "run": run},
                "interpreting",
                bump(job.progress, "requeued", count),
            )
            return False

        return requeue
    apply = interpret.unit(snap, token)
    if apply:
        return apply

    def finished(db, job, conn):
        return not wait_for_interpretation(db, job, conn)

    return finished


def set_checkpoint(job, checkpoint, phase=None, progress=None):
    job.checkpoint = checkpoint
    if phase:
        job.phase = phase
    if progress is not None:
        job.progress = progress


# --- Gmail -------------------------------------------------------------------------------------


def gmail_unit(snap, token):
    cp, provider = snap.checkpoint, google.provider
    stage = cp.get("stage", "start")
    if snap.mode == "reprocess" and stage in ("start", "reconsider"):
        return gmail_reconsider(snap, token)
    if stage == "start":
        start = snap.conn_checkpoint.get("historyId")
        if start and snap.last_success_at:
            # Read the newest mail first, then drain history to retain a gap-free cursor.
            new = gmail_list_start(
                provider.gmail_profile(token),
                max(
                    snap.last_success_at - WATERMARK_OVERLAP,
                    now() - GMAIL_LOOKBACK,
                ),
            )
            new["resumeHistory"] = start
        elif start:
            new = {"stage": "listing", "source": "history", "start": start, "pending": [], "more": True}
        else:
            new = gmail_list_start(provider.gmail_profile(token), now() - GMAIL_LOOKBACK)
        return lambda db, job, conn: set_checkpoint(job, new, "listing") or False
    if (
        cp.get("source") == "list"
        and cp.get("lookbackDays") != 30
        and (int(cp["query"].split("after:", 1)[1]) < int((now() - GMAIL_LOOKBACK).timestamp()) - 60)
    ):
        # Resume an older 90-day job inside the new window, newest page first.
        new = gmail_list_start(provider.gmail_profile(token), now() - GMAIL_LOOKBACK)
        return lambda db, job, conn: set_checkpoint(job, new, "listing") or False
    if cp.get("pending"):
        gid = cp["pending"][0]

        def popped(c):
            return {**c, "pending": c["pending"][1:]}

        return gmail_message_unit(snap, token, gid, popped, reconsider=False)
    if cp.get("more"):
        if cp["source"] == "list":
            query = cp["query"]
            page = provider.gmail_list(token, query, cp.get("pageToken"))
            ids = [m["id"] for m in page.get("messages", [])]
            latest = cp.get("latestHistoryId")
        else:
            try:
                page = provider.gmail_history(token, cp["start"], cp.get("pageToken"))
            except google.SourceError as exc:
                if exc.kind != "not_found":
                    raise
                # History expired: list the gap again; account-scoped identifiers prevent duplicates.
                since = max((snap.last_success_at or now()) - timedelta(days=1), now() - GMAIL_LOOKBACK)
                new = gmail_list_start(provider.gmail_profile(token), since)
                return lambda db, job, conn: set_checkpoint(
                    job, new, "listing", bump(job.progress, "historyResets")
                )
            ids = []
            for entry in page.get("history", []):
                for added in entry.get("messagesAdded", []):
                    message = added.get("message", {})
                    if "DRAFT" not in message.get("labelIds", []) and message.get("id") not in ids:
                        ids.append(message["id"])
            latest = page.get("historyId") or cp.get("latestHistoryId")
        new = {
            **cp,
            "pending": ids,
            "pageToken": page.get("nextPageToken"),
            "more": bool(page.get("nextPageToken")),
        }
        new["latestHistoryId"] = latest

        def listed(db, job, conn):
            set_checkpoint(job, new, "messages", bump(bump(job.progress, "pages"), "listed", len(ids)))
            return False

        return listed
    if cp.get("resumeHistory"):
        new = {
            **cp,
            "stage": "listing",
            "source": "history",
            "start": cp["resumeHistory"],
            "pending": [],
            "pageToken": None,
            "more": True,
        }
        new.pop("resumeHistory")
        return lambda db, job, conn: set_checkpoint(job, new, "listing") or False
    final = cp.get("latestHistoryId") or cp.get("baselineHistoryId") or cp.get("start")

    def finished(db, job, conn):
        conn.checkpoint = {**conn.checkpoint, "historyId": final}
        requeue_subject_questions(db, conn, job)
        return to_interpretation(job)

    return finished


def gmail_list_start(profile, since):
    return {
        "stage": "listing",
        "source": "list",
        "query": f"after:{int(since.timestamp())}",
        "lookbackDays": 30,
        "baselineHistoryId": profile.get("historyId"),
        "pending": [],
        "more": True,
    }


def gmail_reconsider(snap, token):
    """Explicit reprocessing: reconsider previously blocked or ignored mail under current preferences."""
    cp = snap.checkpoint
    with work({"id": snap.uid}) as db:
        stmt = select(SourceRecord.id, SourceRecord.provider_id).where(
            SourceRecord.connection_id == snap.connection_id,
            SourceRecord.kind == "gmail_message",
            SourceRecord.processing_state.in_(("blocked", "ignored")),
            interpret.in_gmail_window(),
        )
        if cp.get("after"):
            stmt = stmt.where(SourceRecord.id > uuid.UUID(cp["after"]))
        row = db.execute(stmt.order_by(SourceRecord.id).limit(1)).first()
    if not row:
        return lambda db, job, conn: to_interpretation(job)
    gid = row.provider_id.split(":", 2)[2]

    def moved(c):
        return {**c, "stage": "reconsider", "after": str(row.id)}

    return gmail_message_unit(snap, token, gid, moved, reconsider=True)


def gmail_message_unit(snap, token, gid, next_checkpoint, reconsider):
    pid = f"gmail:{snap.sub}:{gid}"
    with work({"id": snap.uid}) as db:
        existing = db.scalar(
            select(SourceRecord.id).where(
                SourceRecord.connection_id == snap.connection_id, SourceRecord.provider_id == pid
            )
        )
    if existing and not reconsider:
        # Gmail messages are immutable; an earlier decision stands until explicit reprocessing.
        return counted(next_checkpoint, "unchanged")
    try:
        meta = google.provider.gmail_metadata(token, gid)
    except google.SourceError as exc:
        if exc.kind != "not_found":
            raise
        return counted(next_checkpoint, "unavailable")
    labels = meta.get("labelIds", [])
    if "DRAFT" in labels or ("SENT" in labels and "INBOX" not in labels):
        return counted(next_checkpoint, "skipped")
    sender = mail.header_sender(meta.get("payload", {}).get("headers"))
    received = (
        datetime.fromtimestamp(int(meta.get("internalDate", 0)) / 1000, UTC)
        if meta.get("internalDate")
        else None
    )
    if received is None or received < now() - GMAIL_LOOKBACK:
        # Metadata is sufficient to reject old history entries; never fetch their body.
        return counted(next_checkpoint, "outsideWindow")
    with work({"id": snap.uid}) as db:
        decision, reason = sender_decision(db, snap.uid, sender)
    headers = meta.get("payload", {}).get("headers", [])
    heading = next((h["value"] for h in headers if h.get("name", "").lower() == "subject"), "")
    sender_name = next((h["value"] for h in headers if h.get("name", "").lower() == "from"), "")
    exclusion = mail.academic_exclusion(heading, sender, sender_name)
    if decision == "eligible" and exclusion:
        decision, reason = "ignored", exclusion
    decoded = None
    if decision == "eligible":
        # Only eligible, unblocked mail has its body fetched.
        try:
            raw = google.provider.gmail_raw(token, gid)["raw"]
            decoded = mail.decode(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
            exclusion = mail.academic_exclusion(
                decoded.subject, decoded.sender_email, decoded.sender_name, decoded.authored_text
            )
            if exclusion:
                decision, reason = "ignored", exclusion
        except google.SourceError as exc:
            if exc.kind != "not_found":
                raise
            return counted(next_checkpoint, "unavailable")
        except (KeyError, ValueError, binascii.Error, UnicodeError, IndexError, LookupError):
            decision, reason = "ignored", "undecodable"

    def apply(db, job, conn):
        record = db.scalar(
            select(SourceRecord)
            .where(SourceRecord.connection_id == conn.id, SourceRecord.provider_id == pid)
            .with_for_update()
        )
        if sender:
            lock_sender(db, conn.user_id, sender)
            # Recheck in the applying transaction: a newly blocked sender cannot be committed.
            current, current_reason = sender_decision(db, conn.user_id, sender)
        else:
            current, current_reason = decision, reason
        state, why = (current, current_reason) if current != "eligible" else (decision, reason)
        if state != "eligible" or decoded is None:
            final = "blocked" if state == "blocked" else "ignored"
            if record is None:
                record = SourceRecord(
                    user_id=conn.user_id,
                    connection_id=conn.id,
                    provider_id=pid,
                    kind="gmail_message",
                    processing_state=final,
                    processing_version=VERSION,
                )
                db.add(record)
            record.sender_email, record.received_at = sender, received
            db.flush()
            minimize(db, record, final, why)
            set_checkpoint(job, next_checkpoint(job.checkpoint), progress=bump(job.progress, final))
            return False
        record = store_message(
            db, conn, job, record, pid, gid, meta, received, decoded, current_reason, snap.account_email
        )
        key = "duplicates" if record.processing_state == "duplicate" else "stored"
        set_checkpoint(job, next_checkpoint(job.checkpoint), progress=bump(job.progress, key))
        return False

    return apply


def counted(next_checkpoint, key):
    def apply(db, job, conn):
        set_checkpoint(job, next_checkpoint(job.checkpoint), progress=bump(job.progress, key))
        return False

    return apply


def store_message(db, conn, job, record, pid, gid, meta, received, decoded, reason, account_email):
    digest = decoded.content_hash()
    duplicate = None
    fingerprint = None
    if decoded.message_id:
        # Streaming can minimize an ignored original before its copy is downloaded.
        # Keep only a keyed, opaque identity in the resumable import checkpoint, then
        # erase the index when import ends/cancels/fails. No ignored source content is retained.
        fingerprint = hmac.new(
            settings().session_encryption_key.encode(),
            json.dumps([decoded.message_id, digest]).encode(),
            hashlib.sha256,
        ).hexdigest()
        previous = job.checkpoint.get("messageFingerprints", {}).get(fingerprint)
        if previous:
            duplicate = db.scalar(
                select(SourceRecord.id).where(
                    SourceRecord.id == uuid.UUID(previous),
                    SourceRecord.connection_id == conn.id,
                    SourceRecord.provider_id != pid,
                    SourceRecord.processing_state != "blocked",
                )
            )
    if decoded.message_id and duplicate is None:
        duplicate = db.scalar(
            select(SourceRecord.id).where(
                SourceRecord.connection_id == conn.id,
                SourceRecord.message_id == decoded.message_id,
                SourceRecord.content_hash == digest,
                SourceRecord.provider_id != pid,
                SourceRecord.processing_state.in_(("awaiting_interpretation", "interpreted", "needs_review")),
            )
        )
    if record is None:
        record = SourceRecord(
            user_id=conn.user_id, connection_id=conn.id, provider_id=pid, kind="gmail_message"
        )
        db.add(record)
    elif record.content_hash != digest:
        record.revision += 1
    record.sender_email = decoded.sender_email
    record.title = decoded.subject
    record.message_id = decoded.message_id
    record.thread_id = meta.get("threadId")
    record.sent_at = decoded.sent_at
    record.received_at = received
    record.content_hash = digest
    record.processing_state = "duplicate" if duplicate else "awaiting_interpretation"
    record.processing_version = VERSION
    record.reason = "duplicate_message" if duplicate else reason
    record.expires_at = None
    record.data = {
        **decoded.summary(),
        "senderName": decoded.sender_name,
        "gmailMessageId": gid,
        "addressedToAccount": account_email in decoded.recipients_include,
        "duplicateOf": str(duplicate) if duplicate else None,
    }
    db.flush()
    if fingerprint:
        job.checkpoint = {
            **job.checkpoint,
            "messageFingerprints": {
                **job.checkpoint.get("messageFingerprints", {}),
                fingerprint: str(duplicate or record.id),
            },
        }
    replace_attachments(db, record, decoded.attachments + decoded.links)
    return record


def replace_attachments(db, record, items):
    db.execute(delete(SourceAttachment).where(SourceAttachment.source_record_id == record.id))
    for item in items:
        db.add(
            SourceAttachment(
                user_id=record.user_id,
                source_record_id=record.id,
                kind=item["kind"],
                title=item.get("title"),
                reference=item.get("reference"),
                media_type=item.get("mediaType"),
                size_bytes=item.get("sizeBytes"),
            )
        )


# --- Classroom ---------------------------------------------------------------------------------


def classroom_unit(snap, token):
    cp, provider = snap.checkpoint, google.provider
    stage = cp.get("stage", "start")
    if stage == "start":
        new = {"stage": "courses", "pageToken": None, "marks": {}}
        return lambda db, job, conn: set_checkpoint(job, new, "courses") or False
    if stage == "courses":
        page = provider.classroom_courses(token, cp.get("pageToken"))
        courses, next_token = page.get("courses", []), page.get("nextPageToken")

        def discovered(db, job, conn):
            for course in courses:
                upsert_course(db, conn, course, job.id)
            progress = bump(bump(job.progress, "pages"), "courses", len(courses))
            if next_token:
                set_checkpoint(job, {**job.checkpoint, "pageToken": next_token}, progress=progress)
                return False
            set_checkpoint(job, {**job.checkpoint, "stage": "automap"}, progress=progress)
            return False

        return discovered
    if stage == "automap":
        return automap_unit(snap)
    if stage == "course":
        return course_unit(snap, token)
    marks = cp.get("marks", {})

    def finished(db, job, conn):
        known = conn.checkpoint.get("courses", {})
        conn.checkpoint = {
            **conn.checkpoint,
            "courses": {k: {**known.get(k, {}), **v} for k, v in {**known, **marks}.items()},
        }
        requeue_subject_questions(db, conn, job)
        return to_interpretation(job)

    return finished


def automap_unit(snap):
    """Link newly discovered Classroom courses to the student's subjects by name or short form (AI
    for the rest), so their work imports without manual linking. A course the student unlinked is
    never linked again automatically; each course is reconsidered when the subject list changes."""
    with work({"id": snap.uid}) as db:
        subjects = [
            {
                "id": str(s.id),
                "name": s.name,
                "kind": s.kind,
                "code": s.data.get("code"),
                "aliases": s.data.get("aliases") or [],
            }  # fmt: skip
            for s in db.scalars(select(Subject).where(Subject.user_id == snap.uid).order_by(Subject.name))
        ]
        linked = {
            m.external_course_id
            for m in db.scalars(
                select(SubjectMapping).where(SubjectMapping.connection_id == snap.connection_id)
            )
        }
        signature = hashlib.sha256(
            json.dumps([[s["id"], s["name"], s["kind"]] for s in subjects]).encode()
        ).hexdigest()[:16]
        todo = [
            (c.external_course_id, c.name)
            for c in db.scalars(
                select(SourceCourse).where(
                    SourceCourse.connection_id == snap.connection_id, SourceCourse.available.is_(True)
                )
            )
            if c.external_course_id not in linked
            and not c.data.get("autoLinkDeclined")
            and c.data.get("autoLinkChecked") != signature
        ]
    checked = {cid for cid, _ in todo}
    try:
        links, _ = subject_link.link_courses(todo, subjects)
    except ai.AIUnavailable:
        # Name matches still apply; the rest are reconsidered on a later sync.
        links = {cid: ids for cid, name in todo if (ids := subject_link.course_subjects(name, subjects))}
        checked = set(links)

    def apply(db, job, conn):
        kinds = {s.id: s.kind for s in db.scalars(select(Subject).where(Subject.user_id == conn.user_id))}
        for course in db.scalars(
            select(SourceCourse).where(
                SourceCourse.connection_id == conn.id, SourceCourse.external_course_id.in_(checked or {""})
            )
        ):
            course.data = {**course.data, "autoLinkChecked": signature}
            if course.data.get("autoLinkDeclined"):
                continue
            for sid in links.get(course.external_course_id, []):
                sid = uuid.UUID(sid)
                if sid not in kinds or db.scalar(
                    select(SubjectMapping.id).where(
                        SubjectMapping.subject_id == sid,
                        SubjectMapping.connection_id == conn.id,
                        SubjectMapping.external_course_id == course.external_course_id,
                    )
                ):
                    continue
                db.add(
                    SubjectMapping(
                        user_id=conn.user_id,
                        subject_id=sid,
                        connection_id=conn.id,
                        external_course_id=course.external_course_id,
                        source_available=True,
                        data={
                            "courseName": course.name,
                            "section": course.data.get("section"),
                            "subjectKind": kinds[sid],
                            "automatic": True,
                        },  # fmt: skip
                    )
                )
        db.flush()
        queue = finish_discovery(db, conn, job.id)
        set_checkpoint(job, next_course({**job.checkpoint, "queue": queue}), "coursework")
        return False

    return apply


def next_course(cp):
    queue = list(cp.get("queue", []))
    if not queue:
        return {**cp, "stage": "finish", "course": None, "queue": []}
    return {
        **cp,
        "stage": "course",
        "queue": queue[1:],
        "course": {"id": queue[0], "resource": "submissions"},
    }


def upsert_course(db, conn, course, job_id):
    row = db.scalar(
        select(SourceCourse).where(
            SourceCourse.connection_id == conn.id, SourceCourse.external_course_id == str(course["id"])
        )
    )
    if row is None:
        row = SourceCourse(user_id=conn.user_id, connection_id=conn.id, external_course_id=str(course["id"]))
        db.add(row)
    row.name = (course.get("name") or "Untitled course")[:500]
    row.available = True
    # Source metadata only. Discovering a course never creates or changes a subject.
    row.data = {
        # The student's unlinking and the last automatic-linking check survive rediscovery.
        **{k: v for k, v in (row.data or {}).items() if k in ("autoLinkDeclined", "autoLinkChecked")},
        "section": course.get("section"),
        "room": course.get("room"),
        "courseState": course.get("courseState"),
        "alternateLink": course.get("alternateLink"),
        "updateTime": course.get("updateTime"),
        "lastSeenJob": str(job_id),
    }


def finish_discovery(db, conn, job_id):
    for row in db.scalars(select(SourceCourse).where(SourceCourse.connection_id == conn.id)):
        row.available = row.data.get("lastSeenJob") == str(job_id)
    db.flush()
    available = {
        r.external_course_id
        for r in db.scalars(
            select(SourceCourse).where(
                SourceCourse.connection_id == conn.id, SourceCourse.available.is_(True)
            )
        )
    }
    queue = set()
    for mapping in db.scalars(select(SubjectMapping).where(SubjectMapping.connection_id == conn.id)):
        mapping.source_available = mapping.external_course_id in available
        if mapping.source_available:
            queue.add(mapping.external_course_id)
    return sorted(queue)


def course_unit(snap, token):
    cp, provider = snap.checkpoint, google.provider
    course, cid = cp["course"], cp["course"]["id"]
    resource = course["resource"]
    with work({"id": snap.uid}) as db:
        mapped = db.scalar(
            select(func.count())
            .select_from(SubjectMapping)
            .where(
                SubjectMapping.connection_id == snap.connection_id, SubjectMapping.external_course_id == cid
            )
        )
        outstanding = {}
        if resource == "coursework" and not snap.conn_checkpoint.get("courses", {}).get(cid, {}).get(
            "coursework"
        ):
            for data in db.scalars(
                select(SourceRecord.data).where(
                    SourceRecord.connection_id == snap.connection_id,
                    SourceRecord.kind == "classroom_submission",
                    SourceRecord.external_course_id == cid,
                )
            ):
                outstanding[data.get("courseWorkId")] = data.get("state") in OUTSTANDING
    if not mapped:
        # Mapping removed: stop syncing through it; existing records and tasks remain.
        return lambda db, job, conn: set_checkpoint(job, next_course(job.checkpoint)) or False
    fetch = {
        "submissions": provider.classroom_submissions,
        "coursework": provider.classroom_coursework,
        "announcements": provider.classroom_announcements,
    }[resource]
    try:
        page = fetch(token, cid, course.get("pageToken"))
    except google.SourceError as exc:
        if exc.kind not in ("not_found", "permission"):
            raise

        def unavailable(db, job, conn):
            for mapping in db.scalars(
                select(SubjectMapping).where(
                    SubjectMapping.connection_id == conn.id, SubjectMapping.external_course_id == cid
                )
            ):
                mapping.source_available = False
            for row in db.scalars(
                select(SourceCourse).where(
                    SourceCourse.connection_id == conn.id, SourceCourse.external_course_id == cid
                )
            ):
                row.available = False
            set_checkpoint(
                job, next_course(job.checkpoint), progress=bump(job.progress, "unavailableCourses")
            )
            return False

        return unavailable
    key = {"submissions": "studentSubmissions", "coursework": "courseWork", "announcements": "announcements"}
    items = page.get(key[resource], [])
    watermark = (
        None
        if snap.mode == "reprocess"
        else snap.conn_checkpoint.get("courses", {}).get(cid, {}).get(resource)
    )
    cutoff = parse_time(watermark) - WATERMARK_OVERLAP if watermark else None
    lookback = now() - LOOKBACK
    keep, stop, newest = [], False, cp.get("marks", {}).get(cid, {}).get(resource)
    for item in items:
        updated = parse_time(item.get("updateTime"))
        if updated and (newest is None or updated > parse_time(newest)):
            newest = item["updateTime"]
        if resource == "submissions":
            keep.append(item)
            continue
        if cutoff and updated and updated < cutoff:
            stop = True  # Ordered by update time: everything after this is already imported.
            break
        if resource == "announcements":
            if not cutoff and updated and updated < lookback:
                stop = True
                break
            keep.append(item)
        elif (
            cutoff
            or (updated and updated >= lookback)
            or future_due(item)
            or outstanding.get(item["id"], True)
        ):
            # Initial import: last 90 days, older work with future deadlines, and older outstanding work.
            keep.append(item)
    next_token = None if stop else page.get("nextPageToken")

    def stored(db, job, conn):
        if not db.scalar(
            select(func.count())
            .select_from(SubjectMapping)
            .where(SubjectMapping.connection_id == conn.id, SubjectMapping.external_course_id == cid)
        ):
            set_checkpoint(job, next_course(job.checkpoint))
            return False
        progress = bump(job.progress, "pages")
        for item in keep:
            progress = bump(progress, store_classroom(db, conn, snap.sub, cid, resource, item))
        progress = bump(progress, "examined", len(items))
        marks = {**job.checkpoint.get("marks", {})}
        if newest:
            marks[cid] = {**marks.get(cid, {}), resource: newest}
        checkpoint = {**job.checkpoint, "marks": marks}
        if next_token:
            checkpoint["course"] = {**course, "pageToken": next_token}
        else:
            following = {"submissions": "coursework", "coursework": "announcements"}.get(resource)
            checkpoint = (
                {**checkpoint, "course": {"id": cid, "resource": following}}
                if following
                else next_course(checkpoint)
            )
        set_checkpoint(
            job, checkpoint, checkpoint.get("course", {}) and checkpoint["course"]["resource"], progress
        )
        return False

    return stored


def future_due(item):
    due = due_at(item)
    return bool(due and due > now())


def materials(item):
    out = []
    for m in item.get("materials", []) or []:
        if "driveFile" in m:
            f = m["driveFile"].get("driveFile", m["driveFile"])
            out.append(
                {"kind": "drive", "title": f.get("title"), "reference": f.get("alternateLink") or f.get("id")}
            )
        elif "youtubeVideo" in m:
            v = m["youtubeVideo"]
            out.append(
                {
                    "kind": "youtube",
                    "title": v.get("title"),
                    "reference": v.get("alternateLink") or v.get("id"),
                }
            )
        elif "link" in m:
            out.append({"kind": "link", "title": m["link"].get("title"), "reference": m["link"].get("url")})
        elif "form" in m:
            out.append(
                {"kind": "form", "title": m["form"].get("title"), "reference": m["form"].get("formUrl")}
            )
    return out


def store_classroom(db, conn, sub, cid, resource, item):
    kind = {
        "submissions": "classroom_submission",
        "coursework": "classroom_coursework",
        "announcements": "classroom_announcement",
    }[resource]
    pid = f"classroom:{sub}:{cid}:{resource}:{item['id']}"
    attachments = [] if resource == "submissions" else materials(item)
    if resource == "submissions":
        history = []
        for entry in item.get("submissionHistory", []) or []:
            state = entry.get("stateHistory")
            if state:
                history.append({"state": state.get("state"), "at": state.get("stateTimestamp")})
        data = {
            "courseWorkId": item.get("courseWorkId"),
            "state": item.get("state"),
            "late": bool(item.get("late")),
            "courseWorkType": item.get("courseWorkType"),
            "stateHistory": history,
            "alternateLink": item.get("alternateLink"),
        }
        hashed = data
        title = None
    else:
        due = due_at(item)
        data = {
            "workType": item.get("workType"),
            "state": item.get("state"),
            "dueDate": item.get("dueDate"),
            "dueTime": item.get("dueTime"),
            "dueAt": iso(due),
            "scheduledTime": item.get("scheduledTime"),
            "assigneeMode": item.get("assigneeMode"),
            "alternateLink": item.get("alternateLink"),
            "materialCount": len(attachments),
        }
        # Descriptions and announcement text are hashed for revision detection, not stored.
        hashed = {
            **data,
            "title": item.get("title"),
            "text": item.get("description") or item.get("text"),
            "m": attachments,
        }
        title = (item.get("title") or None) and item["title"][:1000]
    digest = hashlib.sha256(json.dumps(hashed, sort_keys=True, default=str).encode()).hexdigest()
    record = db.scalar(
        select(SourceRecord)
        .where(SourceRecord.connection_id == conn.id, SourceRecord.provider_id == pid)
        .with_for_update()
    )
    if record and record.content_hash == digest:
        return "unchanged"
    result = "updated" if record else "stored"
    if record is None:
        record = SourceRecord(user_id=conn.user_id, connection_id=conn.id, provider_id=pid, kind=kind)
        db.add(record)
    else:
        record.revision += 1
    record.external_course_id = cid
    record.title = title
    record.published_at = parse_time(item.get("creationTime"))
    record.source_updated_at = parse_time(item.get("updateTime"))
    record.content_hash = digest
    record.processing_state = "awaiting_interpretation"
    record.processing_version = VERSION
    record.reason = None
    record.data = data
    db.flush()
    replace_attachments(db, record, attachments)
    return result
