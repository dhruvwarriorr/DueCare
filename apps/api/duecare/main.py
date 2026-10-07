import logging
import uuid
from datetime import datetime, timedelta
from typing import Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import and_, case, func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError

from . import auth, sources_api
from .common import User, finish, owned, page, replay, revision, work
from .db import transaction
from .domain import effective_status, priority, task_data
from .errors import ApiError
from .models import History, Profile, Slot, Subject, Task, now
from .schemas import ProfilePatch, SubjectInput, TaskInput, TaskPatch, TimetableInput

app = FastAPI(title="DueCare API", version="0.2.0", openapi_url="/api/v1/openapi.json")


@app.middleware("http")
async def request_id(request, call_next):
    request.state.request_id = str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(ApiError)
async def errors(request, exc):
    return JSONResponse(
        status_code=exc.status,
        content={
            "code": exc.code,
            "message": exc.message,
            "fieldErrors": exc.fields,
            "requestId": request.state.request_id,
        },
    )


@app.exception_handler(RequestValidationError)
@app.exception_handler(ValidationError)
async def validation(request, exc):
    fields = {
        ".".join(map(str, e["loc"][1:] if e["loc"] and e["loc"][0] == "body" else e["loc"])): e["msg"]
        for e in exc.errors()
    }
    return JSONResponse(
        status_code=422,
        content={
            "code": "INVALID_INPUT",
            "message": "Check the highlighted fields",
            "fieldErrors": fields,
            "requestId": request.state.request_id,
        },
    )


@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    return JSONResponse(
        status_code=503,
        content={
            "code": "DATABASE_UNAVAILABLE",
            "message": "Data is temporarily unavailable. Please try again",
            "requestId": request.state.request_id,
        },
    )


@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    # Unexpected failures still return the structured error contract; details stay in server logs.
    logging.getLogger("duecare").exception("unhandled error", extra={"requestId": request.state.request_id})
    return JSONResponse(
        status_code=500,
        content={
            "code": "INTERNAL_ERROR",
            "message": "Something went wrong. Please try again",
            "requestId": request.state.request_id,
        },
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    with transaction() as db:
        db.execute(text("select 1 from duecare.profiles limit 1"))
    return {"status": "ok"}


@app.post("/internal/auth/start", dependencies=[Depends(auth.gateway)])
def start():
    return auth.login_start()


@app.post("/internal/auth/callback", dependencies=[Depends(auth.gateway)])
def callback(body: dict):
    state, code = body.get("state"), body.get("code")
    if not isinstance(state, str) or not isinstance(code, str) or len(state) > 100 or len(code) > 3000:
        raise ApiError(422, "INVALID_CALLBACK", "Invalid sign-in callback")
    return {"session": auth.login_finish(state, code)}


@app.post("/internal/auth/logout")
def logout(request: Request):
    auth.logout(request)
    return {"ok": True}


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


def profile_out(p, user):
    fields = (
        "institution",
        "programme",
        "department",
        "admissionYear",
        "classYear",
        "currentSemester",
        "division",
        "generalBatch",
        "rollNumber",
    )
    return {
        **p.data,
        "theme": p.data.get("theme", "system"),
        "id": str(p.user_id),
        "identity": user,
        "revision": p.revision,
        "onboardingComplete": all(p.data.get(f) for f in fields),
    }


def subject_out(s, mappings=()):
    return {
        **s.data,
        "id": str(s.id),
        "name": s.name,
        "kind": s.kind,
        "revision": s.revision,
        "classroomMappings": list(mappings),
    }


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
        "completionOrigin": "manual" if t.completed_at else None,
        "revision": t.revision,
        "createdAt": t.created_at.isoformat(),
        "updatedAt": t.updated_at.isoformat(),
        "source": "manual",
    }


def history(db, t, action, changes):
    db.add(History(user_id=t.user_id, task_id=t.id, action=action, changes=changes))


@app.get("/api/v1/me")
def me(user=User):
    with work(user) as db:
        return profile_out(profile(db, user["id"]), user)


@app.patch("/api/v1/me")
def update_me(body: ProfilePatch, user=User):
    with work(user) as db:
        p = profile(db, user["id"])
        db.refresh(p, with_for_update=True)
        revision(p, body.revision)
        changes = body.model_dump(mode="json", by_alias=True, exclude_unset=True, exclude={"revision"})
        if any(v is None for v in changes.values()):
            raise ApiError(422, "INVALID_PROFILE", "Profile fields cannot be cleared")
        p.data = {**p.data, **changes}
        p.revision += 1
        db.flush()
        return profile_out(p, user)


@app.get("/api/v1/subjects")
def subjects(limit: int = Query(50, ge=1, le=100), cursor: str | None = None, user=User):
    with work(user) as db:
        rows, c = page(db, select(Subject).where(Subject.user_id == user["id"]), Subject, limit, cursor)
        mappings = sources_api.mappings_for(db, [s.id for s in rows])
        return {"items": [subject_out(s, mappings.get(s.id, [])) for s in rows], "nextCursor": c}


@app.post("/api/v1/subjects", status_code=201)
def add_subject(body: SubjectInput, user=User):
    with work(user) as db:
        s = Subject(
            user_id=uuid.UUID(user["id"]),
            name=body.name,
            kind=body.kind,
            data=body.model_dump(mode="json", by_alias=True, exclude={"name", "kind", "revision"}),
        )
        db.add(s)
        db.flush()
        return subject_out(s)


@app.get("/api/v1/subjects/{id}")
def get_subject(id: uuid.UUID, user=User):
    with work(user) as db:
        s = owned(db, Subject, id, user["id"])
        return subject_out(s, sources_api.mappings_for(db, [s.id]).get(s.id, []))


@app.patch("/api/v1/subjects/{id}")
def edit_subject(id: uuid.UUID, body: SubjectInput, user=User):
    with work(user) as db:
        s = owned(db, Subject, id, user["id"], True)
        revision(s, body.revision)
        s.name, s.kind = body.name, body.kind
        s.data = body.model_dump(mode="json", by_alias=True, exclude={"name", "kind", "revision"})
        s.revision += 1
        return subject_out(s, sources_api.mappings_for(db, [s.id]).get(s.id, []))


@app.delete("/api/v1/subjects/{id}")
def delete_subject(id: uuid.UUID, request: Request, revision_value: int = Query(alias="revision"), user=User):
    with work(user) as db:
        cached, op = replay(db, request, user, {"revision": revision_value})
        if cached is not None:
            return cached
        s = owned(db, Subject, id, user["id"], True)
        revision(s, revision_value)
        # Retain tasks and manual history, unlinking the deleted subject explicitly.
        for t in db.scalars(
            select(Task).where(Task.user_id == user["id"], Task.subject_id == id).with_for_update()
        ):
            t.subject_id = None
            t.data = {**t.data, "subjectId": None}
            t.revision += 1
            history(db, t, "subject_removed", {"subjectId": None})
        db.flush()
        db.delete(s)
        return finish(db, op, {"ok": True})


@app.get("/api/v1/subjects/{id}/timetable")
def timetable(id: uuid.UUID, user=User):
    with work(user) as db:
        s = owned(db, Subject, id, user["id"])
        return {
            "revision": s.revision,
            "slots": [
                {"id": str(slot.id), **slot.data}
                for slot in db.scalars(
                    select(Slot)
                    .where(Slot.user_id == user["id"], Slot.subject_id == id)
                    .order_by(Slot.created_at, Slot.id)
                )
            ],
        }


@app.put("/api/v1/subjects/{id}/timetable")
def save_timetable(id: uuid.UUID, body: TimetableInput, request: Request, user=User):
    with work(user) as db:
        cached, op = replay(db, request, user, body.model_dump(mode="json"))
        if cached is not None:
            return cached
        s = owned(db, Subject, id, user["id"], True)
        revision(s, body.revision)
        p = profile(db, user["id"])
        current = {
            slot.id: slot
            for slot in db.scalars(select(Slot).where(Slot.subject_id == id, Slot.user_id == user["id"]))
        }
        retained = set()
        result = []
        for item in body.slots:
            if item.id and item.id not in current:
                raise ApiError(404, "NOT_FOUND", "This timetable slot is unavailable")
            slot = current.get(item.id) if item.id else Slot(subject_id=id, user_id=uuid.UUID(user["id"]))
            if item.id in retained:
                raise ApiError(422, "DUPLICATE_SLOT", "A slot cannot be saved twice")
            slot.data = {
                **item.model_dump(mode="json", by_alias=True, exclude={"id"}),
                "timezone": "Asia/Kolkata",
                "semesterContext": p.data.get("currentSemester"),
                "termContext": s.data.get("term"),
                "subjectRevision": s.revision + 1,
            }
            db.add(slot)
            db.flush()
            retained.add(slot.id)
            result.append({"id": str(slot.id), **slot.data})
        for key, slot in current.items():
            if key not in retained:
                db.delete(slot)
        s.revision += 1
        return finish(db, op, {"revision": s.revision, "slots": result})


@app.get("/api/v1/tasks")
def tasks(
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
    q: str = "",
    status: str | None = None,
    type: Literal["assignment", "test"] | None = None,
    subject_id: uuid.UUID | None = Query(None, alias="subjectId"),
    subject_kind: Literal["theory", "lab", "tutorial"] | None = Query(None, alias="subjectKind"),
    priority_filter: Literal["low", "medium", "high", "critical"] | None = Query(None, alias="priority"),
    undated: bool = False,
    date_from: datetime | None = Query(None, alias="dateFrom"),
    date_to: datetime | None = Query(None, alias="dateTo"),
    source: str | None = None,
    batch: str | None = None,
    user=User,
):
    with work(user) as db:
        stmt = select(Task).where(Task.user_id == user["id"])
        for value in (date_from, date_to):
            if value and value.tzinfo is None:
                raise ApiError(422, "INVALID_TIME", "Date filters must include a timezone")
        if date_from and date_to and date_from >= date_to:
            raise ApiError(422, "INVALID_TIME", "Date range end must be after its start")
        current = now()
        effective = case(
            (Task.completed_at.is_not(None), "completed"),
            (and_(Task.due_at <= current, Task.type == "test"), "missed"),
            (Task.due_at <= current, "overdue"),
            else_="due",
        )
        if status:
            if status not in ("due", "completed", "overdue", "missed"):
                raise ApiError(422, "INVALID_STATUS", "Invalid status")
            stmt = stmt.where(effective == status)
        if type:
            stmt = stmt.where(Task.type == type)
        if subject_id:
            stmt = stmt.where(Task.subject_id == subject_id)
        if subject_kind:
            stmt = stmt.join(Subject, Task.subject_id == Subject.id).where(Subject.kind == subject_kind)
        if q:
            stmt = stmt.where(
                or_(Task.title.ilike("%" + q + "%"), Task.data["notes"].astext.ilike("%" + q + "%"))
            )
        if undated:
            stmt = stmt.where(Task.due_at.is_(None))
        if date_from:
            stmt = stmt.where(Task.due_at >= date_from)
        if date_to:
            stmt = stmt.where(Task.due_at < date_to)
        if source and source != "manual":
            stmt = stmt.where(False)
        if batch and profile(db, user["id"]).data.get("generalBatch") != batch:
            stmt = stmt.where(False)
        if priority_filter:
            computed = case(
                (Task.due_at <= current, "critical"),
                (Task.due_at <= current + timedelta(hours=24), "critical"),
                (Task.due_at <= current + timedelta(days=3), "high"),
                (Task.due_at <= current + timedelta(days=7), "medium"),
                else_="low",
            )
            stmt = stmt.where(
                func.coalesce(Task.data["priorityOverride"].astext, computed) == priority_filter
            )
        rows, c = page(db, stmt, Task, limit, cursor)
        return {"items": [task_out(t, db, user["id"]) for t in rows], "nextCursor": c}


@app.post("/api/v1/tasks", status_code=201)
def add_task(body: TaskInput, user=User):
    with work(user) as db:
        d = task_data(body)
        if body.subject_id:
            owned(db, Subject, body.subject_id, user["id"])
        p = profile(db, user["id"])
        d["academicContext"] = {
            k: p.data.get(k)
            for k in ("institution", "programme", "department", "classYear", "currentSemester", "division")
        }
        d["manualFieldOverrides"] = {
            k: {"recordedAt": now().isoformat()}
            for k in {TaskInput.model_fields[name].alias for name in body.model_fields_set}
        }
        t = Task(
            user_id=uuid.UUID(user["id"]),
            title=d["title"],
            type=d["type"],
            subject_id=body.subject_id,
            due_at=datetime.fromisoformat(d["dueAt"]) if d["dueAt"] else None,
            data=d,
        )
        db.add(t)
        db.flush()
        t.status = effective_status(t, now())
        history(db, t, "created", d)
        return task_out(t, db, user["id"])


@app.get("/api/v1/tasks/{id}")
def get_task(id: uuid.UUID, user=User):
    with work(user) as db:
        return task_out(owned(db, Task, id, user["id"]), db, user["id"])


@app.patch("/api/v1/tasks/{id}")
def edit_task(id: uuid.UUID, body: TaskPatch, request: Request, user=User):
    with work(user) as db:
        cached, op = replay(db, request, user, body.model_dump(mode="json", exclude_unset=True))
        if cached is not None:
            return cached
        t = owned(db, Task, id, user["id"], True)
        revision(t, body.revision)
        changes = body.model_dump(
            mode="json", by_alias=True, exclude_unset=True, exclude={"revision", "status"}
        )
        merged = {
            k: v for k, v in t.data.items() if k in {field.alias for field in TaskInput.model_fields.values()}
        }
        # Changing controlling times recomputes cutoff, never retaining an obsolete derived value.
        if (
            any(k in changes for k in ("startsAt", "availabilityClosesAt", "dueDate", "timingMode"))
            and "dueAt" not in changes
        ):
            merged["dueAt"] = None
        if merged.get("dueDate") and "dueAt" not in changes:
            merged["dueAt"] = None
        d = task_data(TaskInput.model_validate({**merged, **changes}))
        if d["subjectId"]:
            owned(db, Subject, uuid.UUID(d["subjectId"]), user["id"])
        d["academicContext"] = t.data.get("academicContext", {})
        d["manualFieldOverrides"] = {
            **t.data.get("manualFieldOverrides", {}),
            **{k: {"recordedAt": now().isoformat()} for k in changes},
        }
        if "latestManualDecision" in t.data:
            d["latestManualDecision"] = t.data["latestManualDecision"]
        accepted_changes = {
            k: v
            for k, v in d.items()
            if k in {field.alias for field in TaskInput.model_fields.values()} and v != t.data.get(k)
        }
        prior_status = effective_status(t, now())
        t.title, t.type, t.data = d["title"], d["type"], d
        t.subject_id = uuid.UUID(d["subjectId"]) if d["subjectId"] else None
        t.due_at = datetime.fromisoformat(d["dueAt"]) if d["dueAt"] else None
        action = "edited"
        if body.status is not None:
            t.completed_at = now() if body.status == "completed" else None
            action = "completed" if body.status == "completed" else "reopened"
            t.data = {**d, "latestManualDecision": {"action": action, "recordedAt": now().isoformat()}}
        t.status = effective_status(t, now())
        t.revision += 1
        db.flush()
        if body.status is not None or t.status != prior_status:
            accepted_changes["status"] = t.status
        if body.status is not None:
            accepted_changes["completedAt"] = t.completed_at.isoformat() if t.completed_at else None
        history(db, t, action, accepted_changes)
        return finish(db, op, task_out(t, db, user["id"]))


@app.delete("/api/v1/tasks/{id}")
def delete_task(id: uuid.UUID, request: Request, revision_value: int = Query(alias="revision"), user=User):
    with work(user) as db:
        cached, op = replay(db, request, user, {"revision": revision_value})
        if cached is not None:
            return cached
        t = owned(db, Task, id, user["id"], True)
        revision(t, revision_value)
        db.delete(t)
        return finish(db, op, {"ok": True})


@app.get("/api/v1/tasks/{id}/history")
def task_history(id: uuid.UUID, limit: int = Query(50, ge=1, le=100), cursor: str | None = None, user=User):
    with work(user) as db:
        owned(db, Task, id, user["id"])
        rows, c = page(
            db,
            select(History).where(History.user_id == user["id"], History.task_id == id),
            History,
            limit,
            cursor,
        )
        return {
            "items": [
                {
                    "id": str(h.id),
                    "action": h.action,
                    "actor": "student",
                    "changes": h.changes,
                    "recordedAt": h.created_at.isoformat(),
                }
                for h in rows
            ],
            "nextCursor": c,
        }


@app.get("/api/v1/overview")
def overview(user=User):
    with work(user) as db:
        current = now()
        effective = case(
            (Task.completed_at.is_not(None), "completed"),
            (and_(Task.due_at <= current, Task.type == "test"), "missed"),
            (Task.due_at <= current, "overdue"),
            else_="due",
        )
        counts = {k: 0 for k in ("due", "completed", "overdue", "missed")}
        counts.update(
            dict(
                db.execute(
                    select(effective, func.count()).where(Task.user_id == user["id"]).group_by(effective)
                ).all()
            )
        )
        undated = db.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.user_id == user["id"], Task.completed_at.is_(None), Task.due_at.is_(None))
        )
        items = db.scalars(
            select(Task)
            .where(Task.user_id == user["id"], Task.completed_at.is_(None))
            .order_by(Task.due_at.asc().nulls_last(), Task.created_at.desc())
            .limit(8)
        )
        return {
            "counts": counts,
            "undated": undated,
            "tasks": [task_out(t, db, user["id"]) for t in items],
            "reviewCount": 0,
            "sync": sources_api.sync_summary(db, user["id"]),
        }


app.include_router(sources_api.router)
