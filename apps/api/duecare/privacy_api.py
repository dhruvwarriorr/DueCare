import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update

from . import auth, privacy
from .common import User, finish, owned, page, replay, revision, work
from .models import Activity, Connection, PrivacyJob, Suppression, now

router = APIRouter(prefix="/api/v1")
internal = APIRouter(prefix="/internal/privacy", dependencies=[Depends(auth.gateway)])


class ReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    read: bool
    revision: int


class SourceDeletionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    connection_id: uuid.UUID = Field(alias="connectionId")
    revision: int
    kind: Literal["source_data", "disconnect"] = "source_data"


class AccountInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: Literal["DELETE"]


class ResumeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    token: str = Field(min_length=64, max_length=64)
    advance: bool = False


def activity_out(item):
    return {
        "id": str(item.id),
        "eventType": item.event_type,
        "message": item.message,
        "targetType": item.target_type,
        "targetId": str(item.target_id),
        "createdAt": item.created_at.isoformat(),
        "readAt": item.read_at.isoformat() if item.read_at else None,
        "revision": item.revision,
    }


@router.get("/activity")
def activity(
    read: bool | None = None, limit: int = Query(50, ge=1, le=100), cursor: str | None = None, user=User
):
    with work(user) as db:
        stmt = select(Activity).where(Activity.user_id == user["id"])
        if read is not None:
            stmt = stmt.where(Activity.read_at.is_not(None) if read else Activity.read_at.is_(None))
        rows, next_cursor = page(db, stmt, Activity, limit, cursor)
        unread = db.scalar(
            select(func.count())
            .select_from(Activity)
            .where(Activity.user_id == user["id"], Activity.read_at.is_(None))
        )
        return {"items": [activity_out(a) for a in rows], "nextCursor": next_cursor, "unreadCount": unread}


@router.patch("/activity/{id}")
def mark_read(id: uuid.UUID, body: ReadInput, user=User):
    with work(user) as db:
        row = owned(db, Activity, id, user["id"], True)
        revision(row, body.revision)
        row.read_at, row.revision = (now() if body.read else None), row.revision + 1
        return activity_out(row)


@router.post("/activity/read-all")
def mark_all_read(user=User):
    with work(user) as db:
        result = db.execute(
            update(Activity)
            .where(Activity.user_id == user["id"], Activity.read_at.is_(None))
            .values(read_at=now(), revision=Activity.revision + 1)
        )
        return {"updated": result.rowcount}


@router.get("/privacy/jobs")
def jobs(limit: int = Query(50, ge=1, le=100), cursor: str | None = None, user=User):
    with work(user) as db:
        rows, c = page(
            db, select(PrivacyJob).where(PrivacyJob.user_id == user["id"]), PrivacyJob, limit, cursor
        )
        return {"items": [privacy.job_out(j) for j in rows], "nextCursor": c}


@router.post("/privacy/source-data-deletions")
def source_delete(body: SourceDeletionInput, request: Request, user=User):
    with work(user) as db:
        cached, op = replay(db, request, user, body.model_dump(mode="json"))
        if cached is not None:
            return cached
        conn = owned(db, Connection, body.connection_id, user["id"], True)
        revision(conn, body.revision)
        job = privacy.start_source(db, conn, body.kind)
        return finish(db, op, privacy.job_out(job))


@router.post("/privacy/jobs/{id}/advance")
def advance(id: uuid.UUID, user=User):
    with work(user) as db:
        job = owned(db, PrivacyJob, id, user["id"], True)
        conn = owned(db, Connection, job.connection_id, user["id"], True)
        return privacy.advance_source(db, job, conn)


def suppression_out(row):
    # Activity identifiers are hashed; no source text or account address is retained here.
    return {
        "id": str(row.id),
        "createdAt": row.created_at.isoformat(),
        "restoredAt": row.restored_at.isoformat() if row.restored_at else None,
        "revision": row.revision,
    }


@router.get("/suppression-records")
def suppressions(limit: int = Query(50, ge=1, le=100), cursor: str | None = None, user=User):
    with work(user) as db:
        rows, c = page(
            db,
            select(Suppression).where(Suppression.user_id == user["id"], Suppression.restored_at.is_(None)),
            Suppression,
            limit,
            cursor,
        )
        return {"items": [suppression_out(s) for s in rows], "nextCursor": c}


@router.post("/suppression-records/{id}/restore")
def restore(id: uuid.UUID, request: Request, user=User):
    with work(user) as db:
        cached, op = replay(db, request, user, {})
        if cached is not None:
            return cached
        row = owned(db, Suppression, id, user["id"], True)
        pending = db.scalars(
            select(Connection)
            .join(PrivacyJob, PrivacyJob.connection_id == Connection.id)
            .where(PrivacyJob.user_id == user["id"], PrivacyJob.status != "completed")
        )
        if any(privacy.namespace(db, conn) == row.namespace for conn in pending):
            from .errors import ApiError

            raise ApiError(409, "PRIVACY_IN_PROGRESS", "Finish the source privacy operation before restoring")
        row.restored_at, row.revision = now(), row.revision + 1
        # Restore only eligibility. The student explicitly starts a full reimport in Sources.
        return finish(db, op, suppression_out(row))


@router.post("/privacy/account-deletion")
def account_delete(body: AccountInput, user=User):
    with work({**user, "_privacy": True}) as db:
        return privacy.start_account(db, user["id"])


@router.get("/privacy/account-deletion")
def account_checkpoint(user=User):
    from .errors import ApiError
    from .models import AccountDeletion

    # An authenticated second browser can recover a pending deletion without the original cookie.
    with work({**user, "_privacy": True}) as db:
        job = db.scalar(select(AccountDeletion).where(AccountDeletion.user_id == user["id"]))
        if not job:
            raise ApiError(404, "NOT_FOUND", "No account deletion is in progress")
        return {**privacy.account_out(job), "resumeToken": privacy.deletion_token(job.id)}


@internal.post("/account-deletion")
def account_resume(body: ResumeInput):
    return privacy.resume_account(body.token, body.advance)


@router.post("/connections/{id}/reimport")
def reimport(id: uuid.UUID, request: Request, user=User):
    from sqlalchemy import update

    from .models import SourceRecord
    from .sync import cancel_jobs, ensure_job

    with work(user) as db:
        cached, op = replay(db, request, user, {})
        if cached is not None:
            return cached
        conn = owned(db, Connection, id, user["id"], True)
        if conn.data.get("privacyJobId"):
            from .errors import ApiError

            raise ApiError(409, "PRIVACY_IN_PROGRESS", "Finish the source privacy operation first")
        cancel_jobs(db, conn.id, "EXPLICIT_REIMPORT")
        conn.checkpoint = {}
        # New source revisions intentionally reconsider old event keys, while suppression still wins.
        db.execute(
            update(SourceRecord)
            .where(SourceRecord.connection_id == id, SourceRecord.processing_state != "blocked")
            .values(processing_state="awaiting_interpretation", revision=SourceRecord.revision + 1)
        )
        return finish(db, op, ensure_job(db, user["id"], id, "import", "manual"))
