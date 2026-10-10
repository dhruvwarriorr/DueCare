"""Timetable upload: read the document, draft weekly slots, then save the student's confirmed slots.

No slots are written before confirmation. Cloud uploads use temporary private storage;
extracted text and drafts are not stored.
confirmed slots go into the existing per-subject timetable with minimal import provenance.
"""

import hashlib
import json
import uuid
from datetime import time
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import Field, field_validator, model_validator
from sqlalchemy import select

from . import academic, timetable_draft, timetable_extract, timetable_storage
from .common import User, finish, replay, work
from .errors import ApiError
from .models import Slot, Subject, now
from .schemas import Input
from .views import profile

router = APIRouter(prefix="/api/v1/timetable-imports")
MAX_BODY = timetable_extract.MAX_TOTAL_BYTES + 512 * 1024


@router.post("/uploads")
def upload_urls(body: timetable_storage.UploadRequest, request: Request, user=User):
    _ready(user)
    return timetable_storage.sign(body, user, request.state.supabase_access_token)


@router.delete("/uploads")
def discard_uploads(body: timetable_storage.UploadedRequest, request: Request, user=User):
    timetable_storage.remove(body, user, request.state.supabase_access_token)
    return {"ok": True}


@router.post("/extract-uploaded")
def extract_uploaded(body: timetable_storage.UploadedRequest, request: Request, user=User):
    _ready(user)
    files = timetable_storage.download(body, user, request.state.supabase_access_token)
    return timetable_extract.extract(files)


def slot_data(item, p, s, origin=None):
    """Stored slot shape shared by the subject timetable editor and timetable imports."""
    data = {
        **item,
        "timezone": "Asia/Kolkata",
        "semesterContext": p.data.get("currentSemester"),
        "termContext": s.data.get("term"),
        "subjectRevision": s.revision + 1,
    }
    if origin:
        data["origin"] = origin
    return data


@router.post("/extract")
async def extract(request: Request, user=User):
    size = request.headers.get("content-length")
    if not size or not size.isdigit():
        raise ApiError(411, "LENGTH_REQUIRED", "Upload size is required")
    if int(size) > MAX_BODY:
        raise ApiError(413, "FILE_TOO_LARGE", "Uploads are limited to 20 MB in total")
    await run_in_threadpool(_ready, user)
    if not request.headers.get("content-type", "").startswith("multipart/form-data"):
        raise ApiError(415, "UNSUPPORTED_FILE", "Upload the timetable as a file")
    form = await request.form(max_files=timetable_extract.MAX_PICTURES + 1, max_fields=2)
    try:
        uploads = [f for f in form.getlist("files") if hasattr(f, "read")]
        files = []
        for n, f in enumerate(uploads, start=1):
            data = await f.read(timetable_extract.MAX_FILE_BYTES + 1)
            files.append(((f.filename or f"File {n}")[:120], data))
    finally:
        await form.close()  # Spooled temporary upload files are removed here.
    return await run_in_threadpool(timetable_extract.extract, files)


def _ready(user):
    # Ownership and account-deletion checks apply even though extraction reads no student data.
    with work(user):
        pass


class Header(Input):
    class_label: str | None = Field(None, max_length=120)
    academic_year: str | None = Field(None, max_length=20)
    semester: str | None = Field(None, max_length=20)


class PageInput(Input):
    id: str = Field(pattern=r"^p\d{1,2}$")
    layout: Literal["grid", "scheduler"] = "grid"
    header: Header = Field(default_factory=Header)


class CellInput(Input):
    id: str = Field(pattern=r"^c\d{1,4}$")
    page: str = Field(pattern=r"^p\d{1,2}$")
    weekday: int = Field(ge=1, le=7)
    start: time
    end: time
    lines: list[str] = Field(min_length=1, max_length=12)
    bbox: list[float] | None = Field(None, min_length=4, max_length=4)
    spans_days: bool = False
    narrow: bool = False
    clipped_top: bool = False
    clipped_bottom: bool = False
    unsure: bool = False

    @field_validator("lines")
    @classmethod
    def short_lines(cls, value):
        if any(len(line) > 120 for line in value):
            raise ValueError("Cell text is too long")
        return value

    @model_validator(mode="after")
    def interval(self):
        if self.end <= self.start:
            raise ValueError("End time must be after start time")
        if self.bbox and not all(0 <= v <= 1 for v in self.bbox):
            raise ValueError("Invalid source region")
        return self


class InterpretInput(Input):
    pages: list[PageInput] = Field(min_length=1, max_length=timetable_extract.MAX_PDF_PAGES)
    cells: list[CellInput] = Field(min_length=1, max_length=timetable_extract.MAX_CELLS)

    @model_validator(mode="after")
    def references(self):
        pages = {p.id for p in self.pages}
        if len(pages) != len(self.pages) or len({c.id for c in self.cells}) != len(self.cells):
            raise ValueError("Duplicate page or cell")
        if any(c.page not in pages for c in self.cells):
            raise ValueError("A cell refers to a missing page")
        return self


def subject_candidate(s):
    return {
        "id": str(s.id),
        "name": s.name,
        "kind": s.kind,
        "code": s.data.get("code"),
        "aliases": s.data.get("aliases") or [],
        "revision": s.revision,
    }


def profile_context(data):
    # Mail approvals, source-policy updates and appearance do not change batch applicability.
    return hashlib.sha256(json.dumps(academic.context(data), sort_keys=True).encode()).hexdigest()


@router.post("/interpret")
def interpret(body: InterpretInput, user=User):
    # Read the current context, then interpret outside the transaction: the AI call can take a
    # while and must not hold the student's row locks.
    with work(user) as db:
        p = profile(db, user["id"])
        profile_data, profile_revision = dict(p.data), p.revision
        subjects = [
            subject_candidate(s)
            for s in db.scalars(select(Subject).where(Subject.user_id == user["id"]).order_by(Subject.name))
        ]
    cells = [
        {
            **c.model_dump(by_alias=True, exclude={"start", "end"}),
            "start": c.start.strftime("%H:%M"),
            "end": c.end.strftime("%H:%M"),
        }
        for c in body.cells
    ]
    pages = [p.model_dump(by_alias=True) for p in body.pages]
    draft = timetable_draft.build(cells, pages, profile_data, subjects)
    return {
        **draft,
        "profileRevision": profile_revision,
        "profileContext": profile_context(profile_data),
        "subjects": subjects,
        "promptVersion": timetable_draft.PROMPT_VERSION,
    }


class ImportSlot(Input):
    subject_id: uuid.UUID
    weekday: int = Field(ge=1, le=7)
    start_time: time
    end_time: time
    location: str | None = Field(None, max_length=200)
    instructor: str | None = Field(None, max_length=200)

    @model_validator(mode="after")
    def interval(self):
        if self.start_time.tzinfo or self.end_time.tzinfo:
            raise ValueError("Weekly slots use local Asia/Kolkata times")
        if self.end_time <= self.start_time:
            raise ValueError("End time must be after start time")
        return self


class SubjectRevision(Input):
    id: uuid.UUID
    revision: int = Field(ge=1)


class ConfirmInput(Input):
    mode: Literal["add", "replace"] = "add"
    dry_run: bool = False
    profile_revision: int = Field(ge=1)
    profile_context: str | None = Field(None, pattern=r"^[a-f0-9]{64}$")
    subjects: list[SubjectRevision] = Field(min_length=1, max_length=100)
    slots: list[ImportSlot] = Field(min_length=1, max_length=300)
    method: Literal["pdf_text", "scheduler_ocr", "image_ocr"] = "pdf_text"
    acknowledge_overlaps: bool = False

    @model_validator(mode="after")
    def referenced(self):
        listed = [s.id for s in self.subjects]
        if len(set(listed)) != len(listed):
            raise ValueError("A subject is listed twice")
        if {s.subject_id for s in self.slots} != set(listed):
            raise ValueError("List exactly the subjects that receive slots")
        return self


def hm(value):
    return (value or "")[:5]


def key(item):
    return (item["weekday"], hm(item["startTime"]), hm(item["endTime"]))


def details(item):
    return ((item.get("location") or "").strip().lower(), (item.get("instructor") or "").strip().lower())


def brief(subject_id, item, names):
    return {
        "subjectId": str(subject_id),
        "subjectName": names.get(str(subject_id)),
        "weekday": item["weekday"],
        "startTime": hm(item["startTime"]),
        "endTime": hm(item["endTime"]),
        "location": item.get("location"),
        "instructor": item.get("instructor"),
    }


@router.post("/confirm")
def confirm(body: ConfirmInput, request: Request, user=User):
    with work(user) as db:
        op = None
        if not body.dry_run:
            cached, op = replay(db, request, user, body.model_dump(mode="json"))
            if cached is not None:
                return cached
        p = profile(db, user["id"])
        changed = (
            profile_context(p.data) != body.profile_context
            if body.profile_context is not None
            else p.revision != body.profile_revision
        )
        if changed:
            raise ApiError(
                409,
                "PROFILE_CHANGED",
                "Your academic details changed. Refresh the batch decisions before saving",
            )
        ids = sorted(s.id for s in body.subjects)
        # A consistent lock order keeps concurrent imports from deadlocking.
        locked = {
            s.id: s
            for s in db.scalars(
                select(Subject)
                .where(Subject.user_id == user["id"], Subject.id.in_(ids))
                .order_by(Subject.id)
                .with_for_update()
            )
        }
        if len(locked) != len(ids):
            raise ApiError(
                404, "SUBJECT_UNAVAILABLE", "A selected subject no longer exists. Refresh and link again"
            )
        for s in body.subjects:
            if locked[s.id].revision != s.revision:
                raise ApiError(
                    409,
                    "REVISION_CONFLICT",
                    f"{locked[s.id].name} changed while you were reviewing. Review the refreshed summary",
                )
        names = {str(s.id): s.name for s in db.scalars(select(Subject).where(Subject.user_id == user["id"]))}
        existing = {}
        others = []
        for slot in db.scalars(
            select(Slot).where(Slot.user_id == user["id"]).order_by(Slot.created_at, Slot.id)
        ):
            (existing.setdefault(slot.subject_id, []) if slot.subject_id in locked else others).append(slot)
        incoming, repeated = {}, 0
        for item in body.slots:
            data = item.model_dump(mode="json", by_alias=True, exclude={"subject_id"})
            bucket = incoming.setdefault(item.subject_id, {})
            if key(data) in bucket:
                repeated += 1
                continue
            bucket[key(data)] = data
        summary = {
            "added": [],
            "duplicates": [],
            "removed": [],
            "updated": [],
            "overlaps": [],
            "repeated": repeated,
        }
        plan = {}  # subject -> (adds, updates[(slot,data)], removals)
        for sid, items in incoming.items():
            current = {}
            for slot in existing.get(sid, []):
                current.setdefault(key(slot.data), slot)
            adds, updates, removals = [], [], []
            for k, data in items.items():
                slot = current.get(k)
                if slot is None:
                    adds.append(data)
                    summary["added"].append(brief(sid, data, names))
                elif body.mode == "replace" and details(slot.data) != details(data):
                    updates.append((slot, data))
                    summary["updated"].append(brief(sid, data, names))
                else:
                    summary["duplicates"].append(
                        {**brief(sid, data, names), "sameDetails": details(slot.data) == details(data)}
                    )
            if body.mode == "replace":
                matched = {id(current[k]) for k in items if k in current}
                for slot in existing.get(sid, []):
                    if id(slot) not in matched:
                        removals.append(slot)
                        summary["removed"].append({**brief(sid, slot.data, names), "id": str(slot.id)})
            plan[sid] = (adds, updates, removals)
        # Overlaps across the resulting week, reported for anything this import adds or changes.
        final = [(s.subject_id, s.data, False) for s in others]
        for sid, (adds, updates, removals) in plan.items():
            gone = {id(s) for s in removals} | {id(s) for s, _ in updates}
            final += [(sid, s.data, False) for s in existing.get(sid, []) if id(s) not in gone]
            final += [(sid, d, True) for d in adds] + [(sid, d, True) for _, d in updates]
        for i, (a_sid, a, a_new) in enumerate(final):
            for b_sid, b, b_new in final[i + 1 :]:
                if (a_new or b_new) and a["weekday"] == b["weekday"]:
                    if hm(a["startTime"]) < hm(b["endTime"]) and hm(b["startTime"]) < hm(a["endTime"]):
                        summary["overlaps"].append(
                            {"first": brief(a_sid, a, names), "second": brief(b_sid, b, names)}
                        )
        if body.dry_run:
            return {"dryRun": True, "summary": summary}
        if summary["overlaps"] and not body.acknowledge_overlaps:
            raise ApiError(409, "OVERLAPS_NEED_REVIEW", "Some classes overlap. Review them before confirming")
        origin = {"type": "timetable_import", "method": body.method, "importedAt": now().isoformat()}
        result = []
        for sid in ids:
            s = locked[sid]
            adds, updates, removals = plan[sid]
            if adds or updates or removals:
                for data in adds:
                    item = {**data, "validFrom": None, "validUntil": None}
                    db.add(
                        Slot(
                            subject_id=sid, user_id=uuid.UUID(user["id"]), data=slot_data(item, p, s, origin)
                        )
                    )
                for slot, data in updates:
                    kept = {k: slot.data.get(k) for k in ("validFrom", "validUntil")}
                    slot.data = slot_data({**data, **kept}, p, s, origin)
                for slot in removals:
                    db.delete(slot)
                s.revision += 1
            db.flush()
            result.append(
                {
                    "id": str(sid),
                    "revision": s.revision,
                    "slots": [
                        {"id": str(slot.id), **slot.data}
                        for slot in db.scalars(
                            select(Slot)
                            .where(Slot.user_id == user["id"], Slot.subject_id == sid)
                            .order_by(Slot.created_at, Slot.id)
                        )
                    ],
                }
            )
        return finish(db, op, {"dryRun": False, "summary": summary, "subjects": result})
