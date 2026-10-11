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
from datetime import UTC, date, datetime, time, timedelta, timezone

from pydantic import ValidationError
from sqlalchemy import case, func, or_, select

from . import (
    academic,
    ai,
    dates,
    faculty,
    google,
    lms,
    mail,
    matching,
    naming,
    rules,
    subject_link,
    targeting,
)
from .classroom_time import due_at
from .common import work
from .config import GMAIL_LOOKBACK, settings
from .domain import effective_status, task_data, window_derived
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

VERSION = "phase3-interpret-4"
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
TASK_FIELDS = {f.alias for f in TaskInput.model_fields.values()}
TASK_DEFAULTS = {f.alias: f.default for f in TaskInput.model_fields.values() if not f.is_required()}
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
    tentative: bool = False
    # Classroom only: "coursework" is an item the student turns work in on; "post" is stream text,
    # a material, or further work a coursework description mentions.
    posted_as: str | None = None
    display_title: str | None = None  # Clean name shown to the student (see naming).
    naming: dict | None = None


@dataclass
class Prepared:
    record_id: uuid.UUID
    revision: int
    candidates: list = field(default_factory=list)
    ignore: str | None = None
    paused: str | None = None
    meta: dict = field(default_factory=dict)
    receipt_retry: int = 0
    relink: int = 0  # Times detached work was queued again; keeps its new event keys distinct.
    paused_retry_after: int = 60
    paused_code: str = "AI_UNAVAILABLE"
    text: str = ""  # Source wording the timing is checked against; never stored.
    ref: datetime | None = None


def norm(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def tokens(text):
    return {
        t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t not in {"the", "a", "of", "and", "for"}
    }


IST = timezone(timedelta(hours=5, minutes=30))
DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def utc(value):
    if not value or not isinstance(value, str) or DATE_ONLY.match(value.strip()):
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    # Extraction is told to use +05:30 unless a source states another zone. A model that drops
    # the offset still means India time; discarding the stated time would lose the deadline.
    return (dt if dt.tzinfo else dt.replace(tzinfo=IST)).astimezone(UTC).isoformat()


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
            .limit(200)
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
        relink=snapshot["data"].get("relinkRun", 0),
    )
    try:
        if snapshot["kind"] == "gmail_message":
            gmail_candidates(prepared, snapshot, ctx, token, account_email)
        elif snapshot["kind"] == "classroom_submission":
            submission_candidates(prepared, snapshot)
        else:
            classroom_candidates(prepared, snapshot, ctx, token)
        fill_timing(prepared)
        resolve_subjects(prepared, ctx, snapshot)
        name_candidates(prepared, ctx)
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
        if c.source == "classroom" and c.method == "ai" and c.title:
            # A post in one course can announce another course's work ("COA IA 1" posted in the DBMS
            # course): a title naming one of the student's other subjects, and not this course's,
            # links there.
            named = subject_link.deterministic([c.title], subjects, component)
            if named and named not in pool_ids and not subject_link.deterministic([c.title], pool, component):
                c.subject_id, c.subject_link = named, {"method": "name", "outsideCourse": True}
                continue
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


def name_candidates(prepared, ctx):
    """One naming call per source for the work it adds; a tidy-up when AI is unavailable."""
    work = [c for c in prepared.candidates if c.intent in WORK_INTENTS and c.title and not skipped_post(c)]
    subjects = {s["id"]: s["name"] for s in ctx["subjects"]}
    items = [
        {"key": f"i{n}", "title": c.title, "type": c.task_type, "subject": subjects.get(c.subject_id)}
        for n, c in enumerate(work)
    ]
    names, used_ai = naming.name_titles(items)
    for n, c in enumerate(work):
        c.display_title, c.naming = names.get(f"i{n}"), naming.naming(used_ai)


def compact(d):
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


def relevant_tasks(ctx, source, sections, limit=40):
    """The tracked tasks a source most likely repeats or follows up, for extraction to match against:
    those sharing its words (course, kind, number, topic) first, open work before completed, then the
    most recently updated."""
    text = " ".join(filter(None, [source.get("subject"), source.get("title"), source.get("courseLabel"),
                                  *(s.get("text", "")[:2000] for s in sections)]))  # fmt: skip
    words = tokens(text)
    names = {s["id"]: tokens(" ".join(filter(None, [s["name"], s.get("code"), *(s.get("aliases") or [])])))
             for s in ctx["subjects"]}  # fmt: skip

    def score(item):
        n, t = item
        mine = tokens(" ".join(filter(None, [t["title"], t["assessmentLabel"], t["deliverableLabel"]])))
        mine |= names.get(t["subjectId"], set())
        return (-len(mine & words), bool(t["completed"]), n)

    return [t for _, t in sorted(enumerate(ctx["tasks"]), key=score)[:limit]]


def ai_payload(ctx, source, sections, allowed_subjects=None):
    """Extraction context. It is sent with every source, so only fields extraction uses are kept:
    a full timetable and task list once made even a short reply exceed provider request limits."""
    subjects = [s for s in ctx["subjects"] if not allowed_subjects or s["id"] in allowed_subjects]
    p = ctx["profile"]
    slots = [
        compact(
            {
                "id": s["id"],
                "subjectId": s["subjectId"],
                "weekday": s.get("weekday"),
                "start": (s.get("startTime") or "")[:5],
                "end": (s.get("endTime") or "")[:5],
                "location": s.get("location"),
            }
        )  # fmt: skip
        for s in ctx["slots"]
        if not allowed_subjects or s["subjectId"] in allowed_subjects
    ]
    tasks = [
        compact(
            {
                "id": t["id"],
                "title": t["title"],
                "type": t["type"],
                "subjectId": t["subjectId"],
                "assessmentLabel": t["assessmentLabel"],
                "deliverableLabel": t["deliverableLabel"],
                "due": (t["dueAt"] or "")[:10],
                "completed": t["completed"] or None,
            }
        )  # fmt: skip
        for t in relevant_tasks(ctx, source, sections)
    ]
    return {
        "now": now().isoformat(),
        "student": academic.context(p),
        "note": "The student's single general batch applies to every subject.",
        "subjects": [compact(s) for s in subjects],
        "weeklySlots": slots,
        "candidateTasks": tasks,
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


def thread_sections(decoded_sections, budget=12000):
    """What extraction reads of a message: the sender's own words and forwarded notices first,
    then only the most recent quoted message. Older quoted history is earlier mail DueCare has
    already read on its own, and long threads otherwise exceed provider request limits."""
    out, used, quoted = [], 0, False
    for i, s in enumerate(decoded_sections):
        if s.kind in ("authored", "forwarded"):
            text = s.text[: max(0, budget - used)]
        elif s.kind == "quoted" and not quoted:
            text, quoted = s.text[:3000], True
        else:
            continue
        if not text.strip():
            continue
        used += len(text) if s.kind != "quoted" else 0
        out.append(
            {
                "id": "authored" if s.kind == "authored" else f"quoted-{i}",
                "kind": s.kind,
                "attribution": s.attribution,
                "text": text,
            }
        )
    return out


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
    prepared.text, prepared.ref = decoded.subject + "\n" + decoded.authored_text, occurred
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
    sections = thread_sections(decoded.sections)
    source = {
        "kind": "email",
        "sender": decoded.sender_email,
        "sentAt": occurred.isoformat() if occurred else None,
        "subject": decoded.subject,
        "courseLabel": label.group(1) if label else None,
        "attachments": [a["title"] for a in decoded.attachments][:10],
        "forwarded": forwarded,
    }
    prepared.text = "\n".join([decoded.subject, *(s["text"] for s in sections)])
    extraction, meta = ai.extract(ai_payload(ctx, source, sections))
    prepared.meta.update(meta)
    course = targeting.merge(lms.course_targeting(label.group(1))) if label else {}
    choices = lms_subjects(ctx, label.group(1)) if label else []
    for i, item in enumerate(extraction.items):
        if not grounded_item(item, sections, decoded.subject):
            continue
        cand = from_item(
            item,
            ctx,
            base_choices=choices,
            allowed=None,
            occurred=occurred,
            source="gmail",
            prepared=prepared,
        )
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
    # Relative wording ("tomorrow") is read against the original post, not a later edit.
    posted = parse_dt(utc(item.get("creationTime"))) or occurred
    prepared.text, prepared.ref = "\n".join(filter(None, [item.get("title"), text])), posted
    main = own_item(extraction.items, item.get("title")) if resource == "coursework" else None
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
            prepared=prepared,
        )
        cand.observed = targeting.merge({**it.targeting.model_dump(), "scope": "activity"})
        cand.trusted = True  # The student explicitly linked this course to their subject(s).
        cand.kt_only = cand.kt_only or kt_text(item.get("title"))
        cand.identity_key = snap["provider_id"] if i == main else f"{snap['provider_id']}:{i}"
        cand.links = [data.get("alternateLink")] if data.get("alternateLink") else []
        submittable = resource == "coursework" and item.get("workType") != "MATERIAL"
        cand.posted_as = "coursework" if submittable and i == main else "post"
        structured_due = due_at(item)
        # Only a precise stated time outranks Classroom's own due time; a bare date does not.
        stated = any(cand.timing.get(k) for k in CUTOFFS)
        if (
            i == main
            and structured_due
            # Structured Classroom deadlines (UTC) are authoritative for assignments. For a test
            # they fill in only when the wording gave no time of its own.
            and (cand.task_type == "assignment" or not stated)
        ):
            cand.timing["dueAt"] = structured_due.isoformat()
            cand.mode, cand.date_only, cand.window = "deadline_only", None, None
            cand.provenance["dueAt"] = {
                "basis": "source-exact",
                "timezone": "UTC",
                "phrase": "Classroom due date",
            }
        if cand.intent == "submission":
            cand.intent = "supporting"  # Only the student's own submission state proves Classroom turn-in.
        prepared.candidates.append(cand)
    if resource == "coursework" and not any(
        c.intent in WORK_INTENTS and c.identity_key == snap["provider_id"] for c in prepared.candidates
    ):
        # No extracted item is the coursework itself (a bare title, or a description listing other
        # tasks): keep it from Classroom's own fields unless extraction deliberately set it aside.
        fallback = structured_coursework(
            item, snap, ctx, occurred, silent=main is None or not extraction.items
        )
        if fallback:
            prepared.candidates = [c for c in prepared.candidates if c.identity_key != fallback.identity_key]
            prepared.candidates.insert(0, fallback)


def own_item(items, title):
    """Which extracted item is the coursework itself. A description can list other work first
    ("IA 1.8" mentioning "IA1.3"), so position alone does not say; a lone work item still does."""
    for match in (lambda t: norm(t) == norm(title), lambda t: same_title(t, title)):
        found = [i for i, it in enumerate(items) if it.title and match(it.title)]
        if found:
            return found[0]
    work = [i for i, it in enumerate(items) if it.intent in WORK_INTENTS]
    return work[0] if len(items) == 1 and work else None


TEST_WORDS = re.compile(r"\b(quiz|test|exam|examination|viva|mcq|practical exam)\b", re.I)
# What a Classroom post may add as new work (student decision): assessments, tutorials, projects and
# presentations. Ordinary work such as experiments and write-ups comes from Classroom only as
# coursework with a turn-in slot, never from stream text or materials.
CLASSROOM_POST_WORK = re.compile(
    r"\b(tutorials?|tut\s?-?\d+|quiz(?:zes)?|mcqs?|tests?|ia\s?-?\d*(?:\.\d+)?|internal assessments?|"
    r"exams?|examinations?|viva|orals?|ost|ese|mse|ise|mid-?terms?|mid-?sems?|end-?sems?|"
    r"(?:mini[\s-]?)?projects?|presentations?)\b",
    re.I,
)


def classroom_post_work(cand):
    return bool(CLASSROOM_POST_WORK.search(" ".join(filter(None, [cand.title, cand.assessment_label]))))


def skipped_post(cand):
    """New work a Classroom post states but the post rule does not add (see CLASSROOM_POST_WORK)."""
    return cand.posted_as == "post" and cand.intent in WORK_INTENTS and not classroom_post_work(cand)


def structured_coursework(item, snap, ctx, occurred, silent):
    """Coursework in a linked course is the student's own work. When extraction yields nothing
    actionable (a bare title, an empty description), keep it from Classroom's own fields rather
    than silently dropping it. Materials and undated posts the model set aside stay ignored."""
    due = due_at(item)
    work_type = item.get("workType")
    if work_type == "MATERIAL" or not (item.get("title") or "").strip():
        return None
    # A Classroom due date settles that this is work to submit; without one, only stand in when
    # extraction returned nothing at all, never over its deliberate "supporting" verdict.
    if not due and not (
        silent and work_type in ("ASSIGNMENT", "SHORT_ANSWER_QUESTION", "MULTIPLE_CHOICE_QUESTION")
    ):
        return None
    title = item["title"].strip()[:300]
    cand = Cand(
        intent="new_work",
        task_type="test" if TEST_WORDS.search(title) else "assignment",
        title=title,
        subject_choices=list(ctx["mapped"]),
        subject_id=ctx["mapped"][0] if len(ctx["mapped"]) == 1 else None,
        trusted=True,
        occurred_at=occurred,
        method="classroom_structured",
        source="classroom",
        excerpt=title,
        kt_only=kt_text(title),
        identity_key=snap["provider_id"],
        links=[snap["data"]["alternateLink"]] if snap["data"].get("alternateLink") else [],
        posted_as="coursework",
    )
    if due:
        cand.timing["dueAt"] = due.isoformat()
        cand.mode = "deadline_only"
        cand.provenance["dueAt"] = {
            "basis": "source-exact",
            "timezone": "UTC",
            "phrase": "Classroom due date",
        }
    return cand


# --- Timing ------------------------------------------------------------------------------------

WORK_INTENTS = ("new_work", "revision", "due_notice")
CUTOFFS = ("dueAt", "availabilityClosesAt", "startsAt")
# Wording that states a time of day without a clock figure; such a time is not invented.
TIME_WORDS = re.compile(r"\b(midnight|tonight|eod|end of (?:the )?day|morning|afternoon|evening)\b", re.I)


def as_date(value):
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def has_timing(cand):
    return bool(cand.date_only or cand.window or any(cand.timing.get(k) for k in CUTOFFS))


def settle_timing(cand, text, ref, raw=None):
    """Make extracted timing consistent before validation, keeping every date the source states.

    Models sometimes read 10/8/26 month first, copy one time into every role, invent a midnight for
    a date-only notice, or add a window beside an exact time. Each is settled here, so one bad
    field cannot make the whole schedule invalid and leave the work without a date."""
    day = (ref or now()).astimezone(IST).date()
    words = " ".join(filter(None, [text, cand.title, cand.excerpt]))
    t = cand.timing
    for name, value in list(t.items()):
        local = parse_dt(value).astimezone(IST)
        fixed = dates.day_first(local.date(), words, day)
        if fixed != local.date():
            t[name] = datetime.combine(fixed, local.timetz()).astimezone(UTC).isoformat()
    if cand.date_only:
        fixed = dates.day_first(as_date(cand.date_only), words, day)
        cand.date_only = fixed.isoformat() if fixed else None
    if cand.window:
        start, end = (as_date(v) for v in cand.window)
        start, end = (dates.day_first(v, words, day) if v else None for v in (start, end))
        cand.window = tuple(sorted((start, end))) if start and end else None
    choices = sorted({d for d in (as_date(a) for a in cand.alternatives) if d})
    if choices and not cand.window and not has_timing(cand):
        # Tentative dates still bound the work: keep them as the range of possible days.
        if len(choices) == 1:
            cand.date_only = choices[0].isoformat()
        else:
            cand.window = (choices[0], choices[-1])
        cand.alternatives = []
    if cand.window:
        start, end = cand.window
        cand.window = None if start == end else (start.isoformat(), end.isoformat())
        if start == end and not cand.date_only:
            cand.date_only = start.isoformat()

    def at(name):
        return parse_dt(t[name]) if t.get(name) else None

    # Only times the source states survive; a model that wrote one value into every role, or a role
    # ordering that cannot hold, loses the repeated or impossible copy rather than the whole schedule.
    if at("startsAt") and at("endsAt") and at("endsAt") <= at("startsAt"):
        t.pop("endsAt")
    if (
        at("availabilityOpensAt")
        and at("availabilityClosesAt")
        and at("availabilityOpensAt") >= at("availabilityClosesAt")
    ):
        t.pop("availabilityOpensAt")
    if at("submissionOpensAt") and at("dueAt") and at("submissionOpensAt") >= at("dueAt"):
        t.pop("submissionOpensAt")
    for name in ("loginByAt", "reportingAt"):
        if at(name) and at("startsAt") and at(name) > at("startsAt"):
            t.pop(name)
    if cand.task_type == "test" and at("startsAt"):
        if at("availabilityClosesAt") and at("availabilityClosesAt") <= at("startsAt"):
            t.pop("availabilityClosesAt")
            t.pop("availabilityOpensAt", None)
    if cand.task_type != "test" and not t.get("dueAt"):
        # Work to submit is due at the time stated for it, whichever role the model chose.
        name = next((n for n in ("availabilityClosesAt", "endsAt", "startsAt") if t.get(n)), None)
        if name:
            t["dueAt"] = t[name]
            if name in cand.provenance:
                cand.provenance["dueAt"] = cand.provenance[name]
    raw = raw or {}
    stated = [n for n in CUTOFFS if t.get(n) and raw.get(n)]
    if stated and text and not dates.find_times(words) and not TIME_WORDS.search(words):
        # The source states no time of day at all, so the model's clock is invented: keep its date
        # as written (a midnight-UTC guess must not become 5:30 am the same day).
        written = as_date(raw[stated[0]])
        if not cand.window:
            cand.date_only = cand.date_only or (written.isoformat() if written else None)
        t.clear()
    if cand.date_only and any(t.get(n) for n in CUTOFFS):
        local = parse_dt(t[next(n for n in CUTOFFS if t.get(n))]).astimezone(IST)
        if (
            local.date().isoformat() == cand.date_only
            and local.time() != time(0, 0)
            and (dates.find_times(words) or TIME_WORDS.search(words))
        ):
            cand.date_only = None  # A stated time on that very date is more precise.
    if cand.window and (cand.date_only or any(t.get(n) for n in CUTOFFS)):
        cand.window = None  # A stated date settles the range it falls in.
    if has_timing(cand) and cand.question and TIMING_DOUBT.search(cand.question):
        # A doubted date is still the best date known. Keep it, widened to any other day the doubt
        # names ("25 or 26 October?"), and mark it tentative rather than leaving the work undated.
        known = [as_date(cand.date_only)] if cand.date_only else []
        known += [as_date(v) for v in cand.window or ()]
        known += [parse_dt(t[n]).astimezone(IST).date() for n in CUTOFFS if t.get(n)]
        named = sorted({*known, *dates.find_dates(cand.question, day)} - {None})
        if len(named) > 1:
            t.clear()
            cand.date_only, cand.window = None, (named[0].isoformat(), named[-1].isoformat())
        cand.tentative = True
    if has_timing(cand):
        # Validation infers the mode from the roles the source states; a model's "unresolved"
        # label beside a stated date must not discard that date.
        cand.mode = None


def found_timing(cand, day, clock, phrase, method, role=None):
    if clock:
        # A dated time for a test is when it is held, unless the source says it is due by then.
        name = "startsAt" if cand.task_type == "test" and role != "due" else "dueAt"
        cand.timing[name] = dates.at_ist(day, clock).astimezone(UTC).isoformat()
        cand.provenance[name] = {
            "basis": "source-exact",
            "timezone": "Asia/Kolkata",
            "phrase": (phrase or "")[:200],
            "method": method,
        }
    else:
        cand.date_only = day.isoformat()
        cand.provenance["dueDate"] = {
            "basis": "source-exact",
            "phrase": (phrase or "")[:200],
            "method": method,
        }
    cand.mode = None


def resolved_timing(cand, r, text, ref):
    """Accept a timing-pass answer only when its phrase is in the source and states that date."""
    if r.kind == "none" or not r.phrase:
        return
    if lms.flat(r.phrase).casefold() not in lms.flat(text).casefold():
        return
    day = ref.astimezone(IST).date()
    stated = dates.find_dates(r.phrase, day)

    def checked(value):
        value = dates.day_first(as_date(value), r.phrase, day) if value and as_date(value) else None
        if not value or (stated and value not in stated):
            return None
        return value if day - timedelta(days=200) <= value <= day + timedelta(days=400) else None

    if r.kind == "window":
        start, end = checked(r.windowStart), checked(r.windowEnd)
        if start and end:
            start, end = sorted((start, end))
            if start == end:
                found_timing(cand, start, None, r.phrase, "timing-pass")
            else:
                cand.window, cand.mode = (start.isoformat(), end.isoformat()), None
                cand.provenance["dateWindowEnd"] = {"basis": "source-exact", "phrase": r.phrase[:200]}
        return
    exact = parse_dt(utc(r.at)) if r.kind == "exact" else None
    value = checked(exact.astimezone(IST).date().isoformat() if exact else r.date)
    if not value:
        return
    clock = exact.astimezone(IST).timetz().replace(tzinfo=None) if exact else None
    if clock and clock not in dates.find_times(r.phrase) and not TIME_WORDS.search(r.phrase):
        clock = None  # A time the phrase does not state is not kept.
    found_timing(cand, value, clock, r.phrase, "timing-pass", r.role)


def fill_timing(prepared):
    """Work whose extraction carried no date gets one more, timing-only look at its own source: first
    its own words, then one focused AI call. Nothing is filled from a source that states no date, and
    a doubt the source raises about timing is never overridden."""
    ref = prepared.ref or now()
    day = ref.astimezone(IST).date()
    pending = []
    for c in prepared.candidates:
        if c.intent not in WORK_INTENTS or not c.task_type or has_timing(c) or skipped_post(c):
            continue
        if c.question and TIMING_DOUBT.search(c.question):
            continue
        for words in (" ".join(filter(None, [c.title, c.excerpt])), c.title, c.excerpt):
            found = dates.single(words or "", day)
            if found:
                found_timing(c, *found, words, "source-date")
                break
        else:
            pending.append(c)
    if not pending or not prepared.text or not dates.mentions_timing(prepared.text, day):
        return
    payload = {
        "sentAt": ref.isoformat(),
        "text": prepared.text[:12000],
        "items": [
            {"key": f"i{n}", "title": c.title, "type": c.task_type, "evidence": (c.excerpt or "")[:300]}
            for n, c in enumerate(pending)
        ],
    }
    try:
        result, meta = ai.resolve_timing(payload)
    except ai.AIUnavailable:
        # Keep the work; the timing look is retried by the undated-work repair on a later sync.
        prepared.meta = {**prepared.meta, "timingPass": {"used": False, "unavailable": True}}
        return
    prepared.meta = {
        **prepared.meta,
        "timingPass": {"used": True, **meta, "prompt": ai.TIMING_PROMPT_VERSION},
    }
    answers = {r.key: r for r in result.items}
    for n, c in enumerate(pending):
        if f"i{n}" in answers:
            resolved_timing(c, answers[f"i{n}"], prepared.text, ref)


def classroom_status(db, task, record, cand):
    """What Classroom shows for the student's own turn-in: state, late, and a returned grade."""
    v = cand.validation or {}
    work = db.scalar(
        select(SourceRecord).where(
            SourceRecord.connection_id == record.connection_id,
            SourceRecord.provider_id == cand.identity_key,
        )
    )
    status = {
        "state": v.get("state"),
        "late": v.get("late", False),
        "grade": v.get("grade"),
        "maxPoints": (work.data.get("maxPoints") if work else None),
        "at": v.get("stateTime"),
    }
    if task.data.get("classroom") != status:
        task.data = {**task.data, "classroom": status}


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
            validation={
                "ownSubmission": True,
                "state": state,
                "stateTime": at.isoformat() if at else None,
                "late": bool(data.get("late")),
                "grade": data.get("assignedGrade"),
            },
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


def from_item(item, ctx, base_choices, allowed, occurred, source, prepared=None):
    owned = {s["id"] for s in ctx["subjects"]}
    subject = (
        item.subjectId if item.subjectId in owned and (not allowed or item.subjectId in allowed) else None
    )
    task_ids = {t["id"] for t in ctx["tasks"]}
    t = item.timing
    timing, provenance, question = {}, {}, item.question
    date_only = t.dateOnly if t.dateOnly and DATE_ONLY.match(t.dateOnly) else None
    for name in TIMING_FIELDS:
        value = getattr(t, name)
        if value and isinstance(value, str) and DATE_ONLY.match(value.strip()):
            # A bare date in a precise field states no time: keep it as the date-only deadline.
            if name in ("dueAt", "availabilityClosesAt", "startsAt") and not date_only:
                date_only = value.strip()
            continue
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
    window = (t.dateWindowStart, t.dateWindowEnd) if t.dateWindowStart and t.dateWindowEnd else None
    cand = Cand(
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
    raw = {name: getattr(t, name) for name in TIMING_FIELDS}
    settle_timing(cand, prepared.text if prepared else "", prepared.ref if prepared else occurred, raw)
    return cand


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
    """Conservative assessment name within one course; IA1 and IA2 remain distinct.

    Dates, times and scheduling words in a title ("scheduled on 28/09/2026 at 1:30 pm") say when the
    work happens, not which work it is, so they are not part of its name."""
    text = naming.undated(naming.PREFIX.sub("", title or "")).casefold()
    names = [subject["name"], subject.get("code"), *(subject.get("aliases") or [])]
    for key, aliases in subject_link.COURSE_NAMES.items():
        if {norm(n) for n in names if n} & {norm(key), *(norm(n) for n in aliases)}:
            names.extend([key, *aliases])
    for name in sorted(filter(None, names), key=len, reverse=True):
        text = re.sub(r"(?<!\w)" + re.escape(name.casefold()) + r"(?!\w)", " ", text)
    text = re.sub(r"\bia\s*[- ]?\s*(\d+)\b", r"ia\1", text)
    words = set(re.findall(r"[a-z]+\d*|\d+", text)) - naming.FILLER - {"regarding", "re", "fwd", "fw"}
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


CUTOFF_FIELDS = ("dueAt", "startsAt", "availabilityClosesAt")
# Targeting that is only missing (not conflicting): a tracked work's copy may settle it.
UNSTATED_AUDIENCE = ("audience not stated", "lab batch not stated")
TRACKED_COPY = "same work already tracked"


def cand_day(cand):
    """The calendar day (IST) a candidate's work is due or held, if it states one."""
    for name in CUTOFF_FIELDS:
        if cand.timing.get(name):
            return parse_dt(cand.timing[name]).astimezone(IST).date()
    if cand.date_only:
        return as_date(cand.date_only)
    return as_date(cand.window[1]) if cand.window else None


def task_day(task):
    return task.due_at.astimezone(IST).date() if task.due_at else None


def exact_time(task):
    """The task's stated time, when it has one (not a date-only or window cutoff)."""
    return (
        task.due_at
        if task.due_at and not task.data.get("dueDate") and not window_derived(task.data)
        else None
    )


def curated(task):
    """A task whose name or timing the student set is theirs; it is never joined automatically."""
    return bool({"title", "dueAt", "dueDate", "startsAt"} & set(task.data.get("manualFieldOverrides") or {}))


# A notice of one piece of work never moves it further than this; beyond it, it is other work.
MAX_DAY_GAP = 60


def notice_signature(ctx, subject_id, title, *labels):
    subject = next((s for s in ctx["subjects"] if s["id"] == subject_id), None) if subject_id else None
    return matching.signature(title, *labels, subject=subject)


def task_signature(ctx, task):
    data = task.data
    subject_id = str(task.subject_id) if task.subject_id else None
    return notice_signature(
        ctx, subject_id, task.title, data.get("assessmentLabel"), data.get("deliverableLabel")
    )


def cand_signature(ctx, cand, subject_id):
    return notice_signature(ctx, subject_id, cand.title, cand.assessment_label, cand.deliverable_label)


def stated_time(cand):
    stated = next((cand.timing[n] for n in CUTOFF_FIELDS if cand.timing.get(n)), None)
    return parse_dt(stated) if stated else None


def same_notice(level, theirs, day, at, task_at, moved_ok, hinted=False, strict=False):
    """Whether a notice at this match level (see matching.compare) is the task's work, given the
    days both state. A changed date is an update of the same work, never a second task; update_task
    then lets only the newest source's timing stand."""
    if level == matching.DIFFERENT:
        return False
    moved = day is not None and theirs is not None and day != theirs
    if moved and abs((day - theirs).days) > MAX_DAY_GAP:
        return False
    if strict:
        return level == matching.SAME and not moved
    if level == matching.SAME or hinted:
        return True
    if level == matching.LIKELY:
        return not moved or moved_ok
    if level == matching.GENERIC:
        same_time = at is None or task_at is None or at == task_at
        return day is not None and theirs is not None and not moved and same_time
    return False


def notice_matches(cand, task, level, hinted=False, strict=False):
    rescheduled = cand.intent == "revision" or matching.says_rescheduled(
        cand.title, cand.excerpt, cand.instructions
    )
    return same_notice(
        level,
        task_day(task),
        cand_day(cand),
        stated_time(cand),
        exact_time(task),
        rescheduled,
        hinted,
        strict,
    )


def own_coursework(cand):
    key = cand.identity_key or ""
    return key if ":coursework:" in key and not re.search(r":\d+$", key) else None


def precision(db, task):
    """The most precise of several tasks for one work: a Classroom assignment, a stated time, the oldest."""
    return (not coursework_identity(db, task), exact_time(task) is None, task.created_at)


def find_same_work(db, uid, cand, subject_id, ctx, strict=False):
    """The tracked task this notice announces again, or None.

    Two or three faculty mailing the same notice, a resend, a reminder, a follow-up or a moved
    deadline all name the same work: same subject, same task type, the same kind, identifiers and
    topic (see matching). The sender and the wording never matter. A task the extraction suggested
    (matchTaskId) is accepted when nothing contradicts it. strict (the notice's audience is not
    confirmed): only an identical work with no date change counts."""
    if not cand.task_type or not cand.title:
        return None
    subjects = {subject_id} if subject_id else set(cand.subject_choices or [])
    hint = cand.match_task_id
    scope = [Task.subject_id.is_(None)]
    if subjects:
        scope.append(Task.subject_id.in_([uuid.UUID(s) for s in subjects]))
    else:
        scope.append(Task.subject_id.is_not(None))  # No subject named: see the guard below.
    if hint:
        scope.append(Task.id == uuid.UUID(hint))
    own = own_coursework(cand)
    day = cand_day(cand)
    found = []
    for task in db.scalars(
        select(Task)
        .where(
            Task.user_id == uid,
            Task.type == cand.task_type,
            Task.data["mergedInto"].astext.is_(None),
            or_(*scope),
        )
        .order_by(Task.created_at)
        .with_for_update()
    ):
        theirs = str(task.subject_id) if task.subject_id else None
        if subject_id and theirs and theirs != subject_id:
            continue  # A suggested task of another subject is other work.
        hinted = str(task.id) == hint and not strict
        level = matching.compare(cand_signature(ctx, cand, subject_id or theirs), task_signature(ctx, task))
        if not (subject_id and theirs) and level != matching.SAME and not hinted:
            continue  # Across an unknown subject, only identical work counts.
        if theirs and theirs not in subjects and not hinted and (day is None or day != task_day(task)):
            continue  # Naming no subject, "Exp 5" is another lab's too unless the same day is stated.
        if curated(task) and level != matching.SAME and not hinted:
            continue  # The student renamed or retimed it: its title no longer speaks for the source.
        if own and (coursework_identity(db, task) - {own}):
            continue  # Two Classroom assignments that happen to share a name.
        if notice_matches(cand, task, level, hinted, strict):
            found.append((not hinted, matching.RANK[level], task))
    if not found:
        return None
    found.sort(key=lambda f: (f[0], f[1]))
    unhinted, rank, best = found[0]
    if not unhinted:
        return best
    ties = [task for _, r, task in found if r == rank]
    if len({t.subject_id for t in ties}) > 1:
        return None  # The same name in two subjects: the notice does not say which.
    if rank == matching.RANK[matching.SAME]:
        return min(ties, key=lambda t: precision(db, t))  # Already listed twice; the sweep joins them.
    return best if len(ties) == 1 else None


def coursework_identity(db, task):
    """The Classroom coursework a task is, if any: two different coursework items are never merged."""
    return {
        key
        for key in db.scalars(
            select(SourceEvent.identity_key)
            .join(TaskEvidence, TaskEvidence.event_id == SourceEvent.id)
            .where(TaskEvidence.task_id == task.id, TaskEvidence.state == "active")
        )
        if key and ":coursework:" in key and not re.search(r":\d+$", key)
    }


def relink_named_subjects(db, uid):
    """Classroom work linked to its course's subject although its title names another of the
    student's subjects (see resolve_subjects) moves to the named subject. A subject the student
    chose stays."""
    subjects = [
        {"id": str(s.id), "name": s.name, "kind": s.kind, "code": s.data.get("code"),
         "aliases": s.data.get("aliases", [])}
        for s in db.scalars(select(Subject).where(Subject.user_id == uid))
    ]  # fmt: skip
    moved = 0
    for task in db.scalars(
        select(Task)
        .where(Task.user_id == uid, Task.subject_id.is_not(None), Task.data["mergedInto"].astext.is_(None))
        .with_for_update()
    ):
        if "classroom" not in (task.data.get("sources") or []) or "subjectId" in (
            task.data.get("manualFieldOverrides") or {}
        ):
            continue
        current = [s for s in subjects if s["id"] == str(task.subject_id)]
        named = subject_link.deterministic([task.title], subjects)
        if not named or named == str(task.subject_id) or subject_link.deterministic([task.title], current):
            continue
        before = str(task.subject_id)
        task.subject_id = uuid.UUID(named)
        task.data = {
            **task.data,
            "subjectId": named,
            "subjectLink": {"method": "name", "outsideCourse": True},
            "timingProvenance": {
                **(task.data.get("timingProvenance") or {}),
                "subjectId": {"basis": "title-named", "sourceTime": now().isoformat()},
            },
        }
        task.revision += 1
        history(db, task, "source_update", {"subjectId": named, "previousSubjectId": before})
        moved += 1
    return moved


def merge_duplicates(db, uid):
    """Join tasks already listed twice for the same work: a notice by mail and one on Classroom, or
    copies of one notice from several faculty. The survivor takes the newest source's details.
    Each merge can be undone."""
    from . import merging

    ctx = None
    tasks = db.scalars(
        select(Task)
        .where(Task.user_id == uid, Task.subject_id.is_not(None), Task.data["mergedInto"].astext.is_(None))
        .order_by(Task.created_at)
        .with_for_update()
    ).all()
    groups = {}
    for task in tasks:
        if task.data.get("sources") and not curated(task):
            groups.setdefault((task.subject_id, task.type), []).append(task)
    merged = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        if ctx is None:
            ctx = {"subjects": [{"id": str(s.id), "name": s.name, "code": s.data.get("code"),
                                 "aliases": s.data.get("aliases", [])}
                                for s in db.scalars(select(Subject).where(Subject.user_id == uid))]}  # fmt: skip
        group.sort(key=lambda t: precision(db, t))
        signatures = {t.id: task_signature(ctx, t) for t in group}
        gone = set()
        for i, keep in enumerate(group):
            if keep.id in gone:
                continue
            for other in group[i + 1 :]:
                if other.id in gone:
                    continue
                level = matching.compare(signatures[keep.id], signatures[other.id])
                # Two tasks carry no "this notice says the date moved"; differing days join only
                # when the work is identical by name.
                if not same_notice(
                    level, task_day(other), task_day(keep), exact_time(keep), exact_time(other), False
                ):
                    continue
                mine, theirs = coursework_identity(db, keep), coursework_identity(db, other)
                if mine and theirs and mine != theirs:
                    continue  # Two Classroom assignments that happen to share a name.
                operation = merging.merge(
                    db,
                    keep,
                    other,
                    lambda task, action, changes: history(
                        db, task, action, {**changes, "reason": "same work"}
                    ),
                )
                adopted = adopt_newer(db, keep, operation.data["movedEvents"])
                if adopted:
                    operation.data = {**operation.data, "adopted": adopted}
                settle_reviews(db, keep, ("possible_duplicate",), "same_work_merged")
                settle_reviews(db, other, ("possible_duplicate",), "same_work_merged")
                gone.add(other.id)
                merged += 1
    return merged


ADOPTED_FIELDS = (*sorted(TASK_FIELDS), "timingProvenance", "displayTitle", "naming", "timingTentative")


def adopt_newer(db, keep, event_ids):
    """Replay a merged-in task's notices on the survivor. Field clocks let only values newer than the
    survivor's own stand (a moved deadline, a renamed title); manual edits and completion are kept.
    Returns {"before", "after"} for the fields it changed, so undoing the merge can restore them."""
    if not event_ids:
        return None
    before = {k: keep.data.get(k) for k in ADOPTED_FIELDS}
    events = db.scalars(
        select(SourceEvent).where(
            SourceEvent.user_id == keep.user_id,
            SourceEvent.id.in_([uuid.UUID(e) for e in event_ids]),
            SourceEvent.event_type.in_(WORK_INTENTS),
            SourceEvent.outcome.in_(("created", "updated", "evidence_recorded", "accepted", "linked")),
        )
    ).all()
    for event in sorted(events, key=lambda e: source_order(db, e)):
        record = db.get(SourceRecord, event.source_record_id)
        if not record:
            continue
        cand = candidate_from_event(event, record)
        cand.subject_id = str(keep.subject_id) if keep.subject_id else None
        owner = event.task_id
        update_task(db, keep, cand, event, True, cand.method, retitle=False)
        event.task_id = owner  # The evidence moved with the merge; undoing it moves it back.
    changed = [k for k in ADOPTED_FIELDS if keep.data.get(k) != before[k]]
    if not changed:
        return None
    return {"before": {k: before[k] for k in changed}, "after": {k: keep.data.get(k) for k in changed}}


def restore_fields(task, adopted):
    """Undo adopt_newer when the survivor still holds exactly what the merge gave it."""
    if not adopted or any(task.data.get(k) != v for k, v in adopted["after"].items()):
        return False
    task.data = {**task.data, **adopted["before"]}
    task.due_at = parse_dt(task.data["dueAt"]) if task.data.get("dueAt") else None
    task.title, task.type = task.data.get("title") or task.title, task.data.get("type") or task.type
    return True


ANSWERED_BY_TRACKING = ("possible_duplicate", "confirm_applicability", "association")
ANSWERED_BY_COMPLETION = ("confirm_completion", "receipt_unverified", "returned_ambiguous")


def tidy_reviews(db, uid):
    """Close questions that are already answered, so Needs attention holds only real decisions:
    the work is now tracked, the suggested duplicate now safely matches, the task is already
    completed (or already open, for an unsubmission). A question about a merged task follows it."""
    closed, ctx = 0, None
    for item in db.scalars(
        select(ReviewItem).where(ReviewItem.user_id == uid, ReviewItem.status == "open").with_for_update()
    ):
        task = db.get(Task, item.task_id) if item.task_id else None
        while task is not None and task.data.get("mergedInto"):
            task = db.get(Task, uuid.UUID(task.data["mergedInto"]))
            item.task_id = task.id if task else None
        reason = None
        identity = item.data.get("identityKey")
        if item.issue_type in ANSWERED_BY_TRACKING and identity:
            tracked = task_by_identity(db, uid, identity)
            if tracked is not None and not tracked.data.get("mergedInto"):
                reason = "already_tracked"
        if (
            not reason
            and item.issue_type in ANSWERED_BY_COMPLETION
            and task is not None
            and task.completed_at
        ):
            reason = "already_completed"
        if not reason and item.issue_type == "unsubmission" and task is not None and not task.completed_at:
            reason = "already_open"
        if not reason and item.issue_type == "possible_duplicate" and task is not None and item.event_id:
            event = db.get(SourceEvent, item.event_id)
            record = db.get(SourceRecord, item.source_record_id) if item.source_record_id else None
            if event is not None and record is not None:
                cand = candidate_from_event(event, record, item.data.get("proposal"))
                subject_id = cand.subject_id or (str(task.subject_id) if task.subject_id else None)
                if ctx is None:
                    ctx = load_context(db, uid, record)
                level = matching.compare(cand_signature(ctx, cand, subject_id), task_signature(ctx, task))
                if (
                    subject_id
                    and subject_id == (str(task.subject_id) if task.subject_id else None)
                    and cand.task_type == task.type
                    and not curated(task)
                    and notice_matches(cand, task, level)
                ):
                    changes, _ = update_task(db, task, cand, event, False, cand.method, retitle=False)
                    event.outcome = "updated" if changes else "evidence_recorded"
                    reason = "same_work_linked"
        if reason:
            item.status, item.resolved_at = "resolved", now()
            item.revision += 1
            item.data = {
                **item.data,
                "resolution": {"action": reason, "at": now().isoformat(), "automatic": True},
            }
            closed += 1
    return closed


def rule_rows(db, uid):
    return [
        {"id": str(r.id), "name": r.name, "enabled": r.enabled, "data": r.data}
        for r in db.scalars(
            select(Rule).where(Rule.user_id == uid, Rule.enabled.is_(True)).order_by(Rule.position)
        )
    ]


def task_facts(db, task):
    """What rules see of a task: every source and sender it came from, its subject and words."""
    subject = db.get(Subject, task.subject_id) if task.subject_id else None
    senders = set(
        db.scalars(
            select(SourceRecord.sender_email)
            .join(SourceEvent, SourceEvent.source_record_id == SourceRecord.id)
            .join(TaskEvidence, TaskEvidence.event_id == SourceEvent.id)
            .where(
                TaskEvidence.task_id == task.id,
                TaskEvidence.state == "active",
                SourceRecord.sender_email.is_not(None),
            )
        )
    )
    data = task.data
    return {
        "source": data.get("sources") or ["manual"],
        "sender": sorted(senders),
        "subjectId": str(task.subject_id) if task.subject_id else None,
        "subjectKind": subject.kind if subject else None,
        "taskType": task.type,
        "assessmentLabel": data.get("assessmentLabel"),
        "text": " ".join(
            filter(
                None,
                [
                    task.title,
                    data.get("displayTitle"),
                    data.get("assessmentLabel"),
                    data.get("deliverableLabel"),
                ],
            )
        ),
    }


def apply_rules_to(db, task, rows):
    """Set the task's rule priority and hidden state from the current rules. Only imported work is
    hidden; a task the student created stays visible. True when anything changed."""
    relevance, level, matched = rules.evaluate(rows, task_facts(db, task))
    data = {k: v for k, v in task.data.items() if k not in ("rulePriority", "hiddenByRule")}
    if level:
        data["rulePriority"] = {"value": level, "ruleId": matched["priority"]}
    if relevance == "exclude" and task.data.get("sources"):
        name = next((r["name"] for r in rows if r["id"] == matched["relevance"]), None)
        data["hiddenByRule"] = {"ruleId": matched["relevance"], "name": name}
    if data == task.data:
        return False
    task.data = data
    return True


def reapply_rules(db, uid):
    """Rules describe all work, not only future imports: re-apply them after any rule change."""
    rows = rule_rows(db, uid)
    tasks = db.scalars(
        select(Task).where(Task.user_id == uid, Task.data["mergedInto"].astext.is_(None)).with_for_update()
    ).all()
    return sum(apply_rules_to(db, task, rows) for task in tasks)


def similar_task(db, uid, cand, subject_id, ctx):
    """Similarity never merges; it only asks the student. Contradicting identifiers, kinds or a
    re-test against the regular sitting stay separate without a question."""
    if not cand.title:
        return None
    mine = cand_signature(ctx, cand, subject_id)
    generic = []
    for t in db.scalars(
        select(Task)
        .where(
            Task.user_id == uid,
            Task.type == cand.task_type,
            Task.subject_id == (uuid.UUID(subject_id) if subject_id else None),
            Task.data["mergedInto"].astext.is_(None),
        )
        .order_by(Task.created_at)
    ):
        level = matching.compare(mine, task_signature(ctx, t))
        if level in (matching.SAME, matching.LIKELY, matching.POSSIBLE):
            return t
        if level == matching.GENERIC and not t.completed_at:
            generic.append(t)
    # "Submit your DBMS assignment" on another day: ask only when one open task could be meant.
    return generic[0] if len(generic) == 1 else None


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
        # Older saved proposals can hold full timestamps here; a window is calendar days.
        days = [as_date(v) for v in cand.window]
        if all(days):
            out["dateWindowStart"], out["dateWindowEnd"] = (d.isoformat() for d in days)
    if cand.date_only:
        out["dueDate"] = cand.date_only
    return source_fields({k: v for k, v in out.items() if v not in (None, "")})


def source_fields(fields):
    """A stated date without a source time uses the local end-of-day default."""
    fields = dict(fields)
    if fields.get("dueDate"):
        # Models sometimes return both dateOnly and an invented midnight timestamp.
        # dateOnly records that no exact time was supplied; keep that distinction.
        for key in ("dueAt", "startsAt", "endsAt", "availabilityOpensAt", "availabilityClosesAt"):
            fields.pop(key, None)
        fields["timingMode"] = "deadline_only"
    return fields


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
        question=data.get("question"),
        posted_as=data.get("postedAs"),
        display_title=data.get("displayTitle"),
        naming=data.get("naming"),
        # A schedule the student changed from the source's proposal is no longer the source's doubt.
        tentative=bool(data.get("tentative"))
        and all(values.get(k) == data.get("proposal", {}).get(k) for k in SCHEDULE_FIELDS),
    )


def task_input(fields):
    """Validate a source proposal through the same contract as manual tasks."""
    allowed = {f.alias for f in TaskInput.model_fields.values()}
    clean = source_fields({k: v for k, v in fields.items() if k in allowed})
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


TIMING_DOUBT = re.compile(
    r"\b(date|dates|day|days|time|times|timing|when|deadline|schedule[ds]?|session|slot|start|starts|"
    r"close|closes|window|reschedul\w*|postpon\w*|tentative)\b",
    re.I,
)


def unresolved(cand):
    """Timing the source does not settle: never invent a slot, date, or start time.

    A stated date is always kept: a doubt about it marks it tentative (see settle_timing), and a
    stated range of days is due by its last day, shown as the whole range. Only work whose source
    gives no date at all is left without one."""
    if has_timing(cand):
        return None
    if cand.question and TIMING_DOUBT.search(cand.question):
        return cand.question
    if cand.alternatives:
        return "The notice gives tentative alternatives. Which date applies?"
    if cand.mode == "unresolved" and not has_timing(cand):
        return "The source does not settle the timing for this work."
    return None


def undated_fields(fields):
    """Keep the obligation without accepting any uncertain date or time."""
    return {**{k: v for k, v in fields.items() if k not in SCHEDULE_FIELDS}, "timingMode": "undated"}


def schedule_fallbacks(values):
    """When a stated schedule does not validate as a whole, keep its clearest single cutoff, then its
    date, then its range of days, before giving up on timing altogether."""
    base = {k: v for k, v in values.items() if k not in SCHEDULE_FIELDS}
    test = values.get("type") == "test"
    for name in (
        ("startsAt", "availabilityClosesAt", "dueAt")
        if test
        else ("dueAt", "availabilityClosesAt", "startsAt")
    ):
        if values.get(name):
            yield {**base, (name if test and name != "dueAt" else "dueAt"): values[name]}
    if values.get("dueDate"):
        yield {**base, "dueDate": values["dueDate"]}
    if values.get("dateWindowStart") and values.get("dateWindowEnd"):
        yield {**base, "dateWindowStart": values["dateWindowStart"], "dateWindowEnd": values["dateWindowEnd"]}


def valid_schedule(values):
    """task_input for the fullest valid form of a source schedule, or None when none validates."""
    for attempt in (values, *schedule_fallbacks(values)):
        try:
            return task_input(attempt)
        except (ApiError, ValidationError) as exc:
            if not timing_error(exc):
                raise
    return None


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
    if method == "student_review":
        d = task_input(values)
    else:
        d = valid_schedule(values)
        if d is None:
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
    if d.get("dueDate"):
        provenance["dueAt"] = {**provenance["dueAt"], "basis": "source-date-only", "defaultTime": "23:59 IST"}
    elif window_derived(d):
        provenance["dueAt"] = {
            **provenance["dueAt"],
            "basis": "source-window-end",
            "defaultTime": "23:59 IST",
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
    d["sourceLinks"] = mail.source_links(cand.links)
    d["observedTargeting"] = cand.observed
    d["groupWork"] = cand.group_work
    if cand.display_title and cand.title == d["title"]:
        d["displayTitle"], d["naming"] = cand.display_title, cand.naming
    else:
        d["displayTitle"], d["naming"] = naming.tidy(d["title"]), naming.naming(False)
    if cand.tentative and d.get("dueAt") and method != "student_review":
        d["timingTentative"] = {"question": (cand.question or "")[:300], "evidenceRef": str(event.id)}
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


def stale_omission(db, prov):
    """Timing an older interpreter dropped (as unreadable or unsettled) is no source statement."""
    if (prov or {}).get("basis") != "source-timing-omitted" or not prov.get("evidenceRef"):
        return False
    old = db.get(SourceEvent, uuid.UUID(prov["evidenceRef"]))
    return bool(old) and old.processing_version != VERSION


def update_task(db, task, cand, event, explicit, method, schedule_only=False, restore=(), retitle=True):
    """Reconcile role-specific fields. Never touches completion.

    restore names fields that wrongly attached work had set: they take this (the task's own) source's
    value, or none, whatever newer time the wrong source carried. retitle is False for another
    notice of the same work (a copy, reminder or follow-up): its wording ("Submit your DBMS
    assignment", "IA 1 postponed") never replaces the work's name."""
    changes, conflicts = {}, {}
    incoming = proposal(cand, cand.subject_id)
    for name in restore:
        if name in TASK_DEFAULTS:
            incoming.setdefault(name, TASK_DEFAULTS[name])
    if method != "student_review" and unresolved(cand):
        incoming = {**undated_fields(incoming), **{k: None for k in SCHEDULE_FIELDS if k != "timingMode"}}
    if schedule_only:
        incoming = {k: v for k, v in incoming.items() if k in SCHEDULE_FIELDS}
    if not cand.title or not retitle:
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
        older = (
            method != "student_review"
            and name not in restore
            and incoming_order < field_order(db, task, name, provenance)
        )
        if older and method == "retime":
            # Repair fills timing that is empty only through an earlier interpreter's mistake. With
            # no accepted value to protect, an older stated date is the best date there is; a
            # current-version omission (a newer notice doubting the timing) still stands.
            current = (provenance.get(name) or {}).get(
                "basis"
            ) == "source-timing-omitted" and not stale_omission(db, provenance.get(name))
            older = current or task.data.get(name) not in (None, "", "undated", "unresolved")
        elif older:
            older = not stale_omission(db, provenance.get(name))
        if older:
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
        if window_derived(task.data) and "dueAt" not in changes:
            merged["dueAt"] = None  # A window's cutoff follows the window or a newly stated deadline.
        if (
            "timingMode" not in changes
            and merged.get("timingMode") in ("undated", "unresolved")
            and any(k in changes for k in (*CUTOFFS, "dueDate", "dateWindowEnd"))
        ):
            # Work that had no date now has one: its mode follows the newly stated timing.
            merged.pop("timingMode")
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
            d = valid_schedule(reset)
            if d is None:
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
            if d.get("dueDate"):
                prov["dueAt"] = {
                    **prov.get("dueAt", {}),
                    "basis": "source-date-only",
                    "defaultTime": "23:59 IST",
                }
            elif window_derived(d):
                prov["dueAt"] = {
                    **prov.get("dueAt", {}),
                    "basis": "source-window-end",
                    "defaultTime": "23:59 IST",
                }
            keep = {k: task.data[k] for k in task.data if k not in allowed}
            if "title" in changes:
                # A source that retitles the work renames it too (a student's own title is kept).
                named = cand.display_title if cand.display_title and cand.title == d["title"] else None
                keep["displayTitle"] = named or naming.tidy(d["title"])
                keep["naming"] = cand.naming if named else naming.naming(False)
            if any(k in changes for k in SCHEDULE_FIELDS):
                keep.pop("timingTentative", None)
                if cand.tentative and d.get("dueAt") and method != "student_review":
                    keep["timingTentative"] = {
                        "question": (cand.question or "")[:300],
                        "evidenceRef": str(event.id),
                    }
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


def new_event(db, record, key, cand):
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
            "links": mail.source_links(cand.links),
            "proposal": proposal(cand, cand.subject_id),
            # Replays (faculty approval, review) rebuild the candidate from this event.
            "question": cand.question,
            "tentative": cand.tentative,
            "postedAs": cand.posted_as,
            "displayTitle": cand.display_title,
            "naming": cand.naming,
        },
    )
    db.add(event)
    db.flush()
    return event


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
    event = new_event(db, record, key, cand)
    event_type = event.event_type

    def done(outcome):
        event.outcome = outcome
        return outcome

    if event_type == "unknown" and cand.intent != "returned_ambiguous":
        return done("ignored_unrelated")
    task = task_by_identity(db, uid, cand.identity_key)
    if (
        task
        and cand.method == "ai"
        and re.search(r":\d+$", cand.identity_key or "")
        and norm(cand.title) != norm(task.title)
        and not same_work(cand, task, ctx)
    ):
        # An item identified by its position in a message: when extraction lists the message's work
        # in another order, that position now names different work, which must not update this task.
        task = None
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
    if not task and skipped_post(cand):
        # A Classroom post adds only assessments, tutorials, projects and presentations. Work it
        # mentions still updates a task already tracked (e.g. a changed coursework deadline).
        return done("ignored_classroom_post")
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
    if (
        not task
        and outcome == "review"
        and reason in UNSTATED_AUDIENCE
        and cand.intent in WORK_INTENTS
        and not cand.section.startswith("quoted")
    ):
        # A copy of work already tracked as the student's, from a faculty member not yet known,
        # that names no audience: it is the same work, not a new question. Only an identical name
        # and an unchanged date count, so another division's schedule never moves the task.
        tracked = find_same_work(db, uid, cand, subject_id, ctx, strict=True)
        if tracked:
            task, subject_id = (
                tracked,
                subject_id or (str(tracked.subject_id) if tracked.subject_id else None),
            )
            outcome, reason, question = "applicable", TRACKED_COPY, None
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
        if cand.method == "classroom_submission":
            classroom_status(db, task, record, cand)
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
        tracked = task_by_identity(db, uid, cand.identity_key)
        explicit = cand.intent == "revision" or tracked is not None
        own = tracked is not None and tracked.id == task.id  # This task's own source may rename it.
        changes, conflicts = update_task(db, task, cand, event, explicit, cand.method, retitle=own)
        reconcile_lms_receipts(db, uid, ctx, task)
        if record.kind == "gmail_message" and outcome == "applicable" and reason != TRACKED_COPY:
            # A copy matched only by name does not vouch for its sender's other mail.
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
    relevance, _, matched = rules.evaluate(ctx["rules"], facts)
    hidden = relevance == "exclude"
    if hidden:
        event.data = {**event.data, "rule": matched}
        if outcome != "applicable":
            return done("rule_excluded")  # Not even known to be the student's: nothing to keep.
    fields = proposal(cand, subject_id)
    fields_extra = {}
    review_data = {
        **context,
        "proposal": fields,
        "extra": fields_extra,
        "subjectChoices": cand.subject_choices,
    }
    if outcome != "applicable" and not hidden:
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
    same = find_same_work(db, uid, cand, subject_id, ctx)
    if same:
        # The same work announced again (another faculty member, a resend, a reminder, a follow-up
        # or a moved deadline): one task, not a question. It is updated like any later notice; older
        # notices never roll back newer values, manual edits stay, completion is never touched.
        if subject_id and not same.subject_id and not cand.subject_id:
            cand.subject_id = subject_id
        changes, _ = update_task(db, same, cand, event, False, cand.method, retitle=False)
        settle_reviews(db, same, ("possible_duplicate",), "same_work_linked")
        return done("updated" if changes else "evidence_recorded")
    similar = None if hidden else similar_task(db, uid, cand, subject_id, ctx)
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
    apply_rules_to(db, created, ctx["rules"])  # Hidden work is kept, out of sight, while its rule stands.
    return done("created")


# --- Repair of work imported without its date ---------------------------------------------------


RETIME_ATTEMPTS = 3


def same_title(a, b):
    mine, theirs = tokens(a), tokens(b)
    return bool(mine and theirs) and (
        norm(a) == norm(b)
        or len(mine & theirs) / len(mine | theirs) >= 0.5
        or mine <= theirs
        or theirs <= mine
    )


def invented_clock(cand, words):
    """Saved evidence from an earlier interpreter: a midnight the excerpt does not state is a guess
    for a date-only notice (31 October must not become 31 October, 5:30 am)."""
    if dates.find_times(words) or TIME_WORDS.search(words):
        return
    stated = dates.find_dates(words, (cand.occurred_at or now()).astimezone(IST).date())
    for name in CUTOFFS:
        if not cand.timing.get(name):
            continue
        if cand.provenance.get(name, {}).get("timezone") == "UTC":
            return  # Classroom's own due fields are authoritative, whatever their clock.
        value = parse_dt(cand.timing[name])
        local = value.astimezone(IST)
        written = (
            value.date()
            if value.time() in (time(0, 0), time(23, 59), time(23, 59, 59))
            else local.date()
            if local.time() == time(0, 0)
            else None
        )
        if written and (written in stated or not stated):
            cand.timing.clear()
            if not cand.window:
                cand.date_only = written.isoformat()
        return


def needs_date(task):
    """No deadline, or a midnight-UTC one with no date-only basis: what a guessed clock looks like."""
    if not task.due_at:
        return True
    basis = (task.data.get("timingProvenance") or {}).get("dueAt") or {}
    return (
        task.due_at.astimezone(UTC).time() == time(0, 0)
        and not task.data.get("dueDate")
        and basis.get("timezone") != "UTC"  # Classroom's structured due time is never a guess.
        and basis.get("basis") != "student-entered"
    )


def gmail_recent(record):
    stamp = record.received_at or record.sent_at or record.created_at
    return record.kind != "gmail_message" or (stamp and stamp >= now() - GMAIL_LOOKBACK)


def repair_undated(db, conn):
    """Work an earlier interpreter imported without its date (or with an invented midnight) gets the
    date its source states: first from the timing its saved evidence recorded, without any network
    call; otherwise its source is queued for one timing-only look. Repair only sets the schedule of
    that same task; it never creates, merges, retitles or completes work, and never overrides a
    schedule the student entered. Each task is examined once per interpreter version."""
    midnight = func.to_char(func.timezone("UTC", Task.due_at), "HH24:MI") == "00:00"
    rows = db.execute(
        select(Task, SourceEvent, SourceRecord)
        .join(TaskEvidence, TaskEvidence.task_id == Task.id)
        .join(SourceEvent, SourceEvent.id == TaskEvidence.event_id)
        .join(SourceRecord, SourceRecord.id == SourceEvent.source_record_id)
        .where(
            Task.user_id == conn.user_id,
            Task.due_at.is_(None) | (midnight & Task.data["dueDate"].astext.is_(None)),
            Task.completed_at.is_(None),
            Task.data["mergedInto"].astext.is_(None),
            Task.data["retimeVersion"].astext.is_distinct_from(VERSION),
            TaskEvidence.state == "active",
            SourceRecord.connection_id == conn.id,
            SourceEvent.event_type.in_(WORK_INTENTS),
        )
        .with_for_update(of=Task)
    ).all()
    found = {}
    for task, event, record in rows:
        found.setdefault(task.id, (task, []))[1].append((event, record))
    queue = {}
    for task, evidence in found.values():
        if task.data.get("dateWindowEnd") and needs_date(task):
            # A window saved before a window carried its deadline: derive it from the task's own fields.
            own = {k: v for k, v in task.data.items() if k in TASK_FIELDS and k != "dueAt"}
            d = valid_schedule(own)
            if d and d.get("dueAt"):
                task.data = {
                    **task.data,
                    "dueAt": d["dueAt"],
                    "timingMode": d["timingMode"],
                    "timingProvenance": {
                        **(task.data.get("timingProvenance") or {}),
                        "dueAt": {"basis": "source-window-end", "defaultTime": "23:59 IST"},
                    },
                }
                task.due_at, task.revision = parse_dt(d["dueAt"]), task.revision + 1
                task.status = effective_status(task, now())
                history(db, task, "source_update", {"dueAt": d["dueAt"], "timingMode": d["timingMode"]})
                continue
        if any(k in SCHEDULE_FIELDS for k in task.data.get("manualFieldOverrides", {})):
            task.data = {**task.data, "retimeVersion": VERSION}
            continue  # The student's own timing decision stands.
        evidence = [(e, r) for e, r in evidence if same_title(e.data.get("title"), task.title)]
        if not evidence:
            continue  # Its own source may be on another connection; that pass examines it.
        task.data = {**task.data, "retimeVersion": VERSION}
        evidence.sort(key=lambda x: source_order(db, x[0]), reverse=True)
        for event, record in evidence:
            cand = candidate_from_event(event, record)
            words = " ".join(filter(None, [cand.title, cand.excerpt]))
            invented_clock(cand, words)
            settle_timing(cand, words, cand.occurred_at)
            if not has_timing(cand):
                found_date = dates.single(words, (cand.occurred_at or now()).astimezone(IST).date())
                if found_date:
                    found_timing(cand, *found_date, words, "source-date")
            if has_timing(cand):
                update_task(db, task, cand, event, True, "retime", schedule_only=True)
            if not needs_date(task):
                break
        if not needs_date(task):
            continue
        record = evidence[0][1]
        timing_pass = (record.data.get("interpretation") or {}).get("timingPass") or {}
        if (
            (record.processing_version != VERSION or timing_pass.get("unavailable"))
            and record.processing_state in ("interpreted", "needs_review")
            and gmail_recent(record)
        ):
            queue.setdefault(record.id, (record, set()))[1].add(str(task.id))
    for record, task_ids in queue.values():
        record.data = {
            **record.data,
            "retime": {"tasks": sorted(task_ids), "state": record.processing_state, "reason": record.reason},
        }
        record.processing_state, record.expires_at = "awaiting_interpretation", None
    return len(queue)


STUDENT_OUTCOMES = ("accepted", "linked")
STUDENT_METHODS = ("student_review", "student_link", "reassigned")


def settle_completion(db, task, detached, own, events):
    """A completion that came from detached work moves to the task's own turn-in, or is undone."""
    completion = task.data.get("completion") or {}
    if not task.completed_at or completion.get("eventId") not in detached:
        return
    turned_in = [
        e
        for e in events
        if e.event_type == "submission" and e.identity_key in own and str(e.id) not in detached
    ]
    if turned_in:
        latest = max(turned_in, key=lambda e: e.occurred_at or datetime.min.replace(tzinfo=UTC))
        task.data = {**task.data, "completion": {**completion, "eventId": str(latest.id)}}
        return
    task.completed_at = None
    task.data = {**task.data, "completion": None}
    task.status = effective_status(task, now())
    task.revision += 1
    history(db, task, "reopened", {"reason": "completion came from another work's turn-in"})


def requeue_relink(records):
    for record in records:
        # Interpreted again under a fresh event key, so the detached work becomes its own task.
        record.data = {**record.data, "relinkRun": record.data.get("relinkRun", 0) + 1}
        record.processing_state, record.expires_at = "awaiting_interpretation", None


def repair_claimed_identity(db, conn):
    """An earlier interpreter gave a coursework's identity to whichever item its description listed
    first, so other work (IA1.3 in IA 1.8's description) took the coursework's place and its turn-ins.
    That item gets its own identity back, the coursework's turn-ins leave the wrong task, and the
    coursework is interpreted again so it becomes its own task. Examined once per interpreter version."""
    rows = db.execute(
        select(SourceEvent, SourceRecord)
        .join(SourceRecord, SourceRecord.id == SourceEvent.source_record_id)
        .where(
            SourceRecord.connection_id == conn.id,
            SourceRecord.kind == "classroom_coursework",
            SourceEvent.identity_key == SourceRecord.provider_id,
            SourceEvent.event_type.in_(WORK_INTENTS),
            SourceEvent.processing_version != VERSION,
            SourceEvent.data["identityChecked"].astext.is_distinct_from(VERSION),
        )
    ).all()
    requeue = {}
    for event, record in rows:
        event.data = {**event.data, "identityChecked": VERSION}
        title = event.data.get("title")
        if not title or norm(title) == norm(record.title) or same_title(title, record.title):
            continue
        event.identity_key = f"{record.provider_id}:{event.event_key.rsplit(':', 1)[-1]}"
        for sibling in db.scalars(
            select(SourceEvent).where(
                SourceEvent.source_record_id == record.id,
                SourceEvent.event_type.in_(WORK_INTENTS),
                SourceEvent.task_id.is_not(None),
            )
        ):
            named = sibling.data.get("title") or ""
            if norm(named) == norm(record.title) or same_title(named, record.title):
                # The item that is the coursework takes its identity, and is applied again as the
                # coursework (with Classroom's own due date) rather than replayed as before.
                sibling.identity_key, sibling.outcome = record.provider_id, "rekeyed"
        task = (
            db.scalar(select(Task).where(Task.id == event.task_id).with_for_update())
            if event.task_id
            else None
        )
        if task:
            evidence = db.execute(
                select(TaskEvidence, SourceEvent, SourceRecord)
                .join(SourceEvent, SourceEvent.id == TaskEvidence.event_id)
                .join(SourceRecord, SourceRecord.id == SourceEvent.source_record_id)
                .where(TaskEvidence.task_id == task.id, TaskEvidence.state == "active")
            ).all()
            turn_ins = [
                (te, e, r)
                for te, e, r in evidence
                if e.event_type in ("submission", "unsubmission") and e.identity_key == record.provider_id
            ]
            for te, e, r in turn_ins:
                te.state, e.task_id, e.outcome = "reassigned", None, "detached"
                if r.processing_state in ("interpreted", "needs_review"):
                    requeue[r.id] = r
            if turn_ins:
                history(
                    db,
                    task,
                    "evidence_detached",
                    {"reason": "turn-in of other coursework", "title": record.title},
                )
            own = {e.identity_key for _, e, _ in evidence if e.event_type in WORK_INTENTS}
            settle_completion(db, task, {str(e.id) for _, e, _ in turn_ins}, own, [e for _, e, _ in evidence])
        if record.processing_state in ("interpreted", "needs_review"):
            requeue[record.id] = record
    requeue_relink(requeue.values())
    return len(requeue)


def repair_misattributed(db, conn):
    """Undo work an earlier interpreter attached to the wrong task. Before AI-suggested matches were
    checked (same_work), one task could absorb other work entirely: "IA 2.15" created by "IA2.8",
    renamed by "IA 2.10", and completed by another item's turn-in, so those items never became tasks.

    A task belongs to the work its current title names. Other AI-attached work (no shared identity,
    not the same work) is detached; fields it set are restored from the task's own source; a
    completion that came from its turn-in is moved to the task's own turn-in or undone; and its
    sources are interpreted again so each becomes its own task. Student decisions, manual titles and
    current-version links are never touched; each link is examined once per interpreter version."""
    candidates = db.scalars(
        select(Task.id)
        .join(TaskEvidence, TaskEvidence.task_id == Task.id)
        .join(SourceEvent, SourceEvent.id == TaskEvidence.event_id)
        .join(SourceRecord, SourceRecord.id == SourceEvent.source_record_id)
        .where(
            Task.user_id == conn.user_id,
            Task.data["mergedInto"].astext.is_(None),
            TaskEvidence.state == "active",
            SourceRecord.connection_id == conn.id,
            SourceEvent.processing_version != VERSION,
            SourceEvent.data["linkChecked"].astext.is_distinct_from(VERSION),
        )
        .distinct()
    ).all()
    requeue, ctx = {}, None
    for task in db.scalars(select(Task).where(Task.id.in_(candidates)).with_for_update()):
        evidence = db.execute(
            select(TaskEvidence, SourceEvent, SourceRecord)
            .join(SourceEvent, SourceEvent.id == TaskEvidence.event_id)
            .join(SourceRecord, SourceRecord.id == SourceEvent.source_record_id)
            .where(TaskEvidence.task_id == task.id, TaskEvidence.state == "active")
        ).all()
        for _, event, _ in evidence:
            event.data = {**event.data, "linkChecked": VERSION}
        if "title" in task.data.get("manualFieldOverrides", {}):
            continue  # The student named this task; what it stands for is theirs to say.
        work = [(te, e, r) for te, e, r in evidence if e.event_type in WORK_INTENTS]
        owners = [
            (te, e, r)
            for te, e, r in work
            if norm(e.data.get("title")) == norm(task.title)
            or e.outcome in STUDENT_OUTCOMES
            or te.method in STUDENT_METHODS
            or e.data.get("method") != "ai"
        ]
        if not owners:
            continue  # Nothing shows which work this task is; leave it as it is.
        own = {e.identity_key for _, e, _ in owners}
        ctx = ctx or load_context(db, conn.user_id, owners[0][2])
        foreign = [
            (te, e, r)
            for te, e, r in work
            if (te, e, r) not in owners
            and e.processing_version != VERSION
            and e.identity_key not in own
            and not same_work(candidate_from_event(e, r), task, ctx)
        ]
        if not foreign:
            continue
        stray = {e.identity_key for _, e, _ in foreign} - own
        # A Classroom turn-in belongs to the coursework it names; it leaves with that coursework.
        foreign += [
            (te, e, r)
            for te, e, r in evidence
            if e.event_type in ("submission", "unsubmission") and e.identity_key in stray
        ]
        detached = {str(e.id) for _, e, _ in foreign}
        for te, event, record in foreign:
            te.state, event.task_id, event.outcome = "reassigned", None, "detached"
            if record.processing_state in ("interpreted", "needs_review") and gmail_recent(record):
                requeue[record.id] = record
            history(
                db, task, "evidence_detached", {"reason": "different work", "title": event.data.get("title")}
            )
        provenance = task.data.get("timingProvenance") or {}
        tainted = {k for k, p in provenance.items() if (p or {}).get("evidenceRef") in detached}
        if tainted:
            _, owner, owner_record = max(owners, key=lambda x: source_order(db, x[1]))
            task.data = {
                **task.data,
                "timingProvenance": {k: v for k, v in provenance.items() if k not in tainted},
            }
            update_task(
                db, task, candidate_from_event(owner, owner_record), owner, True, "repair", restore=tainted
            )
        settle_completion(db, task, detached, own, [e for _, e, _ in evidence])
        kinds = {
            "gmail" if r.kind == "gmail_message" else "classroom"
            for _, e, r in evidence
            if str(e.id) not in detached
        }
        if kinds:
            task.data = {**task.data, "sources": sorted(kinds)}
    requeue_relink(requeue.values())
    return len(requeue)


def retime_candidate(db, uid, record, index, cand, retime):
    """A timing-only second look at a source: set the schedule of the listed undated task, nothing
    else. Work the look finds without a listed task is left alone (it was set aside before)."""
    if cand.intent not in WORK_INTENTS or not has_timing(cand):
        return "retime_skipped"
    listed = [uuid.UUID(i) for i in retime.get("tasks", [])]
    candidates = db.scalars(
        select(Task)
        .where(Task.user_id == uid, Task.id.in_(listed))
        .order_by(Task.created_at)
        .with_for_update()
    ).all()
    by_identity = task_by_identity(db, uid, cand.identity_key)
    ordered = ([by_identity] if by_identity in candidates else []) + candidates
    task = next((t for t in ordered if same_title(cand.title, t.title)), None)
    if not task or task.completed_at or not needs_date(task):
        return "retime_skipped"
    key = f"{record.revision}:retime-{VERSION}:{index}"
    if db.scalar(
        select(SourceEvent.id).where(SourceEvent.source_record_id == record.id, SourceEvent.event_key == key)
    ):
        return "replayed"
    event = new_event(db, record, key, cand)
    changes, _ = update_task(db, task, cand, event, True, "retime", schedule_only=True)
    event.outcome = "updated" if changes else "evidence_recorded"
    return event.outcome


def finish_retime(db, uid, record, prepared, progress):
    retime = record.data["retime"]
    outcomes = (
        []
        if prepared.ignore
        else [retime_candidate(db, uid, record, i, c, retime) for i, c in enumerate(prepared.candidates)]
    )
    progress["tasksUpdated"] = progress.get("tasksUpdated", 0) + outcomes.count("updated")
    data = {k: v for k, v in record.data.items() if k not in ("retime", "aiPausedUntil", "aiPausedReason",
                                                               "aiPausedCode")}  # fmt: skip
    interpretation = {
        **(data.get("interpretation") or {}),
        "retime": {"version": VERSION, "outcomes": outcomes},
    }
    if prepared.meta.get("timingPass"):
        interpretation["timingPass"] = prepared.meta["timingPass"]
    record.data = {**data, "interpretation": interpretation}
    record.processing_state, record.reason = retime["state"], retime.get("reason")
    record.processing_version = VERSION
    return progress


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
    if record.data.get("retime") is not None:
        retime = record.data["retime"]
        if not prepared.paused and (prepared.meta.get("timingPass") or {}).get("unavailable"):
            # A timing-only look exists to ask AI; wait for it rather than finishing without it.
            prepared.paused, prepared.paused_retry_after = "AI timing look is temporarily unavailable", 60
        if prepared.paused and retime.get("attempts", 0) + 1 >= RETIME_ATTEMPTS:
            # A repair must never hold a sync open: after a few failed looks the work stays as it was.
            prepared.paused, prepared.candidates = None, []
        if prepared.paused:
            record.data = {**record.data, "retime": {**retime, "attempts": retime.get("attempts", 0) + 1}}
        else:
            return finish_retime(db, uid, record, prepared, progress)
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
            else "classroom_post_not_work"
            if "ignored_classroom_post" in outcomes
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
    if prepared.relink:
        run = f"{run}l{prepared.relink}"

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
