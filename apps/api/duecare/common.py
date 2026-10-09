import base64
import hashlib
import json
import uuid
from contextlib import contextmanager
from datetime import datetime

from fastapi import Depends
from sqlalchemy import and_, or_, select, text

from . import auth
from .db import transaction
from .errors import ApiError
from .models import Operation

User = Depends(auth.current_user)


def owned(db, model, id, uid, lock=False):
    stmt = select(model).where(model.id == id, model.user_id == uid)
    obj = db.scalar(stmt.with_for_update() if lock else stmt)
    if obj is None:
        raise ApiError(404, "NOT_FOUND", "This item is unavailable")
    return obj


def revision(obj, value):
    if value is None or obj.revision != value:
        raise ApiError(409, "REVISION_CONFLICT", "This item changed. Refresh it before saving again")


@contextmanager
def work(user):
    with transaction(user["id"]) as db:
        try:
            from .models import AccountDeletion
            from .privacy import cleanup, owner_lock

            owner_lock(db, user["id"])
            deleting = db.scalar(select(AccountDeletion.id).where(AccountDeletion.user_id == user["id"]))
            if deleting and not user.get("_privacy"):
                raise ApiError(
                    409,
                    "ACCOUNT_DELETING",
                    "Account deletion is in progress. Resume it from the deletion page",
                )
            cleanup(db, user["id"])
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise


# Compound writes use a transaction-scoped lock and durable idempotency result.
def replay(db, request, user, payload):
    key = request.headers.get("idempotency-key", "")
    if not key or len(key) > 100:
        raise ApiError(422, "IDEMPOTENCY_REQUIRED", "An idempotency key is required")
    fingerprint = hashlib.sha256(
        (request.method + request.url.path + json.dumps(payload, sort_keys=True, default=str)).encode()
    ).hexdigest()
    db.execute(text("select pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": user["id"] + key})
    existing = db.scalar(select(Operation).where(Operation.user_id == user["id"], Operation.key == key))
    if existing:
        if existing.fingerprint != fingerprint:
            raise ApiError(409, "IDEMPOTENCY_CONFLICT", "This key was already used for another operation")
        if existing.result.get("privacyErased"):
            raise ApiError(410, "RESULT_ERASED", "This result was removed by a privacy request")
        return existing.result, None
    return None, Operation(user_id=uuid.UUID(user["id"]), key=key, fingerprint=fingerprint, result={})


def finish(db, op, result):
    op.result = result
    db.add(op)
    return result


def page(db, stmt, model, limit, cursor):
    if cursor:
        try:
            stamp, id = json.loads(base64.urlsafe_b64decode(cursor.encode()))
            stamp = datetime.fromisoformat(stamp)
            id = uuid.UUID(id)
            stmt = stmt.where(or_(model.created_at < stamp, and_(model.created_at == stamp, model.id < id)))
        except (ValueError, TypeError, KeyError):
            raise ApiError(422, "INVALID_CURSOR", "Invalid page cursor")
    rows = list(db.scalars(stmt.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1)))
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = base64.urlsafe_b64encode(
            json.dumps([last.created_at.isoformat(), str(last.id)]).encode()
        ).decode()
    return rows[:limit], next_cursor
