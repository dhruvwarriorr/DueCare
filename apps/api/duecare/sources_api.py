"""Phase 2 routes: source connections, OAuth callbacks, sync jobs, sender preferences, mappings."""

import base64
import hashlib
import logging
import re
import secrets
import uuid
from datetime import timedelta

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, or_, select

from . import auth, faculty, google, interpret, mail, sync
from .common import User, finish, owned, page, replay, revision, work
from .config import settings
from .db import transaction
from .errors import ApiError
from .mail import normalize_email
from .models import (
    Connection,
    GoogleAccount,
    OAuthGrant,
    OAuthState,
    PrivacyJob,
    SenderPreference,
    SourceCourse,
    SourceRecord,
    Subject,
    SubjectMapping,
    SyncJob,
    now,
)
from .schemas import AuthorizeInput, SenderPreferenceInput, SyncInput

router = APIRouter(prefix="/api/v1")
log = logging.getLogger("duecare.sources")
STATE_TTL = timedelta(minutes=10)
COURSE_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


def account_out(a):
    return {
        "id": str(a.id),
        "email": a.email,
        "name": a.data.get("name"),
        "photo": a.data.get("picture"),
    }


def connection_out(db, conn):
    account = db.get(GoogleAccount, conn.account_id)
    active = db.scalar(
        select(SyncJob).where(SyncJob.connection_id == conn.id, SyncJob.status.in_(sync.ACTIVE))
    )
    last = db.scalar(
        select(SyncJob)
        .where(SyncJob.connection_id == conn.id, SyncJob.status.in_(sync.TERMINAL))
        .order_by(SyncJob.created_at.desc())
        .limit(1)
    )
    counts = dict(
        db.execute(
            select(SourceRecord.processing_state, func.count())
            .where(
                SourceRecord.connection_id == conn.id,
                or_(SourceRecord.expires_at.is_(None), SourceRecord.expires_at > now()),
                or_(SourceRecord.processing_state != "awaiting_interpretation", interpret.in_gmail_window()),
            )
            .group_by(SourceRecord.processing_state)
        ).all()
    )
    paused = db.scalar(
        select(func.count())
        .select_from(SourceRecord)
        .where(
            SourceRecord.connection_id == conn.id,
            SourceRecord.processing_state == "awaiting_interpretation",
            SourceRecord.data["aiPausedReason"].astext.is_not(None),
            interpret.in_gmail_window(),
        )
    )
    return {
        "id": str(conn.id),
        "service": conn.service,
        "status": conn.status,
        "revision": conn.revision,
        "account": account_out(account),
        "permissions": conn.scopes,
        "optionalPermissionsMissing": [
            s for s in google.OPTIONAL_SCOPES[conn.service] if s not in conn.scopes
        ],
        "lastAttemptAt": sync.iso(conn.last_attempt_at),
        "lastSuccessAt": sync.iso(conn.last_success_at),
        "retryAt": sync.iso(conn.retry_at),
        "lastError": conn.data.get("lastError"),
        "privacyJobId": conn.data.get("privacyJobId"),
        "activeJob": sync.job_out(active) if active else None,
        "lastJob": sync.job_out(last) if last else None,
        "records": {
            "awaitingInterpretation": counts.get("awaiting_interpretation", 0),
            "interpreted": counts.get("interpreted", 0),
            "needsReview": counts.get("needs_review", 0),
            "aiPaused": paused,
            "duplicates": counts.get("duplicate", 0),
            "blocked": counts.get("blocked", 0),
            "ignored": counts.get("ignored", 0),
        },
    }


def sync_summary(db, uid):
    """Dashboard view of connected sources; None when the student has not connected any."""
    rows = db.scalars(
        select(Connection)
        .where(Connection.user_id == uid, Connection.status != "disconnected")
        .order_by(Connection.created_at)
    ).all()
    if not rows:
        return None
    return [connection_out(db, c) for c in rows]


@router.get("/connections")
def connections(user=User):
    with work(user) as db:
        rows = db.scalars(
            select(Connection)
            .where(Connection.user_id == user["id"])
            .order_by(Connection.created_at, Connection.id)
        )
        return {"items": [connection_out(db, c) for c in rows]}


@router.post("/connections/authorize")
def authorize(body: AuthorizeInput, user=User):
    google.configured()
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    hint = None
    if body.account_id:
        with work(user) as db:
            hint = owned(db, GoogleAccount, body.account_id, user["id"]).email
    with transaction() as db:
        db.query(OAuthState).filter(OAuthState.created_at < now() - STATE_TTL).delete()
        db.add(
            OAuthState(
                id=auth.digest(state),
                user_id=uuid.UUID(user["id"]),
                service=body.service,
                verifier=auth.crypt().encrypt(verifier.encode()).decode(),
            )
        )
        db.commit()
    return {"url": google.provider.authorization_url(body.service, state, challenge, hint)}


@router.get("/connections/oauth/callback")
def oauth_callback(
    state: str = Query("", max_length=200),
    code: str = Query("", max_length=3000),
    error: str = Query("", max_length=200),
    user=User,
):
    # Source callbacks require the authenticated eligible DueCare session that started them.
    with transaction() as db:
        entry = db.scalar(select(OAuthState).where(OAuthState.id == auth.digest(state)).with_for_update())
        if not state or not entry or entry.created_at < now() - STATE_TTL or str(entry.user_id) != user["id"]:
            raise ApiError(400, "AUTHORIZATION_EXPIRED", "This connection attempt expired. Start it again")
        service, verifier = entry.service, auth.crypt().decrypt(entry.verifier.encode()).decode()
        db.delete(entry)
        db.commit()  # One-use state, consumed even when the exchange fails.
    if error or not code:
        raise ApiError(400, "AUTHORIZATION_DECLINED", "Google access was not granted")
    try:
        tokens = google.provider.exchange(code, verifier)
        if not tokens.get("id_token") or not tokens.get("access_token"):
            raise google.SourceError("auth", "Google did not return the account identity")
        claims = google.provider.identity(tokens["id_token"])
    except google.SourceError as exc:
        status = 503 if exc.kind == "retryable" else 400
        raise ApiError(status, "AUTHORIZATION_FAILED", exc.message)
    if (
        claims.get("email_verified") is not True
        or not claims.get("sub")
        or not normalize_email(claims.get("email"))
    ):
        raise ApiError(400, "ACCOUNT_UNVERIFIED", "Connect a Google account with a verified email address")
    profile = {"name": claims.get("name"), "picture": claims.get("picture")}
    with work(user) as db:
        result = link_account(
            db, user["id"], claims["sub"], claims["email"], profile, tokens, google.services_for(service)
        )
    if "error" in result:
        raise ApiError(403, *result["error"])
    return result


def link_account(db, uid, sub, email, profile, tokens, services):
    """Store an encrypted grant for a verified Google account and activate each fully granted service."""
    granted = google.granted_scopes(tokens.get("scope"))
    vault = google.vault()
    uid = uuid.UUID(str(uid))
    account = db.scalar(
        select(GoogleAccount)
        .where(GoogleAccount.user_id == uid, GoogleAccount.google_sub == sub)
        .with_for_update()
    )
    if account is None:
        account = GoogleAccount(user_id=uid, google_sub=sub, email="")
        db.add(account)
    elif db.scalar(
        select(PrivacyJob.id)
        .join(Connection, Connection.id == PrivacyJob.connection_id)
        .where(Connection.account_id == account.id, PrivacyJob.status != "completed")
        .limit(1)
    ):
        raise ApiError(409, "PRIVACY_IN_PROGRESS", "Finish the source privacy operation before reconnecting")
    account.email = normalize_email(email)
    account.data = {**profile, "emailVerified": True}
    db.flush()
    grant = db.scalar(select(OAuthGrant).where(OAuthGrant.account_id == account.id).with_for_update())
    refresh = tokens.get("refresh_token")
    if not refresh and grant and grant.status == "active" and grant.refresh_token:
        # Google can omit a replacement refresh token; preserve the existing one.
        refresh = vault.decrypt(grant.refresh_token, grant.key_version)
    if not refresh:
        return {
            "error": ("OFFLINE_ACCESS_REQUIRED", "Sign in again and allow DueCare to keep read-only access")
        }
    if grant is None:
        grant = OAuthGrant(user_id=uid, account_id=account.id, key_version=vault.current)
        db.add(grant)
    previous = set(grant.scopes or []) if grant.status == "active" else set()
    grant.scopes = sorted(granted | previous)
    granted = set(grant.scopes)
    grant.refresh_token = vault.encrypt(refresh)
    grant.access_token = vault.encrypt(tokens["access_token"])
    grant.access_expires_at = google.expiry(tokens)
    grant.key_version, grant.status = vault.current, "active"
    connected, missing = [], {}
    for svc in services:
        gaps = google.missing_scopes(svc, granted)
        if gaps:
            missing[svc] = [g.rsplit("/", 1)[-1] for g in gaps]
            continue
        conn = db.scalar(
            select(Connection)
            .where(Connection.account_id == account.id, Connection.service == svc)
            .with_for_update()
        )
        if conn is None:
            conn = Connection(user_id=uid, account_id=account.id, service=svc, checkpoint={}, data={})
            db.add(conn)
        elif conn.status != "active":
            conn.revision += 1
        optional = [s for s in google.OPTIONAL_SCOPES[svc] if s in granted]
        conn.status, conn.scopes = "active", google.SERVICE_SCOPES[svc] + optional
        conn.data = {**(conn.data or {}), "lastError": None, "connectedAt": now().isoformat()}
        db.flush()
        connected.append({"connectionId": str(conn.id), "service": svc})
    if not connected:
        in_use = db.scalar(
            select(func.count())
            .select_from(Connection)
            .where(Connection.account_id == account.id, Connection.status == "active")
        )
        if not in_use:
            # Nothing usable was granted: do not keep an unused grant.
            try:
                google.provider.revoke(refresh)
            except google.SourceError:
                pass
            grant.refresh_token = grant.access_token = grant.access_expires_at = None
            grant.status, grant.scopes = "revoked", []
        labels = ", ".join(x for gaps in missing.values() for x in gaps)
        return {
            "error": (
                "PERMISSION_NOT_GRANTED",
                f"Allow every requested read-only permission to connect (missing: {labels})",
            )
        }
    return {
        "connections": connected,
        "services": [c["service"] for c in connected],
        "missing": missing,
        "accountEmail": account.email,
        "connectionId": connected[0]["connectionId"],
        "service": connected[0]["service"],
    }


def attach_login_grant(identity, provider):
    """Turn the Google tokens returned at Somaiya sign-in into Gmail and Classroom connections.

    Never blocks sign-in: on any problem the student can still use DueCare and grant access later."""
    token = provider.get("provider_token")
    if not token:
        return None
    try:
        google.configured()
        info = google.provider.token_info(token)
        # The grant must belong to DueCare's OAuth client (so it can be refreshed) and to this account.
        if (
            info.get("aud") != settings().google_oauth_client_id
            or str(info.get("email", "")).lower() != identity["email"]
        ):
            log.warning("sign-in Google token not usable for sources")
            return None
        tokens = {
            "access_token": token,
            "refresh_token": provider.get("provider_refresh_token"),
            "expires_in": info.get("expires_in", 0),
            "scope": info.get("scope", ""),
        }
        profile = {"name": identity.get("name"), "picture": identity.get("photo")}
        with work(identity) as db:
            result = link_account(
                db, identity["id"], info["sub"], identity["email"], profile, tokens, ["gmail", "classroom"]
            )
        return result
    except (ApiError, google.SourceError, KeyError):
        log.warning("could not attach sign-in Google grant")
        return None


@router.delete("/connections/{id}")
def disconnect(id: uuid.UUID, request: Request, revision_value: int = Query(alias="revision"), user=User):
    from .models import Operation
    from .privacy import advance_source, job_out, start_source

    # Persist the disconnect and cancellation before reaching Google. A crash or outage cannot
    # roll back the student's stop-sync request; the private revoke checkpoint remains resumable.
    with work(user) as db:
        cached, op = replay(db, request, user, {"revision": revision_value})
        if cached is not None:
            return cached
        conn = owned(db, Connection, id, user["id"], True)
        revision(conn, revision_value)
        cancelled = sync.cancel_jobs(db, conn.id, "DISCONNECTED")
        job = start_source(db, conn, "disconnect")
        preserved = db.scalar(
            select(func.count()).select_from(SourceRecord).where(SourceRecord.connection_id == conn.id)
        )
        result = {
            "ok": True,
            "connectionId": str(conn.id),
            "service": conn.service,
            "cancelledJobs": cancelled,
            "googleAccessRevoked": False,
            "preservedSourceRecords": preserved,
            "privacyJob": job_out(job),
        }
        finish(db, op, result)
        db.flush()
        op_id, job_id = op.id, job.id
    with work(user) as db:
        from .models import PrivacyJob

        job = owned(db, PrivacyJob, job_id, user["id"], True)
        conn = owned(db, Connection, id, user["id"], True)
        checkpoint = advance_source(db, job, conn)
        result = {
            **result,
            "privacyJob": checkpoint,
            "googleAccessRevoked": checkpoint["status"] == "completed"
            and bool(job.data.get("googleAccessRevoked")),
        }
        owned(db, Operation, op_id, user["id"], True).result = result
        return result


@router.post("/connections/{id}/sync")
def start_sync(id: uuid.UUID, body: SyncInput, request: Request, user=User):
    with work(user) as db:
        cached, op = replay(db, request, user, body.model_dump(mode="json"))
        if cached is not None:
            return cached
        return finish(db, op, sync.ensure_job(db, user["id"], id, "import", body.trigger))


@router.post("/connections/{id}/reprocess")
def reprocess(id: uuid.UUID, request: Request, user=User):
    with work(user) as db:
        cached, op = replay(db, request, user, {})
        if cached is not None:
            return cached
        return finish(db, op, sync.ensure_job(db, user["id"], id, "reprocess", "manual"))


@router.get("/sync-jobs/{id}")
def get_job(id: uuid.UUID, user=User):
    with work(user) as db:
        return sync.job_out(owned(db, SyncJob, id, user["id"]))


@router.post("/sync-jobs/{id}/advance")
def advance_job(id: uuid.UUID, user=User):
    return sync.advance(user, id)


@router.get("/connections/{id}/classroom-courses")
def classroom_courses(
    id: uuid.UUID, limit: int = Query(50, ge=1, le=100), cursor: str | None = None, user=User
):
    with work(user) as db:
        conn = owned(db, Connection, id, user["id"])
        if conn.service != "classroom":
            raise ApiError(404, "NOT_FOUND", "This item is unavailable")
        rows, next_cursor = page(
            db, select(SourceCourse).where(SourceCourse.connection_id == conn.id), SourceCourse, limit, cursor
        )
        mapped = {}
        for m, s in db.execute(
            select(SubjectMapping, Subject)
            .join(Subject, Subject.id == SubjectMapping.subject_id)
            .where(
                SubjectMapping.connection_id == conn.id,
                SubjectMapping.external_course_id.in_([r.external_course_id for r in rows]),
            )
        ):
            mapped.setdefault(m.external_course_id, []).append(
                {
                    "subjectId": str(s.id),
                    "subjectName": s.name,
                    "subjectKind": s.kind,
                    "automatic": bool(m.data.get("automatic")),
                }
            )
        return {
            "items": [
                {
                    "externalCourseId": r.external_course_id,
                    "name": r.name,
                    "section": r.data.get("section"),
                    "courseState": r.data.get("courseState"),
                    "alternateLink": r.data.get("alternateLink"),
                    "available": r.available,
                    "mappings": mapped.get(r.external_course_id, []),
                }
                for r in rows
            ],
            "nextCursor": next_cursor,
        }


def mapping_out(m, account=None):
    return {
        "connectionId": str(m.connection_id),
        "externalCourseId": m.external_course_id,
        "courseName": m.data.get("courseName"),
        "section": m.data.get("section"),
        "sourceAvailable": m.source_available,
        "subjectKind": m.data.get("subjectKind"),
        "automatic": bool(m.data.get("automatic")),
        "accountEmail": account.email if account else None,
    }


def mappings_for(db, subject_ids):
    out = {}
    if not subject_ids:
        return out
    for m, a in db.execute(
        select(SubjectMapping, GoogleAccount)
        .join(Connection, Connection.id == SubjectMapping.connection_id)
        .join(GoogleAccount, GoogleAccount.id == Connection.account_id)
        .where(SubjectMapping.subject_id.in_(subject_ids))
        .order_by(SubjectMapping.created_at)
    ):
        out.setdefault(m.subject_id, []).append(mapping_out(m, account=a))
    return out


@router.put("/subjects/{id}/classroom-mappings/{connection_id}/{course_id}")
def map_course(id: uuid.UUID, connection_id: uuid.UUID, course_id: str, request: Request, user=User):
    if not COURSE_ID.match(course_id):
        raise ApiError(404, "NOT_FOUND", "This item is unavailable")
    with work(user) as db:
        cached, op = replay(db, request, user, {})
        if cached is not None:
            return cached
        subject = owned(db, Subject, id, user["id"])
        conn = owned(db, Connection, connection_id, user["id"])
        course = db.scalar(
            select(SourceCourse).where(
                SourceCourse.connection_id == conn.id, SourceCourse.external_course_id == course_id
            )
        )
        if conn.service != "classroom" or course is None:
            raise ApiError(404, "NOT_FOUND", "This Classroom course is unavailable")
        mapping = db.scalar(
            select(SubjectMapping).where(
                SubjectMapping.subject_id == subject.id,
                SubjectMapping.connection_id == conn.id,
                SubjectMapping.external_course_id == course_id,
            )
        )
        if mapping is None:
            mapping = SubjectMapping(
                user_id=subject.user_id,
                subject_id=subject.id,
                connection_id=conn.id,
                external_course_id=course_id,
            )
            db.add(mapping)
        mapping.source_available = course.available
        # The subject kind is recorded as context only; the profile batch remains the only student batch.
        mapping.data = {
            "courseName": course.name,
            "section": course.data.get("section"),
            "subjectKind": subject.kind,
        }
        db.flush()
        return finish(db, op, mapping_out(mapping, account=db.get(GoogleAccount, conn.account_id)))


@router.delete("/subjects/{id}/classroom-mappings/{connection_id}/{course_id}")
def unmap_course(id: uuid.UUID, connection_id: uuid.UUID, course_id: str, request: Request, user=User):
    with work(user) as db:
        cached, op = replay(db, request, user, {})
        if cached is not None:
            return cached
        owned(db, Subject, id, user["id"])
        mapping = db.scalar(
            select(SubjectMapping).where(
                SubjectMapping.user_id == user["id"],
                SubjectMapping.subject_id == id,
                SubjectMapping.connection_id == connection_id,
                SubjectMapping.external_course_id == course_id,
            )
        )
        if mapping:
            db.delete(mapping)
            # A course the student unlinked is never linked again automatically.
            course = db.scalar(
                select(SourceCourse).where(
                    SourceCourse.connection_id == connection_id, SourceCourse.external_course_id == course_id
                )
            )
            if course:
                course.data = {**course.data, "autoLinkDeclined": True}
        # Future syncs stop using this mapping; existing tasks and source records are preserved.
        return finish(db, op, {"ok": True, "removed": bool(mapping)})


def preference_out(p):
    return {
        "email": p.email,
        "action": p.action,
        "revision": p.revision,
        "createdAt": p.created_at.isoformat(),
        "updatedAt": p.updated_at.isoformat(),
    }


def sender_address(value):
    email = normalize_email(value)
    if not email:
        raise ApiError(
            422, "INVALID_SENDER", "Enter one exact sender email address", {"email": "Invalid address"}
        )
    return email


def faculty_out(db, uid):
    return {
        "items": [
            {"email": email, **data}
            for email, data in sorted(faculty.entries(db, uid).items())
            if data.get("approved")
        ]
    }


@router.get("/approved-faculty")
def approved_faculty(user=User):
    with work(user) as db:
        from .reconcile import ensure_source_policy

        ensure_source_policy(db, user["id"])
        return faculty_out(db, user["id"])


@router.put("/approved-faculty/{sender_email}")
def approve_faculty(sender_email: str, user=User):
    email = sender_address(sender_email)
    with work(user) as db:
        sync.lock_sender(db, user["id"], email)
        records = db.scalars(
            select(SourceRecord).where(
                SourceRecord.user_id == user["id"],
                SourceRecord.kind == "gmail_message",
                SourceRecord.sender_email == email,
                SourceRecord.processing_state.not_in(("ignored", "blocked")),
            )
        ).all()
        if not any(
            not mail.academic_exclusion(r.title, email, r.data.get("senderName"), r.excerpt) for r in records
        ):
            raise ApiError(422, "FACULTY_UNAVAILABLE", "Only a sender of your academic mail can be approved")
        if not faculty.approve(db, user["id"], email, "student"):
            raise ApiError(409, "SENDER_BLOCKED", "Unblock this sender before approving them")
        from .reconcile import refresh_faculty_reviews

        resolved = refresh_faculty_reviews(db, user["id"])
        return {**faculty_out(db, user["id"]), "reviewsResolved": resolved}


@router.delete("/approved-faculty/{sender_email}")
def revoke_faculty(sender_email: str, user=User):
    email = sender_address(sender_email)
    with work(user) as db:
        faculty.revoke(db, user["id"], email)
        return faculty_out(db, user["id"])


@router.get("/sender-preferences")
def sender_preferences(limit: int = Query(50, ge=1, le=100), cursor: str | None = None, user=User):
    with work(user) as db:
        rows, next_cursor = page(
            db,
            select(SenderPreference).where(SenderPreference.user_id == user["id"]),
            SenderPreference,
            limit,
            cursor,
        )
        return {"items": [preference_out(p) for p in rows], "nextCursor": next_cursor}


@router.put("/sender-preferences/{sender_email}")
def set_sender_preference(sender_email: str, body: SenderPreferenceInput, user=User):
    email = sender_address(sender_email)
    with work(user) as db:
        sync.lock_sender(db, user["id"], email)
        pref = db.scalar(
            select(SenderPreference)
            .where(SenderPreference.user_id == user["id"], SenderPreference.email == email)
            .with_for_update()
        )
        if pref is None:
            if body.revision is not None:
                raise ApiError(409, "REVISION_CONFLICT", "This item changed. Refresh it before saving again")
            pref = SenderPreference(user_id=uuid.UUID(user["id"]), email=email, action=body.action)
            db.add(pref)
        else:
            revision(pref, body.revision)
            pref.action = body.action
            pref.revision += 1
        db.flush()
        suppressed = sync.suppress_sender(db, user["id"], email) if body.action == "block" else 0
        return {**preference_out(pref), "suppressedRecords": suppressed}


@router.delete("/sender-preferences/{sender_email}")
def delete_sender_preference(sender_email: str, revision_value: int = Query(alias="revision"), user=User):
    email = sender_address(sender_email)
    with work(user) as db:
        sync.lock_sender(db, user["id"], email)
        pref = db.scalar(
            select(SenderPreference)
            .where(SenderPreference.user_id == user["id"], SenderPreference.email == email)
            .with_for_update()
        )
        if pref is None:
            raise ApiError(404, "NOT_FOUND", "This item is unavailable")
        revision(pref, revision_value)
        db.delete(pref)
        # Removing a block affects future processing; ignored mail returns only through reprocessing.
        return {"ok": True, "email": email}
