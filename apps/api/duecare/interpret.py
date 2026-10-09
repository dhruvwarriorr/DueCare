"""Academic interpretation and reconciliation of imported source records (Phase 3).

Decision order for each record: current sender block -> recognized template or bounded AI
extraction -> academic applicability against the profile -> subject resolution among the student's
own subjects -> ordered rules (new tasks only) -> reconciliation with existing tasks.

Reconciliation invariants (enforced here, independently of AI):
- Due/overdue notices, digests, countdowns, deadline passage and source edits never clear completion.
- Completion comes only from validated submission evidence on an enabled path, or the student.
- A newer explicit student reopen survives replay of older receipts.
- Manual field corrections win over sources; the latest source settles source disagreements.
- Older source events never roll back newer accepted values.
"""

import base64
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import case, func, or_, select

from . import academic, ai, faculty, google, lms, mail, rules, subject_link, targeting
from .classroom_time import due_at
from .common import work
from .config import GMAIL_LOOKBACK, settings
from .domain import effective_status, task_data
from .errors import ApiError
from .models import (
    Connection,
    History,
    Profile,
    ReviewItem,
    Rule,
    Slot,
    SourceCourse,
    SourceEvent,
    SourceRecord,
    Subject,
    SubjectMapping,
    Task,
    TaskEvidence,
    now,
)
from .schemas import TaskInput

VERSION = "phase3-interpret-2"
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
SCHEDULE_FIELDS = {*TIMING_FIELDS, "dueDate", "dateWindowStart", "dateWindowEnd", "timingMode"}
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
    subject_link: dict | None = None


@dataclass
class Prepared:
    record_id: uuid.UUID
    revision: int
    candidates: list = field(default_factory=list)
    ignore: str | None = None
    paused: str | None = None
    meta: dict = field(default_factory=dict)
    receipt_retry: int = 0
    paused_retry_after: int = 60
    paused_code: str = "AI_UNAVAILABLE"


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
    return {"lms_assignment_receipt", "lms_quiz_receipt", "classroom_turned_in"} | {
        p.strip() for p in settings().auto_completion_paths.split(",") if p.strip()
    }


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
    mapped, course_name = [], None
    if record.external_course_id:
        course_name = db.scalar(
            select(SourceCourse.name).where(
                SourceCourse.connection_id == record.connection_id,
                SourceCourse.external_course_id == record.external_course_id,
            )
        )
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
        "courseName": course_name,
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


def in_gmail_window():
    return or_(
        SourceRecord.kind != "gmail_message",
        func.coalesce(
            SourceRecord.received_at,
            SourceRecord.sent_at,
            SourceRecord.created_at,
        )
        >= now() - GMAIL_LOOKBACK,
    )


def pending_records(db, connection_id, limit=1, exclude=()):
    order = func.coalesce(SourceRecord.sent_at, SourceRecord.published_at, SourceRecord.received_at)
    stmt = select(SourceRecord.id, SourceRecord.kind, SourceRecord.title).where(
        SourceRecord.connection_id == connection_id,
        SourceRecord.processing_state == "awaiting_interpretation",
        in_gmail_window(),
        (SourceRecord.data["aiPausedUntil"].astext.is_(None))
        | (SourceRecord.data["aiPausedUntil"].astext < now().isoformat()),
    )
    if exclude:
        stmt = stmt.where(SourceRecord.id.not_in(exclude))
    # Gmail's newest messages take priority over an old interpretation backlog.
    # Classroom keeps chronological event ordering and coursework priority.
    rows = db.execute(
        stmt.order_by(
            case((SourceRecord.kind == "gmail_message", order), else_=None).desc().nulls_last(),
            order.asc().nulls_first(),
            SourceRecord.id,
        ).limit(200)
    ).all()
    return [r[0] for r in sorted(rows, key=lambda r: KIND_ORDER.get(r.kind, 9))[:limit]]


def pending_record(db, connection_id):
    records = pending_records(db, connection_id)
    return records[0] if records else None


def next_record(uid, connection_id):
    with work({"id": uid}) as db:
        return pending_record(db, connection_id)


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
    prepared = Prepared(
        record_id=record_id,
        revision=snapshot["revision"],
        receipt_retry=snapshot["data"].get("receiptRetry", 0),
    )
    try:
        if snapshot["kind"] == "gmail_message":
            gmail_candidates(prepared, snapshot, ctx, token, account_email)
        elif snapshot["kind"] == "classroom_submission":
            submission_candidates(prepared, snapshot)
        else:
            classroom_candidates(prepared, snapshot, ctx, token)
        resolve_subjects(prepared, ctx, snapshot)
    except google.SourceError as exc:
        if exc.kind != "not_found":
            raise
        prepared.ignore = "source_unavailable"
    except ai.BudgetExpired:
        raise
    except ai.AIUnavailable as exc:
        prepared.paused = str(exc)
        prepared.paused_retry_after = exc.retry_after
        prepared.paused_code = exc.code
    return prepared, ctx


LINKED_INTENTS = {"new_work", "revision", "due_notice", "submission", "withdrawal"}


def resolve_subjects(prepared, ctx, snap):
    """Link each work item to one of the student's subjects without asking them: short forms, names
    and full-name initials first, then one AI call for the rest. Classroom items stay within the
    course's linked subjects. Work no subject fits, or that cannot be linked while the AI is
    unavailable, is created without a subject."""
    subjects = ctx["subjects"]
    pending = []
    for n, c in enumerate(prepared.candidates):
        if c.intent not in LINKED_INTENTS or not subjects:
            continue
        pool_ids = (
            (set(ctx["mapped"]) if c.source == "classroom" else {s["id"] for s in subjects})
            if c.method == "ai"
            else (set(c.subject_choices) or {s["id"] for s in subjects})
        )
        pool = [s for s in subjects if s["id"] in pool_ids]
        # An extracted subject ID is a suggestion. Explicit course words take precedence.
        texts = [c.course_label, c.title, c.assessment_label, c.deliverable_label]
        component = c.component_hint or subject_link.component_of(" ".join(t for t in texts if t))
        chosen = pool[0]["id"] if len(pool) == 1 else subject_link.deterministic(texts, pool, component)
        if chosen:
            c.subject_id, c.subject_link = chosen, {"method": "name"}
            continue
        if c.subject_id in pool_ids:
            continue
        pending.append((n, c, pool))
    if not pending:
        return
    items = [
        {
            "key": f"i{n}",
            "allowed": [s["id"] for s in pool],
            "taskType": c.task_type,
            "title": c.title,
            "assessmentLabel": c.assessment_label,
            "deliverableLabel": c.deliverable_label,
            "componentHint": c.component_hint,
            "courseLabel": c.course_label,
            "classroomCourse": ctx.get("courseName"),
            "sourceTitle": snap["title"],
            "excerpt": (c.excerpt or "")[:300],
        }
        for n, c, pool in pending
    ]
    try:
        links, meta = subject_link.ai_links(items, subjects)
    except ai.AIUnavailable:
        # Linking alone is not worth holding the work back: keep it without a subject, to set later.
        links, meta = {}, {"used": False, "unavailable": True}
    prepared.meta = {**prepared.meta, "subjectLinking": meta}
    for n, c, _ in pending:
        chosen = links.get(f"i{n}")
        c.subject_id = chosen
        if chosen:
            c.subject_link = {"method": "ai", "model": meta.get("model")}
        else:
            c.subject_link = {
                "method": "none",
                **({"reason": "ai_unavailable"} if meta.get("unavailable") else {}),
            }


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


def grounded_item(item, sections, title=None):
    """Lookup tasks must not become obligations invented in a different source."""
    evidence = lms.flat(item.evidence).casefold()
    section = next((s for s in sections if s.get("id") == item.section), None)
    if not evidence or not section:
        return False
    source = lms.flat(section.get("text", "")).casefold()
    return evidence in source or (item.section == "authored" and evidence in lms.flat(title).casefold())


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
    exclusion = mail.academic_exclusion(
        decoded.subject, decoded.sender_email, decoded.sender_name, decoded.authored_text
    )
    if exclusion:
        prepared.ignore = exclusion
        return
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
                    "template": template,
                    "sender": decoded.sender_email in lms_senders(),
                    "authenticated": auth_obs.get("dkim") == "pass"
                    and auth_obs.get("dmarc") == "pass"
                    and auth_obs.get("headerFrom") == decoded.sender_email.rsplit("@", 1)[1],
                    "addressedToAccount": addressed,
                    "notForwarded": not forwarded,
                    "activityLink": bool(c.identity_key)
                    and c.identity_key.split(":")[1] in lms_hosts()
                    and c.identity_key.split(":")[2] == ("quiz" if c.task_type == "test" else "assign"),
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
        if not grounded_item(item, sections, decoded.subject):
            continue
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
    sections = [{"id": "authored", "text": text}]
    extraction, meta = ai.extract(ai_payload(ctx, source, sections, ctx["mapped"]))
    prepared.meta = {"method": "ai", **meta}
    occurred = parse_dt(utc(item.get("updateTime") or item.get("creationTime")))
    if occurred is None:
        occurred = snap["published"]
    for i, it in enumerate(extraction.items):
        if not grounded_item(it, sections, item.get("title")):
            continue
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


def work_signature(title, subject):
    """Conservative assessment name within one course; IA1 and IA2 remain distinct."""
    text = (title or "").casefold()
    names = [subject["name"], subject.get("code"), *(subject.get("aliases") or [])]
    for key, aliases in subject_link.COURSE_NAMES.items():
        if {norm(n) for n in names if n} & {norm(key), *(norm(n) for n in aliases)}:
            names.extend([key, *aliases])
    for name in sorted(filter(None, names), key=len, reverse=True):
        text = re.sub(r"(?<!\w)" + re.escape(name.casefold()) + r"(?!\w)", " ", text)
    text = re.sub(r"\bia\s*[- ]?\s*(\d+)\b", r"ia\1", text)
    words = set(re.findall(r"[a-z]+\d*|\d+", text))
    if any(re.fullmatch(r"ia\d+", w) for w in words):
        words -= {"quiz", "test", "exam", "examination", "mcq", "internal", "assessment"}
    return words


def same_work(cand, task, ctx):
    """A model-suggested task ID alone is never identity or completion evidence."""
    if cand.task_type and cand.task_type != task.type:
        return False
    if not cand.subject_id or str(task.subject_id) != cand.subject_id:
        return False
    subject = next((s for s in ctx["subjects"] if s["id"] == cand.subject_id), None)
    if not subject:
        return False
    mine, theirs = work_signature(cand.title, subject), work_signature(task.title, subject)
    if not mine or not theirs:
        return False
    if {w for w in mine if re.search(r"\d", w)} != {w for w in theirs if re.search(r"\d", w)}:
        return False
    return mine == theirs or len(mine & theirs) / len(mine | theirs) >= 0.6


def receipt_tasks(db, uid, cand, ctx, primary=None):
    """Verified LMS receipts can cover duplicate notices of the same course assessment.

    Different concrete LMS activities are never joined by their display names. A generic
    name without a course and assessment identity is insufficient for fallback matching.
    """
    tasks = [primary] if primary else []
    if not cand.identity_key or not cand.identity_key.startswith("lms:") or not cand.subject_id:
        return tasks
    for task in db.scalars(
        select(Task)
        .where(
            Task.user_id == uid,
            Task.subject_id == uuid.UUID(cand.subject_id),
            Task.type == cand.task_type,
            Task.data["mergedInto"].astext.is_(None),
        )
        .order_by(Task.created_at)
        .with_for_update()
    ):
        if task in tasks or not same_work(cand, task, ctx):
            continue
        keys = set(
            db.scalars(
                select(SourceEvent.identity_key)
                .join(TaskEvidence, TaskEvidence.event_id == SourceEvent.id)
                .where(
                    TaskEvidence.task_id == task.id,
                    TaskEvidence.state == "active",
                    SourceEvent.identity_key.like("lms:%"),
                )
            )
        )
        if keys and cand.identity_key not in keys:
            continue
        subject = next(s for s in ctx["subjects"] if s["id"] == cand.subject_id)
        signature = work_signature(cand.title, subject)
        if signature <= {"quiz", "test", "exam", "assignment", "experiment", "submission", "assessment"}:
            continue
        # Fallback is exact after removing course words and IA assessment synonyms.
        if signature != work_signature(task.title, subject):
            continue
        tasks.append(task)
    return tasks


def verified_lms_receipt(cand):
    validation = cand.validation or {}
    return (
        validation.get("template") in ("assignment_receipt", "quiz_receipt")
        and all(
            validation.get(k) is True
            for k in ("sender", "authenticated", "addressedToAccount", "notForwarded", "activityLink")
        )
        and cand.method == "lms_" + validation["template"]
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


def candidate_from_event(event, record, fields=None):
    data = event.data
    values = {**data.get("proposal", {}), **(fields or {})}
    return Cand(
        intent=event.event_type,
        task_type=values.get("type", data.get("taskType")),
        title=values.get("title", data.get("title")),
        subject_id=values.get("subjectId"),
        assessment_label=values.get("assessmentLabel", data.get("assessmentLabel")),
        deliverable_label=values.get("deliverableLabel", data.get("deliverableLabel")),
        location=values.get("location"),
        instructions=values.get("instructions"),
        duration=values.get("durationMinutes"),
        mode=values.get("timingMode"),
        date_only=values.get("dueDate"),
        window=(values["dateWindowStart"], values["dateWindowEnd"])
        if values.get("dateWindowStart") and values.get("dateWindowEnd")
        else None,
        observed=data.get("observedTargeting") or {},
        timing={**(data.get("timing") or {}), **{k: v for k, v in values.items() if k in TIMING_FIELDS}},
        provenance=data.get("provenance") or {},
        validation=data.get("validation"),
        links=data.get("links") or [],
        excerpt=data.get("excerpt"),
        occurred_at=event.occurred_at,
        identity_key=event.identity_key,
        method=data.get("method", "review"),
        section=data.get("section", "authored"),
        source="classroom" if record.kind.startswith("classroom") else "gmail",
        course_label=data.get("courseLabel"),
    )


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


def undated_fields(fields):
    """Keep the obligation without accepting any uncertain date or time."""
    return {**{k: v for k, v in fields.items() if k not in SCHEDULE_FIELDS}, "timingMode": "undated"}


def timing_error(exc):
    if isinstance(exc, ApiError):
        return exc.code == "INVALID_TIME"
    return isinstance(exc, ValidationError) and all(
        error["loc"] and error["loc"][0] in SCHEDULE_FIELDS for error in exc.errors()
    )


def create_task(db, uid, ctx, record, event, cand, subject_id, method, fields=None):
    values = fields or proposal(cand, subject_id)
    timing_omitted = method != "student_review" and bool(unresolved(cand))
    if timing_omitted:
        values = undated_fields(values)
    try:
        d = task_input(values)
    except (ApiError, ValidationError) as exc:
        if method == "student_review" or not timing_error(exc):
            raise
        timing_omitted = True
        d = task_input(undated_fields(values))
    provenance = {**d.get("timingProvenance", {})}
    for name, prov in cand.provenance.items():
        if name in provenance or d.get(name):
            provenance[name] = {**prov, "evidenceRef": str(event.id)}
    for name, value in d.items():
        if name == "timingProvenance":
            continue
        if value is not None:
            provenance[name] = {
                **provenance.get(name, {"basis": "source-exact"}),
                "sourceTime": source_order(db, event)[0].isoformat(),
                "evidenceRef": str(event.id),
            }
    if d.get("dueAt"):
        provenance["dueAt"] = {
            **provenance.get("dueAt", {"basis": "source-exact"}),
            "sourceTime": source_order(db, event)[0].isoformat(),
            "evidenceRef": str(event.id),
        }
    if timing_omitted:
        # Clearing uncertain timing is also a source decision: an older notice must not
        # fill it back in merely because the accepted values are now null.
        for name in SCHEDULE_FIELDS:
            provenance[name] = {
                "basis": "source-timing-omitted",
                "sourceTime": source_order(db, event)[0].isoformat(),
                "evidenceRef": str(event.id),
            }
    d["timingProvenance"] = provenance
    p = ctx["profile"]
    d["academicContext"] = academic.context(p)
    d["manualFieldOverrides"] = {}
    d["sources"] = [cand.source]
    d["sourceLinks"] = cand.links
    d["observedTargeting"] = cand.observed
    d["groupWork"] = cand.group_work
    if cand.subject_link:
        d["subjectLink"] = cand.subject_link
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
    if cand.identity_key:
        # Subject questions from before automatic linking are settled by this task.
        for item in db.scalars(
            select(ReviewItem).where(
                ReviewItem.user_id == record.user_id,
                ReviewItem.status == "open",
                ReviewItem.issue_type == "choose_subject",
                ReviewItem.data["identityKey"].astext == cand.identity_key,
            )
        ):
            item.status, item.resolved_at, item.task_id = "resolved", now(), task.id
    history(
        db,
        task,
        "imported",
        {k: d.get(k) for k in ("title", "type", "subjectId", "dueAt", "timingMode") if d.get(k)},
        event,
    )
    requeue_receipts(db, uid, cand.identity_key)
    reconcile_lms_receipts(db, uid, ctx, task)
    if record.kind == "gmail_message":
        faculty.approve(
            db, uid, record.sender_email, "student" if method == "student_review" else "automatic"
        )
    return task


def requeue_receipts(db, uid, identity):
    """A receipt may arrive before its task; retry it as soon as an exact activity exists."""
    if not identity:
        return
    records = db.scalars(
        select(SourceRecord)
        .where(
            SourceRecord.user_id == uid,
            SourceRecord.processing_state == "ignored",
            SourceRecord.reason == "unmatched_receipt",
            in_gmail_window(),
            SourceRecord.id.in_(
                select(SourceEvent.source_record_id).where(
                    SourceEvent.user_id == uid,
                    SourceEvent.identity_key == identity,
                    SourceEvent.outcome == "unmatched_receipt",
                )
            ),
        )
        .with_for_update()
    ).all()
    for record in records:
        record.processing_state, record.reason, record.expires_at = "awaiting_interpretation", None, None
        record.data = {**record.data, "receiptRetry": record.data.get("receiptRetry", 0) + 1}


def reconcile_lms_receipts(db, uid, ctx, only_task=None):
    """Replay saved authenticated receipts when a matching notice appears later, without AI."""
    from .privacy import suppressed
    from .sync import sender_decision

    count = 0
    rows = db.execute(
        select(SourceEvent, SourceRecord)
        .join(SourceRecord, SourceRecord.id == SourceEvent.source_record_id)
        .where(
            SourceEvent.user_id == uid,
            SourceEvent.event_type == "submission",
            SourceRecord.kind == "gmail_message",
            in_gmail_window(),
        )
        .order_by(SourceEvent.occurred_at, SourceEvent.created_at)
    ).all()
    for event, record in rows:
        if (
            record.processing_state in ("blocked", "duplicate")
            or (record.processing_state == "ignored" and record.reason != "unmatched_receipt")
            or (record.expires_at and record.expires_at <= now())
        ):
            continue
        conn = db.get(Connection, record.connection_id)
        if (
            not conn
            or conn.status != "active"
            or sender_decision(db, uid, record.sender_email)[0] == "blocked"
        ):
            continue
        cand = candidate_from_event(event, record)
        if not verified_lms_receipt(cand) or cand.method not in completion_paths():
            continue
        if suppressed(db, conn, cand.identity_key) or suppressed(db, conn, record.provider_id):
            continue
        primary = task_by_identity(db, uid, cand.identity_key)
        matches = receipt_tasks(db, uid, cand, ctx, primary)
        applied = []
        for task in matches:
            if (only_task and only_task.id != task.id) or task.completed_at:
                continue
            outcome, _, _ = targeting.evaluate(
                cand.observed,
                ctx["profile"],
                subject_kind=subject_kind(ctx, str(task.subject_id)),
                trusted=True,
            )
            if outcome != "applicable":
                continue
            link(db, task, event, cand.method)
            result = complete_task(db, task, event, cand.method)
            count += int(result == "completed")
            if result == "completed":
                applied.append(task)
        if applied:
            event.task_id = primary.id if primary else applied[0].id
            event.outcome = "completed"
            if record.reason == "unmatched_receipt":
                record.processing_state, record.reason, record.expires_at = "interpreted", None, None
    return count


def source_order(db, event):
    """Order by publication/edit time, never by sync arrival or interpretation completion."""
    record = db.get(SourceRecord, event.source_record_id)
    stamp = event.occurred_at
    if record:
        if event.processing_version != VERSION and record.kind in (
            "classroom_coursework",
            "classroom_announcement",
        ):
            stamp = record.source_updated_at or stamp
        stamp = stamp or record.sent_at or record.published_at or record.received_at
    stamp = stamp or datetime.min.replace(tzinfo=UTC)
    key = record.provider_id if record else str(event.source_record_id)
    parts = event.event_key.split(":")
    revision = int(parts[0]) if parts[0].isdigit() else 0
    return stamp.astimezone(UTC), f"{key}:{parts[-1]}:{revision:020d}"


def field_order(db, task, name, provenance):
    previous = provenance.get(name, {})
    if previous.get("evidenceRef"):
        old = db.get(SourceEvent, uuid.UUID(previous["evidenceRef"]))
        if old and old.user_id == task.user_id:
            return source_order(db, old)
    stamp = parse_dt(utc(previous.get("sourceTime")))
    if stamp:
        return stamp, ""
    # Legacy tasks may have no field clock. Recover it from the evidence that supplied
    # the currently accepted value, rather than treating the next imported item as newest.
    events = db.scalars(
        select(SourceEvent)
        .join(TaskEvidence, TaskEvidence.event_id == SourceEvent.id)
        .where(
            TaskEvidence.task_id == task.id,
            TaskEvidence.state == "active",
            SourceEvent.event_type.in_(("new_work", "revision", "due_notice")),
            SourceEvent.outcome.in_(("created", "updated", "accepted", "linked", "evidence_recorded")),
        )
    ).all()
    matching = [
        e
        for e in events
        if {**e.data, **e.data.get("timing", {}), **e.data.get("proposal", {})}.get(name)
        == task.data.get(name)
    ]
    return max((source_order(db, e) for e in matching), default=(datetime.min.replace(tzinfo=UTC), ""))


def settle_reviews(db, task, issues, reason):
    count = 0
    for item in db.scalars(
        select(ReviewItem).where(
            ReviewItem.user_id == task.user_id,
            ReviewItem.task_id == task.id,
            ReviewItem.status == "open",
            ReviewItem.issue_type.in_(issues),
        )
    ):
        item.status, item.resolved_at = "resolved", now()
        item.revision += 1
        item.data = {**item.data, "resolution": {"action": reason, "at": now().isoformat()}}
        count += 1
    return count


def update_task(db, task, cand, event, explicit, method):
    """Reconcile role-specific fields. Never touches completion."""
    changes, conflicts = {}, {}
    incoming = proposal(cand, cand.subject_id)
    if method != "student_review" and unresolved(cand):
        incoming = {**undated_fields(incoming), **{k: None for k in SCHEDULE_FIELDS if k != "timingMode"}}
    if not cand.title:
        incoming.pop("title", None)
    mode = task.data.get("timingMode")
    keep_session = (
        mode == "fixed_session"
        and "availabilityClosesAt" in incoming
        and cand.intent == "due_notice"
        and "startsAt" not in incoming
    )
    if keep_session:
        # A quiz closing notice does not overwrite an established classroom session.
        incoming.pop("dueAt", None)
        incoming.pop("timingMode", None)
    overrides = task.data.get("manualFieldOverrides", {})
    provenance = task.data.get("timingProvenance", {})
    prov = {**provenance}
    incoming_order = source_order(db, event)
    for name, value in incoming.items():
        current = task.data.get(name)
        if name in overrides or (name in ("startsAt", "availabilityClosesAt") and "dueAt" in overrides):
            continue
        if method != "student_review" and incoming_order < field_order(db, task, name, provenance):
            continue
        prov[name] = {
            **cand.provenance.get(name, {"basis": "source-exact"}),
            "sourceTime": incoming_order[0].isoformat(),
            "evidenceRef": str(event.id),
        }
        if current != value:
            changes[name] = value
    if "dueAt" not in overrides and any(
        name in incoming and prov.get(name, {}).get("evidenceRef") == str(event.id)
        for name in (
            ("dueDate", "startsAt") if keep_session else ("dueDate", "startsAt", "availabilityClosesAt")
        )
    ):
        prov["dueAt"] = {
            **prov.get("dueAt", {"basis": "source-exact"}),
            "sourceTime": incoming_order[0].isoformat(),
            "evidenceRef": str(event.id),
        }
    if changes:
        allowed = {f.alias for f in TaskInput.model_fields.values()}
        merged = {k: v for k, v in task.data.items() if k in allowed}
        if any(k in changes for k in ("startsAt", "availabilityClosesAt")) and "dueAt" not in changes:
            merged["dueAt"] = None
        merged.update(changes)
        merged.pop("dueDate", None) if "dueAt" in changes else None
        try:
            d = task_input(merged)
        except (ApiError, ValidationError) as exc:
            if not timing_error(exc):
                raise
            # A new schedule can be incompatible with leftover old times. Replace the old
            # schedule as a unit with the newer source's own valid schedule, preserving edits.
            schedule = {*TIMING_FIELDS, "timingMode", "dueDate", "dateWindowStart", "dateWindowEnd"}
            reset = {
                k: v
                for k, v in merged.items()
                if k not in schedule
                or k in overrides
                or incoming_order < field_order(db, task, k, provenance)
            }
            reset.update(
                {
                    k: v
                    for k, v in incoming.items()
                    if k in schedule and k in prov and prov[k].get("evidenceRef") == str(event.id)
                }
            )
            try:
                d = task_input(reset)
            except (ApiError, ValidationError) as exc:
                if not timing_error(exc):
                    raise
                # An older inconsistent schedule cannot clear a newer accepted one.
                reset = undated_fields(merged)
                preserve_schedule = any(
                    k in overrides
                    or (
                        task.data.get(k) is not None and incoming_order < field_order(db, task, k, provenance)
                    )
                    for k in schedule
                )
                if preserve_schedule:
                    reset.update({k: task.data.get(k) for k in schedule})
                else:
                    for name in schedule:
                        prov[name] = {
                            "basis": "source-timing-omitted",
                            "sourceTime": incoming_order[0].isoformat(),
                            "evidenceRef": str(event.id),
                        }
                d = task_input(reset)
                changes = {k: d.get(k) for k in schedule | changes.keys() if task.data.get(k) != d.get(k)}
            else:
                changes = {k: d.get(k) for k in schedule | changes.keys() if task.data.get(k) != d.get(k)}
        if changes:
            # Track derived cutoffs too: a date-only deadline or test start can also
            # change dueAt, and an older explicit cutoff must not undo that newer value.
            changes = {k: d.get(k) for k in allowed if task.data.get(k) != d.get(k)}
            for name in changes:
                prov[name] = {
                    **cand.provenance.get(name, {"basis": "source-exact"}),
                    "sourceTime": incoming_order[0].isoformat(),
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
            task.title, task.type = d["title"], d["type"]
            task.subject_id = uuid.UUID(d["subjectId"]) if d.get("subjectId") else None
            task.status = effective_status(task, now())
            task.revision += 1
            history(db, task, "source_update", changes, event)
    if not conflicts:
        if not changes and prov != provenance:
            task.data = {**task.data, "timingProvenance": prov}
            task.revision += 1
        settle_reviews(db, task, ("conflict", "timing_unresolved"), "source_details_applied")
    link(db, task, event, method)
    return changes, conflicts


def complete_task(db, task, event, origin):
    """Atomic completion under the task row lock; survives every later reminder."""
    if task.completed_at:
        settle_reviews(db, task, ("confirm_completion", "receipt_unverified"), "submission_confirmed")
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
    for review in db.scalars(
        select(ReviewItem).where(
            ReviewItem.user_id == task.user_id,
            ReviewItem.task_id == task.id,
            ReviewItem.status == "open",
            ReviewItem.issue_type.in_(("confirm_completion", "receipt_unverified")),
        )
    ):
        review.status, review.resolved_at = "resolved", now()
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
    if cand.source == "gmail" and mail.academic_exclusion(
        cand.title, record.sender_email, text=cand.instructions or cand.excerpt
    ):
        return "ignored_non_academic"
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
            "courseLabel": cand.course_label,
            "observedTargeting": cand.observed,
            "timing": cand.timing,
            "provenance": cand.provenance,
            "validation": cand.validation,
            "excerpt": cand.excerpt,
            "links": cand.links,
            "proposal": proposal(cand, cand.subject_id),
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
        if task and cand.method == "ai" and not same_work(cand, task, ctx):
            task = None
    if not task and cand.intent == "submission" and verified_lms_receipt(cand):
        matches = receipt_tasks(db, uid, cand, ctx)
        task = matches[0] if matches else None
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
        cand.observed,
        ctx["profile"],
        subject_kind=kind,
        trusted=cand.trusted or bool(task) or faculty.approved(db, uid, record.sender_email),
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
            return done("unmatched_receipt")  # Re-queued automatically when its exact task is created.
        if cand.task_type and task.type != cand.task_type:
            return done("ignored_type_mismatch")
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
        path = (
            "classroom_turned_in"
            if cand.method == "classroom_submission"
            else "lms_quiz_receipt"
            if cand.validation and cand.validation.get("template") == "quiz_receipt"
            else "lms_assignment_receipt"
        )
        valid = verified_lms_receipt(cand) or (
            cand.method == "classroom_submission" and (cand.validation or {}).get("ownSubmission") is True
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
                cand.identity_key,
            )
            return done("review")
        if path in completion_paths():
            completed = complete_task(db, task, event, path)
            if verified_lms_receipt(cand):
                for sibling in receipt_tasks(db, uid, cand, ctx, task):
                    if sibling.id != task.id:
                        link(db, sibling, event, path)
                        complete_task(db, sibling, event, path)
                event.task_id = task.id
            return done(completed)
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
        requeue_receipts(db, uid, cand.identity_key)
        explicit = cand.intent == "revision" or task_by_identity(db, uid, cand.identity_key) is not None
        changes, conflicts = update_task(db, task, cand, event, explicit, cand.method)
        reconcile_lms_receipts(db, uid, ctx, task)
        if record.kind == "gmail_message" and outcome == "applicable":
            faculty.approve(db, uid, record.sender_email)
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
    # Subjects are linked automatically (see resolve_subjects); work matching none of the student's
    # subjects is kept without one rather than asking.
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
    created = create_task(db, uid, ctx, record, event, cand, subject_id, cand.method)
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
    if record.kind == "gmail_message" and mail.academic_exclusion(
        record.title, record.sender_email, record.data.get("senderName"), record.excerpt
    ):
        prepared.ignore, prepared.paused = "non_academic_mail", None
    if prepared.paused:
        record.data = {
            **record.data,
            "aiPausedUntil": (now() + timedelta(seconds=prepared.paused_retry_after)).isoformat(),
            "aiPausedReason": prepared.paused,
            "aiPausedCode": prepared.paused_code,
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
    was_approved = faculty.approved(db, uid, record.sender_email)
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
    data = {
        k: v for k, v in record.data.items() if k not in ("aiPausedUntil", "aiPausedReason", "aiPausedCode")
    }
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
    if record.kind == "gmail_message" and not was_approved and faculty.approved(db, uid, record.sender_email):
        from .reconcile import refresh_faculty_reviews

        refresh_faculty_reviews(db, uid)
    return progress


def unit(snap, token, record_id=None):
    """One interpretation unit for the sync engine; returns apply(db, job, conn) -> done."""
    record_id = record_id or next_record(snap.uid, snap.connection_id)
    if record_id is None:
        return None
    prepared, ctx = prepare(snap.uid, record_id, token, snap.account_email)
    run = snap.checkpoint.get("run", 0)
    if prepared.receipt_retry:
        run = f"{run}r{prepared.receipt_retry}"

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
