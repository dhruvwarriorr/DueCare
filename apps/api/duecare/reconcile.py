"""Apply current source policies to saved evidence without paying for another AI extraction."""

import uuid

from sqlalchemy import select

from . import faculty, interpret, mail, targeting
from .domain import effective_status
from .models import (
    Connection,
    History,
    Profile,
    ReviewItem,
    SourceAttachment,
    SourceEvent,
    SourceRecord,
    Task,
    TaskEvidence,
    now,
)


def ensure_source_policy(db, uid):
    """Apply the saved-mail policy once per owner under the caller's work lock."""
    profile = db.get(Profile, uuid.UUID(str(uid)))
    version = "academic-end-of-day-links-3"
    if not profile or profile.data.get("sourcePolicyVersion") == version:
        return
    cleaned = refresh_saved_source_data(db, uid)
    result = {**refresh_attention(db, uid), **cleaned}
    profile.data = {**profile.data, "sourcePolicyVersion": version, "sourcePolicyRefresh": result}
    profile.revision += 1


def refresh_saved_source_data(db, uid):
    """Remove saved signature URLs and normalize date-only proposals before acceptance."""
    counts = {"linksRemoved": 0, "dateOnlyFixed": 0}
    for model in (SourceEvent, ReviewItem, Task):
        for row in db.scalars(select(model).where(model.user_id == uid)):
            data = dict(row.data)
            for key in ("links", "sourceLinks"):
                if key in data:
                    filtered = mail.source_links(data[key])
                    counts["linksRemoved"] += len(data[key] or []) - len(filtered)
                    data[key] = filtered
            if model in (SourceEvent, ReviewItem) and (data.get("proposal") or {}).get("dueDate"):
                proposal = interpret.source_fields(data["proposal"])
                counts["dateOnlyFixed"] += int(proposal != data["proposal"])
                data["proposal"] = proposal
                if model == SourceEvent:
                    data["timing"] = {
                        k: v
                        for k, v in (data.get("timing") or {}).items()
                        if k
                        not in ("dueAt", "startsAt", "endsAt", "availabilityOpensAt", "availabilityClosesAt")
                    }
            if (
                model == Task
                and data.get("dueDate")
                and not any(
                    key in (data.get("manualFieldOverrides") or {})
                    for key in ("dueAt", "startsAt", "availabilityClosesAt")
                )
            ):
                normalized = interpret.task_input(data)
                if data.get("dueAt") != normalized["dueAt"]:
                    data.update({k: normalized[k] for k in interpret.SCHEDULE_FIELDS})
                    row.due_at = interpret.parse_dt(normalized["dueAt"])
                    row.status = effective_status(row, now())
                    counts["dateOnlyFixed"] += 1
            if data != row.data:
                row.data = data
                row.revision += 1
    for link in db.scalars(
        select(SourceAttachment).where(SourceAttachment.user_id == uid, SourceAttachment.kind == "link")
    ):
        if not mail.source_links([link.reference]):
            db.delete(link)
            counts["linksRemoved"] += 1
    return counts


def refresh_faculty_reviews(db, uid):
    """Reapply saved academic proposals after exact-sender approval, without AI calls."""
    from .sync import sender_decision

    resolved = 0
    reviews = db.scalars(
        select(ReviewItem).where(
            ReviewItem.user_id == uid,
            ReviewItem.status == "open",
            ReviewItem.issue_type == "confirm_applicability",
        )
    ).all()
    for review in reviews:
        record = db.get(SourceRecord, review.source_record_id) if review.source_record_id else None
        event = db.get(SourceEvent, review.event_id) if review.event_id else None
        if not record or not event or record.kind != "gmail_message":
            continue
        if not faculty.approved(db, uid, record.sender_email):
            continue
        if record.processing_state in ("blocked", "ignored") or (
            record.expires_at and record.expires_at <= now()
        ):
            continue
        if sender_decision(db, uid, record.sender_email)[0] == "blocked":
            continue
        if mail.academic_exclusion(record.title, record.sender_email, text=record.excerpt):
            continue
        ctx = interpret.load_context(db, uid, record)
        cand = interpret.candidate_from_event(event, record, review.data.get("proposal"))
        if cand.subject_id and cand.subject_id not in {s["id"] for s in ctx["subjects"]}:
            cand.subject_id = None
        cand.subject_choices = review.data.get("subjectChoices") or []
        if review.task_id:
            cand.match_task_id = str(review.task_id)
        outcome, _, _ = targeting.evaluate(
            cand.observed,
            ctx["profile"],
            subject_kind=interpret.subject_kind(ctx, cand.subject_id),
            trusted=True,
        )
        if outcome != "applicable":
            continue
        outcome = interpret.apply_candidate(db, uid, ctx, record, 0, cand, f"faculty-{review.id}")
        applied = db.scalar(
            select(SourceEvent).where(
                SourceEvent.source_record_id == record.id,
                SourceEvent.event_key == f"{record.revision}:faculty-{review.id}:0",
            )
        )
        review.status, review.resolved_at = "resolved", now()
        review.task_id = applied.task_id if applied and applied.task_id else review.task_id
        review.data = {
            **review.data,
            "resolution": {"action": "faculty_approved", "outcome": outcome, "at": now().isoformat()},
        }
        review.revision += 1
        db.flush()
        if not db.scalar(
            select(ReviewItem.id)
            .where(
                ReviewItem.source_record_id == record.id,
                ReviewItem.status == "open",
            )
            .limit(1)
        ):
            record.processing_state = "interpreted"
        resolved += 1
    return resolved


def refresh_attention(db, uid):
    """Caller must hold the owner's work transaction; all reads/writes stay owner scoped."""
    from .privacy import task_suppression
    from .sync import minimize, sender_decision

    result = {
        "conflictsResolved": 0,
        "mailIgnored": 0,
        "reviewsDismissed": 0,
        "tasksCompleted": 0,
        "nonAcademicTasksRemoved": 0,
        "timingReviewsResolved": 0,
        "undatedTasksCreated": 0,
        "facultyApproved": 0,
        "applicabilityReviewsResolved": 0,
    }
    reviews = db.scalars(
        select(ReviewItem).where(ReviewItem.user_id == uid, ReviewItem.status == "open")
    ).all()
    excluded = set()
    records = db.scalars(
        select(SourceRecord).where(SourceRecord.user_id == uid, SourceRecord.kind == "gmail_message")
    ).all()
    for record in records:
        related = [r for r in reviews if r.source_record_id == record.id]
        if record.processing_state == "ignored" and record.reason == "non_academic_mail" and not related:
            continue
        headings = [
            record.title,
            *[r.data.get("sourceTitle") for r in related],
            *[(r.data.get("proposal") or {}).get("title") for r in related],
        ]
        text = " ".join(filter(None, [record.excerpt, *[r.data.get("excerpt") for r in related]]))
        if mail.academic_exclusion(
            " ".join(filter(None, headings)), record.sender_email, record.data.get("senderName"), text
        ):
            excluded.add(record.id)
            for review in related:
                review.status, review.resolved_at = "dismissed", now()
                review.revision += 1
                review.data = {"resolution": {"action": "non_academic_mail", "at": now().isoformat()}}
                result["reviewsDismissed"] += 1
    if excluded:
        task_ids = db.scalars(
            select(TaskEvidence.task_id)
            .join(SourceEvent, SourceEvent.id == TaskEvidence.event_id)
            .where(SourceEvent.user_id == uid, SourceEvent.source_record_id.in_(excluded))
        ).all()
        for task in db.scalars(
            select(Task).where(Task.user_id == uid, Task.id.in_(task_ids)).with_for_update()
        ):
            evidence_ids = set(
                db.scalars(
                    select(SourceEvent.source_record_id)
                    .join(TaskEvidence, TaskEvidence.event_id == SourceEvent.id)
                    .where(TaskEvidence.task_id == task.id, TaskEvidence.state == "active")
                )
            )
            manual = task.data.get("manualFieldOverrides") or task.data.get("latestManualDecision")
            manual_history = db.scalar(
                select(History.id)
                .where(
                    History.task_id == task.id, History.changes["_actor"].astext.is_distinct_from("source")
                )
                .limit(1)
            )
            if (
                evidence_ids
                and evidence_ids <= excluded
                and task.data.get("sources")
                and not manual
                and not manual_history
            ):
                task_suppression(db, task)
                db.delete(task)
                result["nonAcademicTasksRemoved"] += 1
        for record in records:
            if record.id in excluded:
                minimize(db, record, "ignored", "non_academic_mail")
                result["mailIgnored"] += 1
        db.flush()

    accepted = db.execute(
        select(SourceRecord, SourceEvent)
        .join(
            SourceEvent,
            SourceEvent.source_record_id == SourceRecord.id,
        )
        .join(TaskEvidence, TaskEvidence.event_id == SourceEvent.id)
        .where(
            SourceRecord.user_id == uid,
            SourceRecord.kind == "gmail_message",
            SourceRecord.processing_state.not_in(("ignored", "blocked")),
            TaskEvidence.state == "active",
            SourceEvent.event_type.in_(("new_work", "revision", "due_notice")),
            SourceEvent.outcome.in_(("created", "updated", "evidence_recorded", "accepted", "linked")),
        )
    ).all()
    for record, event in accepted:
        if mail.academic_exclusion(record.title, record.sender_email, text=record.excerpt):
            continue
        was_approved = faculty.approved(db, uid, record.sender_email)
        if faculty.approve(db, uid, record.sender_email) and not was_approved:
            result["facultyApproved"] += 1
    result["applicabilityReviewsResolved"] = refresh_faculty_reviews(db, uid)
    context_record = next((r for r in records if r.processing_state != "blocked"), None)
    if context_record:
        ctx = interpret.load_context(db, uid, context_record)
        result["tasksCompleted"] += interpret.reconcile_lms_receipts(db, uid, ctx)

    # Capture all conflict proposals before settling any sibling rows, then replay them in
    # source time order. Field clocks make this safe even if imports originally finished out of order.
    conflicts = []
    for review in reviews:
        if review.issue_type != "conflict" or review.source_record_id in excluded:
            continue
        event = db.get(SourceEvent, review.event_id) if review.event_id else None
        record = db.get(SourceRecord, review.source_record_id) if review.source_record_id else None
        task = db.get(Task, review.task_id) if review.task_id else None
        if not event or not record or not task or record.processing_state == "blocked":
            continue
        if record.sender_email and sender_decision(db, uid, record.sender_email)[0] == "blocked":
            continue
        fields = {k: v["proposed"] for k, v in (review.data.get("conflicts") or {}).items()}
        conflicts.append((interpret.source_order(db, event), review, event, record, task, fields))
    for _, review, event, record, task, fields in sorted(conflicts, key=lambda row: row[0]):
        cand = interpret.candidate_from_event(event, record, fields)
        changes, _ = interpret.update_task(db, task, cand, event, True, cand.method)
        review.status, review.resolved_at = "resolved", now()
        review.data = {
            **review.data,
            "resolution": {"action": "latest_source_wins", "at": now().isoformat()},
        }
        event.outcome = "updated" if changes else "evidence_recorded"
        result["conflictsResolved"] += 1
        review.revision += 1

    # Timing uncertainty is not a review gate. Preserve the work as an undated task;
    # current eligibility, sender blocks and deleted-import suppression still apply.
    for review in reviews:
        if review.issue_type != "timing_unresolved" or review.source_record_id in excluded:
            continue
        event = db.get(SourceEvent, review.event_id) if review.event_id else None
        record = db.get(SourceRecord, review.source_record_id) if review.source_record_id else None
        if not event or not record or record.processing_state == "blocked":
            continue
        conn = db.get(Connection, record.connection_id)
        from .privacy import suppressed

        if suppressed(db, conn, event.identity_key) or suppressed(db, conn, record.provider_id):
            review.status, review.resolved_at = "dismissed", now()
            review.revision += 1
            continue
        if record.sender_email and sender_decision(db, uid, record.sender_email)[0] == "blocked":
            continue
        ctx = interpret.load_context(db, uid, record)
        cand = interpret.candidate_from_event(event, record, review.data.get("proposal"))
        task = (
            db.get(Task, review.task_id)
            if review.task_id
            else interpret.task_by_identity(db, uid, event.identity_key)
        )
        outcome, _, question = targeting.evaluate(
            cand.observed,
            ctx["profile"],
            subject_kind=interpret.subject_kind(
                ctx, cand.subject_id or (str(task.subject_id) if task and task.subject_id else None)
            ),
            trusted=bool(task)
            or record.kind.startswith("classroom")
            or (cand.method.startswith("lms_") and bool(record.data.get("addressedToAccount"))),
        )
        if outcome != "applicable":
            review.issue_type = "confirm_applicability"
            review.question = question or "Is this work for you?"
            review.revision += 1
            continue
        cand.question = "Imported timing is uncertain"
        if task:
            interpret.update_task(db, task, cand, event, True, cand.method)
        else:
            task = interpret.create_task(db, uid, ctx, record, event, cand, cand.subject_id, cand.method)
            if review.data.get("extra"):
                task.data = {**task.data, **review.data["extra"]}
            result["undatedTasksCreated"] += 1
        review.task_id, review.status, review.resolved_at = task.id, "resolved", now()
        review.revision += 1
        review.data = {**review.data, "resolution": {"action": "kept_without_dates", "at": now().isoformat()}}
        event.outcome = "accepted"
        result["timingReviewsResolved"] += 1

    # Saved submission records come from Classroom's userId=me endpoint. Reconcile their
    # current state, never a classmate's work or an old TURNED_IN event after an unsubmission.
    submissions = db.scalars(
        select(SourceRecord)
        .join(Connection, Connection.id == SourceRecord.connection_id)
        .where(
            SourceRecord.user_id == uid,
            SourceRecord.kind == "classroom_submission",
            Connection.status == "active",
            SourceRecord.processing_state != "blocked",
        )
    ).all()
    for record in submissions:
        prepared = interpret.Prepared(record_id=record.id, revision=record.revision)
        interpret.submission_candidates(prepared, {"data": record.data, "provider_id": record.provider_id})
        if not prepared.candidates or prepared.candidates[0].intent != "submission":
            continue
        task = interpret.task_by_identity(db, uid, prepared.candidates[0].identity_key)
        if not task:
            continue
        if task.completed_at:
            interpret.settle_reviews(
                db, task, ("confirm_completion", "receipt_unverified"), "submission_confirmed"
            )
            continue
        record.processing_state = "awaiting_interpretation"
        ctx = interpret.load_context(db, uid, record)
        progress = interpret.commit(db, uid, record, prepared, ctx, {}, "source-policy-2")
        result["tasksCompleted"] += progress.get("completed", 0)
    db.flush()
    for record_id in {r.source_record_id for r in reviews if r.source_record_id not in excluded}:
        record = db.get(SourceRecord, record_id) if record_id else None
        if (
            record
            and record.processing_state == "needs_review"
            and not db.scalar(
                select(ReviewItem.id)
                .where(ReviewItem.source_record_id == record_id, ReviewItem.status == "open")
                .limit(1)
            )
        ):
            record.processing_state = "interpreted"
    return result
