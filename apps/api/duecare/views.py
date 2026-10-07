"""Shared response views for task and profile records."""

import uuid

from sqlalchemy import text

from .domain import effective_status, priority
from .models import Profile, Subject, now


def profile(db, uid):
    p = db.get(Profile, uuid.UUID(uid))
    if not p:
        db.execute(
            text(
                "insert into duecare.profiles (user_id,revision,data,created_at,updated_at) "
                "values (:id,1,'{}',now(),now()) on conflict do nothing"
            ),
            {"id": uid},
        )
        p = db.get(Profile, uuid.UUID(uid))
    return p


def task_out(t, db, uid):
    s = db.get(Subject, t.subject_id) if t.subject_id else None
    p = profile(db, uid)
    return {
        **t.data,
        "id": str(t.id),
        "title": t.title,
        "type": t.type,
        "subjectId": str(t.subject_id) if t.subject_id else None,
        "subjectName": s.name if s else None,
        "subjectKind": s.kind if s else None,
        "generalBatch": p.data.get("generalBatch"),
        "dueAt": t.due_at.isoformat() if t.due_at else None,
        "status": effective_status(t, now()),
        "priority": priority(t, now()),
        "completedAt": t.completed_at.isoformat() if t.completed_at else None,
        "completionOrigin": ((t.data.get("completion") or {}).get("origin") or "manual")
        if t.completed_at
        else None,
        "completion": t.data.get("completion") if t.completed_at else None,
        "revision": t.revision,
        "createdAt": t.created_at.isoformat(),
        "updatedAt": t.updated_at.isoformat(),
        "source": "+".join(t.data.get("sources") or ["manual"]),
        "sources": t.data.get("sources") or ["manual"],
        "mergedInto": t.data.get("mergedInto"),
    }
