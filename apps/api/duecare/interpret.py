"""Academic interpretation and reconciliation of imported source records (Phase 3).

Decision order for each record: current sender block -> recognized template or bounded AI
extraction -> academic applicability against the profile -> subject resolution among the student's
own subjects -> ordered rules (new tasks only) -> reconciliation with existing tasks.

Reconciliation invariants (enforced here, independently of AI):
- Due/overdue notices, digests, countdowns, deadline passage and source edits never clear completion.
- Completion comes only from validated submission evidence on an enabled path, or the student.
- A newer explicit student reopen survives replay of older receipts.
- Manual field corrections win over sources; conflicts go to Needs attention.
- Older source events never roll back newer accepted values.
"""

import base64
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from . import academic, ai, google, lms, mail, rules, targeting
from .classroom_time import due_at
from .common import work
from .config import settings
from .domain import effective_status, task_data
from .errors import ApiError
from .models import (
    Connection,
    History,
    Profile,
    ReviewItem,
    Rule,
    Slot,
    SourceEvent,
    SourceRecord,
    Subject,
    SubjectMapping,
    Task,
    TaskEvidence,
    now,
)
from .schemas import TaskInput

VERSION = "phase3-interpret-1"
AI_PAUSE = timedelta(minutes=10)
ACADEMIC = re.compile(
    r"\b(assignments?|submi(t|ssion)|quiz(zes)?|tests?|exams?|examination|viva|oral|practical|ost|ese|ia[- ]?\d|"
    r"internal assessment|experiments?|exp\s?-?\d+|labs?|laboratory|tutorials?|deadline|due|marks|syllabus|"
    r"seating|write-?up|report|presentation|project|coursework|homework|module)\b",
    re.I,
)
TIMING_FIELDS = (
    "dueAt", "submissionOpensAt", "availabilityOpensAt", "availabilityClosesAt", "loginByAt", "reportingAt",
    "startsAt", "endsAt",
)  # fmt: skip
DETAIL_FIELDS = ("location", "assessmentLabel", "deliverableLabel", "durationMinutes")
KIND_ORDER = {
    "classroom_coursework": 0,
    "classroom_announcement": 1,
    "gmail_message": 2,
    "classroom_submission": 3,
}


@dataclass
class Cand:
    intent: str
    task_type: str | None = None
    title: str | None = None
    assessment_label: str | None = None
    deliverable_label: str | None = None
    subject_id: str | None = None
    subject_choices: list = field(default_factory=list)
    component_hint: str | None = None
    observed: dict = field(default_factory=dict)
    trusted: bool = False
    timing: dict = field(default_factory=dict)
    mode: str | None = None
    date_only: str | None = None
    window: tuple | None = None
    alternatives: list = field(default_factory=list)
    duration: int | None = None
    provenance: dict = field(default_factory=dict)
    location: str | None = None
    instructions: str | None = None
    group_work: bool = False
    identity_key: str | None = None
    match_task_id: str | None = None
    question: str | None = None
    excerpt: str | None = None
    links: list = field(default_factory=list)
    validation: dict | None = None
    occurred_at: datetime | None = None
    section: str = "authored"
    relates: bool = False
    method: str = "ai"
    source: str = "gmail"
    course_label: str | None = None
    kt_only: bool = False


@dataclass
class Prepared:
    record_id: uuid.UUID
    revision: int
    candidates: list = field(default_factory=list)
    ignore: str | None = None
    paused: str | None = None
    meta: dict = field(default_factory=dict)


def norm(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def tokens(text):
    return {
        t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t not in {"the", "a", "of", "and", "for"}
    }


def utc(value):
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(UTC).isoformat() if dt.tzinfo else None


def parse_dt(value):
    return datetime.fromisoformat(value) if value else None


def completion_paths():
    return {p.strip() for p in settings().auto_completion_paths.split(",") if p.strip()}


DEFAULT_LMS_SENDER = "lms-kjsse@somaiya.edu"
DEFAULT_LMS_HOST = "lms-kjsce.somaiya.edu"


def lms_hosts():
    return {DEFAULT_LMS_HOST} | {h.strip().lower() for h in settings().lms_hosts.split(",") if h.strip()}


def lms_senders():
    # The Somaiya LMS sender is always recognized; LMS_SENDERS can add others but not remove it.
    return {DEFAULT_LMS_SENDER} | {p.strip().lower() for p in settings().lms_senders.split(",") if p.strip()}


# --- Context -----------------------------------------------------------------------------------


def load_context(db, uid, record):
    profile = academic.profile_data((db.get(Profile, uuid.UUID(str(uid))) or Profile(data={})).data)
    subjects = [
        {
            "id": str(s.id),
            "name": s.name,
            "kind": s.kind,
            "code": s.data.get("code"),
            "aliases": s.data.get("aliases", []),
            "term": s.data.get("term"),
            "classCode": s.data.get("classCode"),
            "lmsCourseLabels": s.data.get("lmsCourseLabels", []),
        }
        for s in db.scalars(select(Subject).where(Subject.user_id == uid).order_by(Subject.created_at))
    ]
    slots = [
        {"id": str(s.id), "subjectId": str(s.subject_id), **s.data}
        for s in db.scalars(select(Slot).where(Slot.user_id == uid))
    ]
    mapped = []
    if record.external_course_id:
        mapped = [
            str(m.subject_id)
            for m in db.scalars(
                select(SubjectMapping).where(
                    SubjectMapping.connection_id == record.connection_id,
                    SubjectMapping.external_course_id == record.external_course_id,
                )
            )
        ]
    tasks = [
        {
            "id": str(t.id),
            "title": t.title,
            "type": t.type,
            "subjectId": str(t.subject_id) if t.subject_id else None,
            "assessmentLabel": t.data.get("assessmentLabel"),
            "deliverableLabel": t.data.get("deliverableLabel"),
            "dueAt": t.due_at.isoformat() if t.due_at else None,
            "completed": bool(t.completed_at),
        }
        for t in db.scalars(
            select(Task)
            .where(Task.user_id == uid, Task.data["mergedInto"].astext.is_(None))
            .order_by(Task.updated_at.desc())
            .limit(60)
        )
    ]
    rule_rows = [
        {"id": str(r.id), "name": r.name, "enabled": r.enabled, "data": r.data}
        for r in db.scalars(
            select(Rule).where(Rule.user_id == uid, Rule.enabled.is_(True)).order_by(Rule.position)
        )
    ]
    return {
        "profile": profile,
        "subjects": subjects,
        "slots": slots,
        "mapped": mapped,
        "tasks": tasks,
        "rules": rule_rows,
    }


def lms_subjects(ctx, label):
    """Subjects matching an LMS course label. Only a student-confirmed label is decisive; otherwise every
    subject sharing the course's base name is a choice, because a course name alone does not settle
    theory versus lab versus tutorial."""
    if not label:
        return []
    confirmed = [s["id"] for s in ctx["subjects"] if norm(label) in {norm(x) for x in s["lmsCourseLabels"]}]
    if confirmed:
        return confirmed
    name = norm(lms.course_name(label))
    short = norm((targeting.parse_course_label(label) or {}).get("course"))
    keys = {norm(label), name, short} - {""}
    found = []
    for s in ctx["subjects"]:
        known = {norm(a) for a in s["aliases"] + [s["code"] or "", s["name"]]} - {""}
        if known & keys or (name and norm(s["name"]).startswith(name)):
            found.append(s["id"])
    return found


def subject_kind(ctx, subject_id):
    return next((s["kind"] for s in ctx["subjects"] if s["id"] == subject_id), None)


# --- Preparation (network calls happen here, outside database transactions) --------------------


def next_record(uid, connection_id):
    with work({"id": uid}) as db:
        order = func.coalesce(SourceRecord.sent_at, SourceRecord.published_at, SourceRecord.received_at)
        rows = db.execute(
            select(SourceRecord.id, SourceRecord.kind, SourceRecord.title)
            .where(
                SourceRecord.connection_id == connection_id,
                SourceRecord.processing_state == "awaiting_interpretation",
                (SourceRecord.data["aiPausedUntil"].astext.is_(None))
                | (SourceRecord.data["aiPausedUntil"].astext < now().isoformat()),
            )
            .order_by(order.asc().nulls_first(), SourceRecord.id)
            .limit(200)
        ).all()
    if not rows:
        return None
    # Announcements and coursework before submissions; receipts after the notices they confirm.
    receipt = lambda r: (r.title or "").lower().startswith("assignment submission confirmation")  # noqa: E731
    return min(rows, key=lambda r: KIND_ORDER.get(r.kind, 9) + (2 if receipt(r) else 0))[0]


def prepare(uid, record_id, token, account_email):
    with work({"id": uid}) as db:
        record = db.get(SourceRecord, record_id)
        ctx = load_context(db, uid, record)
        snapshot = {
            "id": record.id,
            "revision": record.revision,
            "kind": record.kind,
            "provider_id": record.provider_id,
            "course": record.external_course_id,
            "data": dict(record.data),
            "title": record.title,
            "published": record.published_at or record.sent_at,
        }
    prepared = Prepared(record_id=record_id, revision=snapshot["revision"])
    try:
        if snapshot["kind"] == "gmail_message":
            gmail_candidates(prepared, snapshot, ctx, token, account_email)
        elif snapshot["kind"] == "classroom_submission":
            submission_candidates(prepared, snapshot)
        else:
            classroom_candidates(prepared, snapshot, ctx, token)
    except google.SourceError as exc:
        if exc.kind != "not_found":
            raise
        prepared.ignore = "source_unavailable"
    except ai.AIUnavailable as exc:
        prepared.paused = str(exc)
    return prepared, ctx


def ai_payload(ctx, source, sections, allowed_subjects=None):
    subjects = [s for s in ctx["subjects"] if not allowed_subjects or s["id"] in allowed_subjects]
    p = ctx["profile"]
    return {
        "now": now().isoformat(),
        "student": academic.context(p),
        "note": "The student's single general batch applies to every subject.",
        "subjects": subjects,
        "weeklySlots": [
            s for s in ctx["slots"] if not allowed_subjects or s["subjectId"] in allowed_subjects
        ],
        "candidateTasks": ctx["tasks"][:40],
        "source": source,
        "sections": sections,
    }


def gmail_candidates(prepared, snap, ctx, token, account_email):
    gid = snap["provider_id"].split(":", 2)[2]
    raw = google.provider.gmail_raw(token, gid)["raw"]
    decoded = mail.decode(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    links = [link["reference"] for link in decoded.links]
    occurred = decoded.sent_at
    addressed = account_email in decoded.recipients_include
    forwarded = any(s.kind == "forwarded" for s in decoded.sections) or bool(
        re.match(r"^(fwd?|fw):", decoded.subject.strip(), re.I)
    )
    from_lms = decoded.sender_email in lms_senders()
    template, found = lms.parse(decoded.subject, decoded.authored_text, links) if from_lms else (None, [])
    prepared.meta = {"method": template or "ai", "sender": decoded.sender_email}
    if template:
        for c in found:
            course = lms.course_targeting(c.course_label)
            cand = Cand(
                intent=c.intent,
                task_type=c.task_type,
                title=c.title,
                identity_key=c.identity_key,
                observed=targeting.merge(course),
                # A personal LMS notification for an enrolled course establishes course membership.
                trusted=addressed,
                timing=dict(c.timing),
                duration=c.duration_minutes,
                provenance={
                    k: {**v, "sourceTime": occurred.isoformat() if occurred else None}
                    for k, v in c.provenance.items()
                },
                subject_choices=lms_subjects(ctx, c.course_label),
                links=[link for link in links if "/mod/" in link][:5],
                occurred_at=occurred,
                method="lms_" + template,
                excerpt=(f"{c.course_label} · {c.title}" if c.course_label else c.title)[:500],
            )
            cand.course_label = c.course_label
            if c.intent == "submission":
                auth_obs = decoded.authentication or {}
                cand.validation = {
                    "template": "assignment_receipt",
                    "sender": decoded.sender_email in lms_senders(),
                    "authenticated": auth_obs.get("dkim") == "pass"
                    and auth_obs.get("dmarc") == "pass"
                    and auth_obs.get("headerFrom") == decoded.sender_email.rsplit("@", 1)[1],
                    "addressedToAccount": addressed,
                    "notForwarded": not forwarded,
                    "activityLink": bool(c.identity_key) and c.identity_key.split(":")[1] in lms_hosts(),
                }
            prepared.candidates.append(cand)
        return
    text = decoded.subject + "\n" + decoded.authored_text
    if not ACADEMIC.search(text):
        prepared.ignore = "no_academic_signal"
        return
    label = re.match(r"^(\S+_(?:ODD|EVEN)_\d{2}-\d{2})\s*:", decoded.subject)
    sections = [
        {
            "id": "authored" if s.kind == "authored" else f"quoted-{i}",
            "kind": s.kind,
            "attribution": s.attribution,
            "text": s.text[: 12000 if s.kind == "authored" else 4000],
        }
        for i, s in enumerate(decoded.sections)
        if s.kind in ("authored", "quoted", "forwarded")
    ][:5]
    source = {
        "kind": "email",
        "sender": decoded.sender_email,
        "sentAt": occurred.isoformat() if occurred else None,
        "subject": decoded.subject,
        "courseLabel": label.group(1) if label else None,
        "attachments": [a["title"] for a in decoded.attachments][:10],
        "forwarded": forwarded,
    }
    extraction, meta = ai.extract(ai_payload(ctx, source, sections))
    prepared.meta.update(meta)
    course = targeting.merge(lms.course_targeting(label.group(1))) if label else {}
    choices = lms_subjects(ctx, label.group(1)) if label else []
    for i, item in enumerate(extraction.items):
        cand = from_item(item, ctx, base_choices=choices, allowed=None, occurred=occurred, source="gmail")
        cand.observed = targeting.merge(
            course.get("course"), {**item.targeting.model_dump(), "scope": "activity"}
        )
        cand.trusted = bool(label) and addressed and from_lms
        cand.kt_only = cand.kt_only or kt_text(decoded.subject)
        cand.identity_key = f"{snap['provider_id']}:{i}"
        cand.links = links[:5]
        if item.intent == "submission":
            # Free-form receipts are never a validated template: they require student review.
            cand.validation = {
                "template": None,
                "addressedToAccount": addressed,
                "notForwarded": not forwarded,
            }
        prepared.candidates.append(cand)


def classroom_candidates(prepared, snap, ctx, token):
    parts = snap["provider_id"].split(":")
    course_id, resource, item_id = parts[2], parts[3], parts[4]
    getter = (
        google.provider.classroom_coursework_item
        if resource == "coursework"
        else google.provider.classroom_announcement_item
    )
    item = getter(token, course_id, item_id)
    data = snap["data"]
    source = {
        "kind": "classroom_" + resource,
        "publishedAt": item.get("creationTime"),
        "updatedAt": item.get("updateTime"),
        "title": item.get("title"),
        "workType": item.get("workType"),
        "structuredDueAt": iso_or_none(due_at(item)),
        "materials": [m.get("title") for m in (item.get("materials") or []) if isinstance(m, dict)][:10],
    }
    text = (item.get("description") or item.get("text") or "")[:12000]
    extraction, meta = ai.extract(ai_payload(ctx, source, [{"id": "authored", "text": text}], ctx["mapped"]))
    prepared.meta = {"method": "ai", **meta}
    occurred = parse_dt(snap["published"].isoformat()) if snap["published"] else None
    for i, it in enumerate(extraction.items):
        cand = from_item(
            it,
            ctx,
            base_choices=ctx["mapped"],
            allowed=set(ctx["mapped"]),
            occurred=occurred,
            source="classroom",
        )
        cand.observed = targeting.merge({**it.targeting.model_dump(), "scope": "activity"})
        cand.trusted = True  # The student explicitly linked this course to their subject(s).
        cand.kt_only = cand.kt_only or kt_text(item.get("title"))
        cand.identity_key = (
            snap["provider_id"] if (resource == "coursework" and i == 0) else f"{snap['provider_id']}:{i}"
        )
        cand.links = [data.get("alternateLink")] if data.get("alternateLink") else []
        structured_due = due_at(item)
        if resource == "coursework" and i == 0 and structured_due and cand.task_type == "assignment":
            # Structured Classroom deadlines (UTC) are authoritative over extracted wording.
            cand.timing["dueAt"] = structured_due.isoformat()
            cand.mode, cand.date_only = "deadline_only", None
            cand.provenance["dueAt"] = {
                "basis": "source-exact",
                "timezone": "UTC",
                "phrase": "Classroom due date",
            }
        if cand.intent == "submission":
            cand.intent = "supporting"  # Only the student's own submission state proves Classroom turn-in.
        prepared.candidates.append(cand)


def iso_or_none(value):
    return value.isoformat() if value else None


def submission_candidates(prepared, snap):
    data = snap["data"]
    parts = snap["provider_id"].split(":")
    work_key = ":".join(parts[:3] + ["coursework", data.get("courseWorkId") or ""])
    history = data.get("stateHistory") or []
    state = data.get("state")

    def last(name):
        times = [h["at"] for h in history if h.get("state") == name and h.get("at")]
        return parse_dt(utc(max(times))) if times else None

    turned = last("TURNED_IN")
    prepared.meta = {"method": "classroom_submission"}
    if state == "TURNED_IN" or (state == "RETURNED" and turned):
        intent, at = "submission", turned or parse_dt(utc(data.get("updateTime")))
    elif state == "RECLAIMED_BY_STUDENT":
        intent, at = "unsubmission", last("RECLAIMED_BY_STUDENT")
    elif state == "RETURNED":
        intent, at = "returned_ambiguous", None
    else:
        prepared.ignore = "not_submitted"  # NEW/CREATED: attaching files does not prove turn-in.
        return
    prepared.candidates.append(
        Cand(
            intent=intent,
            identity_key=work_key,
            occurred_at=at,
            trusted=True,
            method="classroom_submission",
            source="classroom",
            validation={"ownSubmission": True, "state": state, "stateTime": at.isoformat() if at else None},
            links=[data.get("alternateLink")] if data.get("alternateLink") else [],
        )
    )


# KT (ATKT) notices concern only students re-taking a failed subject. The extraction flag decides;
# these wordings also mark an item when the model misses them, unless regular students are included.
KT_ONLY = re.compile(
    r"\b(?:a\.?\s?t\.?\s?k\.?\s?t\b|kt\s+(?:exams?|examinations?|students?|subjects?|forms?|results?|papers?"
    r"|fees?|re-?exams?|re-?examinations?|registrations?)|(?:re-?exam(?:ination)?s?|supplementary)\s+for\s+kt\b"
    r"|backlog\s+(?:exams?|examinations?|students?|subjects?))",
    re.I,
)
REGULAR = re.compile(r"\bregular\b", re.I)


def kt_text(*texts):
    text = " ".join(t for t in texts if t)
    return bool(KT_ONLY.search(text)) and not REGULAR.search(text)


def from_item(item, ctx, base_choices, allowed, occurred, source):
    owned = {s["id"] for s in ctx["subjects"]}
    subject = (
        item.subjectId if item.subjectId in owned and (not allowed or item.subjectId in allowed) else None
    )
    task_ids = {t["id"] for t in ctx["tasks"]}
    t = item.timing
    timing, provenance, question = {}, {}, item.question
    for name in TIMING_FIELDS:
        value = getattr(t, name)
        if value:
            parsed = utc(value)
            if parsed:
                timing[name] = parsed
                basis = "explicitly-derived" if name in t.derived else "source-exact"
                provenance[name] = {
                    "basis": basis,
                    "timezone": "Asia/Kolkata",
                    "phrase": (t.phrases.get(name) or "")[:200],
                    "sourceTime": occurred.isoformat() if occurred else None,
                }
            else:
                question = question or "The source time could not be read precisely. Which time applies?"
    slot = (
        next((s for s in ctx["slots"] if s["id"] == t.timetableSlotId), None) if t.timetableSlotId else None
    )
    for name in t.derived:
        if name in timing and t.timetableSlotId:
            if not slot or slot["subjectId"] != subject:
                # Timetable-derived times need a valid slot of the established subject.
                timing.pop(name, None)
                question = question or "Which session time applies to this work?"
            else:
                provenance[name].update(
                    basis="timetable-derived", slotId=slot["id"], subjectRevision=slot.get("subjectRevision")
                )
    date_only = t.dateOnly if t.dateOnly and re.match(r"^\d{4}-\d{2}-\d{2}$", t.dateOnly) else None
    window = (t.dateWindowStart, t.dateWindowEnd) if t.dateWindowStart and t.dateWindowEnd else None
    return Cand(
        intent=item.intent,
        task_type=item.taskType,
        title=(item.title or "").strip() or None,
        assessment_label=item.assessmentLabel,
        deliverable_label=item.deliverableLabel,
        subject_id=subject,
        subject_choices=list(base_choices) if not subject else [subject],
        component_hint=item.componentHint,
        timing=timing,
        mode=t.mode,
        date_only=date_only,
        window=window,
        alternatives=t.alternatives,
        duration=t.durationMinutes,
        provenance=provenance,
        location=item.location,
        instructions=item.instructions,
        group_work=item.groupWork,
        match_task_id=item.matchTaskId if item.matchTaskId in task_ids else None,
        question=question,
        excerpt=(item.evidence or "")[:500] or None,
        occurred_at=occurred,
        section=item.section,
        relates=item.relatesToAssessment,
        source=source,
        kt_only=item.ktOnly or kt_text(item.title, item.assessmentLabel),
    )


# --- Commit ------------------------------------------------------------------------------------


def history(db, task, action, changes, event=None):
    from .activity import task_changed

    task_changed(db, task, action, changes, event)
    db.add(
        History(
            user_id=task.user_id,
            task_id=task.id,
            action=action,
            changes={
                **changes,
                "_actor": "source",
                "_eventId": str(event.id) if event else None,
                "_sourceTime": event.occurred_at.isoformat() if event and event.occurred_at else None,
            },
        )
    )


def link(db, task, event, method):
    exists = db.scalar(
        select(TaskEvidence).where(TaskEvidence.task_id == task.id, TaskEvidence.event_id == event.id)
    )
    if not exists:
        db.add(
            TaskEvidence(
                user_id=task.user_id, task_id=task.id, event_id=event.id, method=method, state="active"
            )
        )
    event.task_id = task.id


def task_by_identity(db, uid, key):
    if not key:
        return None
    return db.scalar(
        select(Task)
        .join(TaskEvidence, TaskEvidence.task_id == Task.id)
        .join(SourceEvent, SourceEvent.id == TaskEvidence.event_id)
        .where(
            Task.user_id == uid,
            TaskEvidence.state == "active",
            SourceEvent.identity_key == key,
            Task.data["mergedInto"].astext.is_(None),
        )
        .order_by(Task.created_at)
        .limit(1)
        .with_for_update(of=Task)
    )


def similar_task(db, uid, cand, subject_id):
    """Similarity never merges; it only asks the student (different kinds/labels stay separate)."""
    if not cand.title:
        return None
    mine = tokens(cand.title)
    for t in db.scalars(
        select(Task).where(
            Task.user_id == uid,
            Task.type == cand.task_type,
            Task.subject_id == (uuid.UUID(subject_id) if subject_id else None),
            Task.data["mergedInto"].astext.is_(None),
        )
    ):
        theirs = tokens(t.title)
        label_same = cand.assessment_label and norm(cand.assessment_label) == norm(
            t.data.get("assessmentLabel")
        )
        if label_same or (mine and len(mine & theirs) / len(mine | theirs) >= 0.6):
            return t
    return None


def open_review(db, uid, record, event, issue, question, data, task=None, identity=None):
    if identity:
        existing = db.scalar(
            select(ReviewItem).where(
                ReviewItem.user_id == uid,
                ReviewItem.status == "open",
                ReviewItem.issue_type == issue,
                ReviewItem.data["identityKey"].astext == identity,
            )
        )
        if existing:
            # Repeated notices for one unresolved activity add evidence to the same question.
            existing.data = {**existing.data, "eventIds": [*existing.data.get("eventIds", []), str(event.id)]}
            return existing
    item = ReviewItem(
        user_id=record.user_id,
        issue_type=issue,
        status="open",
        task_id=task.id if task else None,
        source_record_id=record.id,
        event_id=event.id,
        sender_email=record.sender_email,
        question=question[:500],
        data={**data, "identityKey": identity, "eventIds": [str(event.id)]},
    )
    db.add(item)
    db.flush()
    from .activity import notify

    notify(db, uid, "review", "review", item.id, "An imported item needs your review.", f"review:{item.id}")
    return item


def proposal(cand, subject_id):
    out = {
        "title": (cand.title or "Untitled work")[:300],
        "type": cand.task_type,
        "subjectId": subject_id,
        "assessmentLabel": cand.assessment_label,
        "deliverableLabel": cand.deliverable_label,
        "location": cand.location,
        "instructions": (cand.instructions or "")[:4000],
        "durationMinutes": cand.duration,
        **cand.timing,
    }
    if cand.mode:
        out["timingMode"] = cand.mode
    if cand.window:
        out["dateWindowStart"], out["dateWindowEnd"] = cand.window
    if cand.date_only:
        out["dueDate"] = cand.date_only
    return {k: v for k, v in out.items() if v not in (None, "")}


def task_input(fields):
    """Validate a source proposal through the same contract as manual tasks."""
    allowed = {f.alias for f in TaskInput.model_fields.values()}
    clean = {k: v for k, v in fields.items() if k in allowed}
    if clean.get("type") == "test" and clean.get("startsAt") and not clean.get("timingMode"):
        clean["timingMode"] = "fixed_session"
    if clean.get("type") == "test" and clean.get("availabilityClosesAt") and not clean.get("startsAt"):
        clean["timingMode"] = "attempt_window"
    if clean.get("timingMode") == "fixed_session" and not clean.get("startsAt"):
        clean.pop("timingMode")
    if clean.get("timingMode") == "attempt_window" and not clean.get("availabilityClosesAt"):
        clean.pop("timingMode")
    if clean.get("timingMode") in ("fixed_session", "attempt_window"):
        clean.pop("dueAt", None)
    if clean.get("dueAt") and not clean.get("timingMode"):
        clean["timingMode"] = "deadline_only"
    if clean.get("timingMode") == "unresolved":
        clean.pop("dueAt", None)
    return task_data(TaskInput.model_validate(clean))


def unresolved(cand):
    """Timing the source does not settle: never invent a slot, date, or start time."""
    if cand.question:
        return cand.question
    if cand.window:
        return "Exact date has not been announced. Which date in this window applies to you?"
    if cand.alternatives:
        return "The notice gives tentative alternatives. Which date applies?"
    if cand.task_type == "test" and cand.date_only:
        return "Exact start time has not been announced."
    if cand.mode == "unresolved":
        return "The source does not settle the timing for this work."
    return None


def create_task(db, uid, ctx, record, event, cand, subject_id, method, fields=None):
    d = task_input(fields or proposal(cand, subject_id))
    provenance = {**d.get("timingProvenance", {})}
    for name, prov in cand.provenance.items():
        if name in provenance or d.get(name):
            provenance[name] = {**prov, "evidenceRef": str(event.id)}
    d["timingProvenance"] = provenance
    p = ctx["profile"]
    d["academicContext"] = academic.context(p)
    d["manualFieldOverrides"] = {}
    d["sources"] = [cand.source]
    d["sourceLinks"] = cand.links
    d["observedTargeting"] = cand.observed
    d["groupWork"] = cand.group_work
    task = Task(
        user_id=record.user_id,
        title=d["title"],
        type=d["type"],
        subject_id=uuid.UUID(d["subjectId"]) if d.get("subjectId") else None,
        due_at=parse_dt(d["dueAt"]) if d.get("dueAt") else None,
        data=d,
    )
    db.add(task)
    db.flush()
    task.status = effective_status(task, now())
    link(db, task, event, method)
    history(
        db,
        task,
        "imported",
        {k: d.get(k) for k in ("title", "type", "subjectId", "dueAt", "timingMode") if d.get(k)},
        event,
    )
    return task


def update_task(db, task, cand, event, explicit, method):
    """Reconcile role-specific fields. Never touches completion."""
    changes, conflicts = {}, {}
    incoming = {**cand.timing}
    for name, value in (("location", cand.location), ("assessmentLabel", cand.assessment_label),
                        ("deliverableLabel", cand.deliverable_label), ("durationMinutes", cand.duration)):  # fmt: skip
        if value not in (None, ""):
            incoming[name] = value
    mode = task.data.get("timingMode")
    if mode == "fixed_session" and "availabilityClosesAt" in incoming:
        # A quiz closing notice does not overwrite an established classroom session.
        incoming.pop("dueAt", None)
    overrides = task.data.get("manualFieldOverrides", {})
    provenance = task.data.get("timingProvenance", {})
    for name, value in incoming.items():
        current = task.data.get(name)
        if current == value:
            continue
        if name in overrides or (name in ("startsAt", "availabilityClosesAt") and "dueAt" in overrides):
            conflicts[name] = {"current": current, "proposed": value, "reason": "student correction"}
            continue
        previous = provenance.get(name, {}).get("sourceTime")
        if previous and cand.occurred_at and cand.occurred_at.isoformat() < previous:
            continue  # An older notice imported later cannot roll back a newer value.
        if current not in (None, "") and not explicit:
            conflicts[name] = {"current": current, "proposed": value, "reason": "sources disagree"}
            continue
        changes[name] = value
    if changes:
        allowed = {f.alias for f in TaskInput.model_fields.values()}
        merged = {k: v for k, v in task.data.items() if k in allowed}
        if any(k in changes for k in ("startsAt", "availabilityClosesAt")) and "dueAt" not in changes:
            merged["dueAt"] = None
        merged.update(changes)
        merged.pop("dueDate", None) if "dueAt" in changes else None
        try:
            d = task_input(merged)
        except ApiError:
            conflicts.update(
                {
                    k: {"current": task.data.get(k), "proposed": v, "reason": "inconsistent timing"}
                    for k, v in changes.items()
                }
            )
            changes = {}
        else:
            prov = {**provenance}
            for name in changes:
                prov[name] = {
                    **cand.provenance.get(name, {"basis": "source-exact"}),
                    "evidenceRef": str(event.id),
                }
            keep = {k: task.data[k] for k in task.data if k not in allowed}
            task.data = {
                **keep,
                **d,
                "timingProvenance": prov,
                "sources": sorted({*task.data.get("sources", []), cand.source}),
            }
            task.due_at = parse_dt(d["dueAt"]) if d.get("dueAt") else None
            task.status = effective_status(task, now())
            task.revision += 1
            history(db, task, "source_update", changes, event)
    link(db, task, event, method)
    return changes, conflicts


def complete_task(db, task, event, origin):
    """Atomic completion under the task row lock; survives every later reminder."""
    if task.completed_at:
        history(
            db, task, "evidence_added", {"reason": "additional submission evidence", "origin": origin}, event
        )
        return "already_completed"
    decision = task.data.get("latestManualDecision") or {}
    if (
        decision.get("action") == "reopened"
        and event.occurred_at
        and decision.get("recordedAt", "") > event.occurred_at.isoformat()
    ):
        history(db, task, "evidence_added", {"reason": "older than the student's reopen decision"}, event)
        return "manual_decision_preserved"
    task.completed_at = now()
    task.data = {
        **task.data,
        "completion": {
            "origin": origin,
            "eventId": str(event.id),
            "sourceTime": event.occurred_at.isoformat() if event.occurred_at else None,
            "basis": "source occurrence time (not a verified upload time)",
            "recordedAt": now().isoformat(),
        },
    }
    task.status = "completed"
    task.revision += 1
    history(db, task, "completed", {"status": "completed", "origin": origin}, event)
    return "completed"


def reopen_task(db, task, event):
    completion = task.data.get("completion") or {}
    decision = task.data.get("latestManualDecision") or {}
    stamp = event.occurred_at.isoformat() if event.occurred_at else ""
    newest = max(
        completion.get("sourceTime") or "",
        decision.get("recordedAt") or "" if decision.get("action") == "completed" else "",
    )
    if not task.completed_at or not stamp or stamp <= newest:
        history(db, task, "evidence_added", {"reason": "unsubmission not newer than completion"}, event)
        return "preserved"
    task.completed_at = None
    task.data = {**task.data, "completion": None}
    task.status = effective_status(task, now())
    task.revision += 1
    history(db, task, "reopened", {"status": task.status, "reason": "newer validated unsubmission"}, event)
    return "reopened"


def apply_candidate(db, uid, ctx, record, index, cand, run):
    from .privacy import suppressed

    conn = db.get(Connection, record.connection_id)
    if suppressed(db, conn, cand.identity_key) or suppressed(db, conn, record.provider_id):
        return "ignored_deleted"
    key = f"{record.revision}:{run}:{index}"
    if db.scalar(
        select(SourceEvent.id).where(SourceEvent.source_record_id == record.id, SourceEvent.event_key == key)
    ):
        return "replayed"
    applied = (
        "created",
        "updated",
        "evidence_recorded",
        "accepted",
        "linked",
        "completed",
        "already_completed",
    )
    if cand.identity_key and db.scalar(
        select(SourceEvent.id).where(
            SourceEvent.source_record_id == record.id,
            SourceEvent.event_key.like(f"{record.revision}:%:{index}"),
            SourceEvent.identity_key == cand.identity_key,
            SourceEvent.outcome.in_(applied),
            SourceEvent.task_id.is_not(None),
        )
    ):
        # Reprocessing an unchanged source revision already applied to a task adds no duplicate evidence.
        return "replayed"
    event_type = cand.intent if cand.intent in ("new_work", "revision", "due_notice", "supporting", "submission",
                                                "unsubmission", "withdrawal") else "unknown"  # fmt: skip
    event = SourceEvent(
        user_id=record.user_id,
        source_record_id=record.id,
        event_key=key,
        event_type=event_type,
        identity_key=cand.identity_key,
        occurred_at=cand.occurred_at,
        outcome="pending",
        processing_version=VERSION,
        data={
            "method": cand.method,
            "title": cand.title,
            "taskType": cand.task_type,
            "assessmentLabel": cand.assessment_label,
            "deliverableLabel": cand.deliverable_label,
            "section": cand.section,
            "observedTargeting": cand.observed,
            "timing": cand.timing,
            "provenance": cand.provenance,
            "validation": cand.validation,
            "excerpt": cand.excerpt,
            "links": cand.links,
        },
    )
    db.add(event)
    db.flush()

    def done(outcome):
        event.outcome = outcome
        return outcome

    if event_type == "unknown" and cand.intent != "returned_ambiguous":
        return done("ignored_unrelated")
    task = task_by_identity(db, uid, cand.identity_key)
    if not task and cand.match_task_id:
        task = db.scalar(
            select(Task)
            .where(Task.id == uuid.UUID(cand.match_task_id), Task.user_id == uid)
            .with_for_update()
        )
    if cand.kt_only and ctx["profile"].get("ignoreKtNotices") and not task:
        # The student chose to ignore KT notices. Work already tracked keeps receiving updates.
        return done("ignored_kt")
    subject_id = cand.subject_id or (str(task.subject_id) if task and task.subject_id else None)
    if not subject_id and cand.subject_choices:
        choices = cand.subject_choices
        if cand.component_hint:
            choices = [c for c in choices if subject_kind(ctx, c) == cand.component_hint] or choices
        subject_id = choices[0] if len(choices) == 1 else None
    kind = subject_kind(ctx, subject_id)
    outcome, reason, question = targeting.evaluate(
        cand.observed, ctx["profile"], subject_kind=kind, trusted=cand.trusted or bool(task)
    )
    event.data = {**event.data, "targeting": {"outcome": outcome, "reason": reason}}
    if outcome == "mismatch":
        return done("ignored_mismatch")  # No task, review, completion change, or activity.
    context = {
        "observed": cand.observed,
        "student": academic.context(ctx["profile"]),
        "excerpt": cand.excerpt,
        "sourceTitle": record.title,
        "sourceKind": record.kind,
        "links": cand.links,
        "method": cand.method,
        "courseLabel": getattr(cand, "course_label", None),
    }

    if cand.intent in ("submission", "unsubmission", "returned_ambiguous"):
        if not task:
            return done("unmatched_receipt")  # Reconsidered only during explicit reprocessing.
        if outcome != "applicable":
            open_review(
                db,
                uid,
                record,
                event,
                "confirm_applicability",
                question or "Does this evidence belong to you?",
                context,
                task,
                cand.identity_key,
            )
            return done("review")
        link(db, task, event, cand.method)
        if cand.intent == "returned_ambiguous":
            open_review(
                db,
                uid,
                record,
                event,
                "returned_ambiguous",
                "Classroom returned this work without a turn-in record. Is it complete?",
                context,
                task,
            )
            return done("review")
        path = "classroom_turned_in" if cand.method == "classroom_submission" else "lms_assignment_receipt"
        valid = (
            bool(cand.validation)
            and all(v for k, v in cand.validation.items() if k not in ("state", "stateTime", "template"))
            and (
                cand.method == "classroom_submission"
                or cand.validation.get("template") == "assignment_receipt"
            )
        )
        if cand.intent == "unsubmission":
            if valid and path in completion_paths():
                return done(reopen_task(db, task, event))
            if task.completed_at:
                open_review(
                    db,
                    uid,
                    record,
                    event,
                    "unsubmission",
                    "Classroom shows this work was unsubmitted. Reopen it?",
                    context,
                    task,
                )
                return done("review")
            return done("evidence_recorded")
        if not valid:
            open_review(
                db,
                uid,
                record,
                event,
                "receipt_unverified",
                "This submission evidence could not be verified. Mark the task completed?",
                {**context, "validation": cand.validation},
                task,
            )
            return done("review")
        if path in completion_paths():
            return done(complete_task(db, task, event, path))
        if task.completed_at:
            history(db, task, "evidence_added", {"reason": "submission evidence for completed work"}, event)
            return done("evidence_recorded")
        open_review(
            db,
            uid,
            record,
            event,
            "confirm_completion",
            "A submission confirmation was found. Mark this task completed?",
            {**context, "validation": cand.validation, "path": path},
            task,
            cand.identity_key,
        )
        return done("review")

    if cand.intent == "withdrawal":
        if task:
            open_review(
                db,
                uid,
                record,
                event,
                "withdrawal",
                "A newer notice says this requirement was withdrawn. Remove the task?",
                context,
                task,
            )
            return done("review")
        return done("ignored_unmatched_withdrawal")

    if cand.intent == "supporting":
        if task:
            link(db, task, event, cand.method)
            history(db, task, "supporting_information", {"links": cand.links[:3]}, event)
            return done("evidence_recorded")
        if cand.relates:
            open_review(
                db,
                uid,
                record,
                event,
                "association",
                "Which task does this guidance belong to?",
                context,
                identity=cand.identity_key,
            )
            return done("review")
        return done("ignored_supporting")

    # New work, revisions, and due notices.
    if not cand.task_type and not task:
        return done("ignored_unclassified")
    if task:
        if task.type != (cand.task_type or task.type):
            open_review(
                db,
                uid,
                record,
                event,
                "conflict",
                "The source describes this work as a different type. Which is right?",
                context,
                task,
            )
            return done("review")
        explicit = cand.intent == "revision" or task_by_identity(db, uid, cand.identity_key) is not None
        changes, conflicts = update_task(db, task, cand, event, explicit, cand.method)
        if conflicts:
            open_review(
                db, uid, record, event, "conflict", "Two sources give different details for this task. Which should be kept?",
                {**context, "conflicts": conflicts}, task,
            )  # fmt: skip
            return done("review")
        if task.completed_at and cand.intent == "due_notice":
            history(db, task, "evidence_added", {"reason": "reminder did not change completion"}, event)
        return done("updated" if changes else "evidence_recorded")
    if cand.section.startswith("quoted"):
        return done("quoted_history")  # Quoted schedules are history, not new tasks.
    facts = {
        "source": cand.source,
        "sender": record.sender_email,
        "subjectId": subject_id,
        "subjectKind": kind,
        "taskType": cand.task_type,
        "assessmentLabel": cand.assessment_label,
        "text": " ".join(filter(None, [cand.title, cand.excerpt, record.title])),
    }
    relevance, rule_priority, matched = rules.evaluate(ctx["rules"], facts)
    if relevance == "exclude":
        event.data = {**event.data, "rule": matched}
        return done("rule_excluded")
    fields = proposal(cand, subject_id)
    if rule_priority:
        fields_extra = {"rulePriority": {"value": rule_priority, "ruleId": matched["priority"]}}
    else:
        fields_extra = {}
    review_data = {
        **context,
        "proposal": fields,
        "extra": fields_extra,
        "subjectChoices": cand.subject_choices,
    }
    if outcome != "applicable":
        open_review(
            db,
            uid,
            record,
            event,
            "confirm_applicability",
            question or "Is this work for you?",
            {**review_data, "reason": reason},
            identity=cand.identity_key,
        )
        return done("review")
    if not subject_id:
        open_review(
            db,
            uid,
            record,
            event,
            "choose_subject",
            "Which of your subjects is this for?",
            review_data,
            identity=cand.identity_key,
        )
        return done("review")
    issue = unresolved(cand)
    if issue:
        open_review(
            db, uid, record, event, "timing_unresolved", issue,
            {**review_data, "window": cand.window, "alternatives": cand.alternatives}, identity=cand.identity_key,
        )  # fmt: skip
        return done("review")
    similar = similar_task(db, uid, cand, subject_id)
    if similar:
        open_review(
            db,
            uid,
            record,
            event,
            "possible_duplicate",
            "This looks like an existing task. Is it the same work?",
            review_data,
            similar,
            cand.identity_key,
        )
        return done("review")
    try:
        created = create_task(db, uid, ctx, record, event, cand, subject_id, cand.method)
    except ApiError:
        open_review(
            db,
            uid,
            record,
            event,
            "timing_unresolved",
            "The source gives inconsistent times. Which are right?",
            review_data,
            identity=cand.identity_key,
        )
        return done("review")
    if fields_extra:
        created.data = {**created.data, **fields_extra}
    return done("created")


def commit(db, uid, record, prepared, ctx, progress, run):
    """Apply one prepared record. Returns updated progress."""

    def bump(key):
        progress[key] = progress.get(key, 0) + 1

    from .sync import lock_sender, minimize, sender_decision  # Avoid an import cycle with sync.

    if record.processing_state != "awaiting_interpretation" or record.revision != prepared.revision:
        bump("skipped")
        return progress
    if record.sender_email:
        lock_sender(db, record.user_id, record.sender_email)
        state, _ = sender_decision(db, record.user_id, record.sender_email)
        if state == "blocked":
            minimize(db, record, "blocked", "sender_blocked")
            bump("blocked")
            return progress
    if prepared.paused:
        record.data = {
            **record.data,
            "aiPausedUntil": (now() + AI_PAUSE).isoformat(),
            "aiPausedReason": prepared.paused,
        }
        bump("aiPaused")
        return progress
    if prepared.ignore:
        if record.kind.startswith("classroom"):
            # Classroom items can change later (e.g. NEW -> TURNED_IN); keep the content hash so an
            # unchanged item is not re-queued on every sync. No body is stored for these records.
            record.processing_state, record.reason = "ignored", prepared.ignore
        else:
            minimize(db, record, "ignored", prepared.ignore)
        bump("notAcademic")
        return progress
    outcomes = [apply_candidate(db, uid, ctx, record, i, c, run) for i, c in enumerate(prepared.candidates)]
    for o in outcomes:
        bump(
            {
                "created": "tasksCreated",
                "updated": "tasksUpdated",
                "review": "reviews",
                "completed": "completed",
            }.get(o, "evidence")
        )
    data = {k: v for k, v in record.data.items() if k not in ("aiPausedUntil", "aiPausedReason")}
    record.data = {
        **data,
        "interpretation": {
            **prepared.meta,
            "version": VERSION,
            "outcomes": outcomes,
            "at": now().isoformat(),
        },
    }
    record.processing_version = VERSION
    if outcomes and all(o.startswith("ignored") or o == "unmatched_receipt" for o in outcomes):
        reason = (
            "targeting_mismatch"
            if "ignored_mismatch" in outcomes
            else "kt_notice"
            if "ignored_kt" in outcomes
            else ("unmatched_receipt" if "unmatched_receipt" in outcomes else "not_academic_work")
        )
        if reason == "unmatched_receipt" or record.kind.startswith("classroom"):
            record.processing_state, record.reason = "ignored", reason
            record.expires_at = now() + timedelta(days=30)
        else:
            minimize(db, record, "ignored", reason)
    elif not outcomes:
        minimize(db, record, "ignored", "no_obligation")
    else:
        record.processing_state = "needs_review" if "review" in outcomes else "interpreted"
        excerpt = next((c.excerpt for c in prepared.candidates if c.excerpt), None)
        record.excerpt = excerpt[:500] if excerpt else None
    return progress


def unit(snap, token):
    """One interpretation unit for the sync engine; returns apply(db, job, conn) -> done."""
    record_id = next_record(snap.uid, snap.connection_id)
    if record_id is None:
        return None
    prepared, ctx = prepare(snap.uid, record_id, token, snap.account_email)
    run = snap.checkpoint.get("run", 0)

    def apply(db, job, conn):
        record = db.scalar(select(SourceRecord).where(SourceRecord.id == record_id).with_for_update())
        progress = commit(db, conn.user_id, record, prepared, ctx, dict(job.progress), run)
        job.progress = progress
        job.phase = "interpreting"
        return False

    return apply


def suppress_reviews(db, uid, email):
    from sqlalchemy import delete

    from .models import Activity

    rows = db.scalars(
        select(ReviewItem).where(
            ReviewItem.user_id == uid, ReviewItem.sender_email == email, ReviewItem.status == "open"
        )
    ).all()
    for r in rows:
        r.status = "suppressed"  # Cannot be approved while the block is active.
        r.data, r.question = {}, "This sender is blocked"
        db.execute(delete(Activity).where(Activity.target_type == "review", Activity.target_id == r.id))
    return len(rows)


def json_safe(value):
    return json.loads(json.dumps(value, default=str))
