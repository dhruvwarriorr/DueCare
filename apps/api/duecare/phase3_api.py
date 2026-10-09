"""Phase 3 routes: Needs attention, rules, merges, evidence reassignment, and task evidence."""

import uuid
from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import Field
from sqlalchemy import func, select

from . import ai, faculty, interpret, mail, rules, targeting
from .common import User, finish, owned, page, replay, revision, work
from .domain import effective_status
from .errors import ApiError
from .models import (
    History,
    MergeOperation,
    Profile,
    ReviewItem,
    Rule,
    SourceEvent,
    SourceRecord,
    Subject,
    Task,
    TaskEvidence,
    now,
)
from .schemas import Input
from .sync import sender_decision
from .views import task_out as task_view

router = APIRouter(prefix="/api/v1")
EDITABLE = (
    "title", "type", "subjectId", "timingMode", "dueAt", "dueDate", "submissionOpensAt", "availabilityOpensAt",
    "availabilityClosesAt", "loginByAt", "reportingAt", "startsAt", "endsAt", "dateWindowStart", "dateWindowEnd",
    "location", "assessmentLabel", "deliverableLabel",
)  # fmt: skip


def manual_history(db, task, action, changes):
    db.add(History(user_id=task.user_id, task_id=task.id, action=action, changes=changes))
    from .activity import task_changed

    task_changed(db, task, action, changes)


# --- Needs attention ---------------------------------------------------------------------------


def review_out(r, db):
    task = db.get(Task, r.task_id) if r.task_id else None
    return {
        "id": str(r.id),
        "issueType": r.issue_type,
        "status": r.status,
        "question": r.question,
        "taskId": str(r.task_id) if r.task_id else None,
        "taskTitle": task.title if task else None,
        "senderEmail": r.sender_email,
        "observed": r.data.get("observed"),
        "student": r.data.get("student"),
        "proposal": r.data.get("proposal"),
        "conflicts": r.data.get("conflicts"),
        "window": r.data.get("window"),
        "alternatives": r.data.get("alternatives"),
        "subjectChoices": r.data.get("subjectChoices", []),
        "courseLabel": r.data.get("courseLabel"),
        "excerpt": r.data.get("excerpt"),
        "sourceTitle": r.data.get("sourceTitle"),
        "sourceKind": r.data.get("sourceKind"),
        "links": r.data.get("links", []),
        "validation": r.data.get("validation"),
        "evidenceCount": len(r.data.get("eventIds", [])),
        "resolution": r.data.get("resolution"),
        "revision": r.revision,
        "createdAt": r.created_at.isoformat(),
    }


@router.get("/review-items")
def review_items(
    status: Literal["open", "resolved", "dismissed", "suppressed"] = "open",
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
    user=User,
):
    with work(user) as db:
        from .reconcile import ensure_source_policy

        ensure_source_policy(db, user["id"])
        rows, c = page(
            db,
            select(ReviewItem)
            .outerjoin(SourceRecord, SourceRecord.id == ReviewItem.source_record_id)
            .where(
                ReviewItem.user_id == user["id"],
                ReviewItem.status == status,
                (SourceRecord.expires_at.is_(None)) | (SourceRecord.expires_at > now()),
            ),
            ReviewItem,
            limit,
            cursor,
        )
        return {"items": [review_out(r, db) for r in rows], "nextCursor": c}


class Resolution(Input):
    revision: int = Field(ge=1)
    action: Literal[
        "accept",
        "link",
        "dismiss",
        "complete",
        "reopen",
        "apply_update",
        "keep_current",
        "delete_task",
        "keep_task",
    ]
    subject_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    remember_alias: bool = False
    fields: dict = Field(default_factory=dict)


def candidate_from(event, record):
    return interpret.candidate_from_event(event, record)


def context(db, uid):
    p = db.get(Profile, uuid.UUID(uid))
    return {"profile": p.data if p else {}}


@router.post("/review-items/{id}/resolve")
def resolve_review(id: uuid.UUID, body: Resolution, request: Request, user=User):
    with work(user) as db:
        cached, op = replay(db, request, user, body.model_dump(mode="json"))
        if cached is not None:
            return cached
        item = owned(db, ReviewItem, id, user["id"], True)
        revision(item, body.revision)
        if item.status != "open":
            raise ApiError(409, "REVIEW_CLOSED", "This item was already resolved")
        if item.sender_email and sender_decision(db, user["id"], item.sender_email)[0] == "blocked":
            item.status = "suppressed"
            item.revision += 1
            return finish(db, op, {"ok": False, "code": "SENDER_BLOCKED", "review": review_out(item, db)})
        event = db.get(SourceEvent, item.event_id) if item.event_id else None
        record = db.get(SourceRecord, item.source_record_id) if item.source_record_id else None
        if record and record.expires_at and record.expires_at <= now():
            raise ApiError(410, "REVIEW_EXPIRED", "This review has expired")
        if (
            record
            and record.kind == "gmail_message"
            and body.action != "dismiss"
            and mail.academic_exclusion(
                record.title or item.data.get("sourceTitle"),
                record.sender_email,
                text=record.excerpt or item.data.get("excerpt"),
            )
        ):
            raise ApiError(
                409,
                "NON_ACADEMIC_MAIL",
                "This message is excluded from academic work. Dismiss it or refresh Needs attention",
            )
        task = (
            db.scalar(select(Task).where(Task.id == item.task_id).with_for_update()) if item.task_id else None
        )
        result = {"ok": True}
        if body.action == "dismiss":
            item.status = "dismissed"
        elif body.action == "accept":
            if not event or not record:
                raise ApiError(409, "REVIEW_UNAVAILABLE", "The source for this item is no longer available")
            # Recheck the current profile: a confirmed mismatch cannot be approved.
            outcome, _, _ = targeting.evaluate(
                item.data.get("observed") or {}, context(db, user["id"])["profile"], trusted=True
            )
            if outcome == "mismatch":
                raise ApiError(
                    409, "TARGETING_MISMATCH", "Your profile no longer matches this work's audience"
                )
            fields = {**(item.data.get("proposal") or {})}
            edits = {k: v for k, v in body.fields.items() if k in EDITABLE}
            if body.subject_id:
                owned(db, Subject, body.subject_id, user["id"])
                edits["subjectId"] = str(body.subject_id)
            fields.update(edits)
            if not fields.get("type"):
                raise ApiError(
                    422,
                    "TYPE_REQUIRED",
                    "Choose whether this is an assignment or a test",
                    {"type": "Required"},
                )
            if fields.get("dateWindowStart") and not any(
                fields.get(k) for k in ("dueAt", "startsAt", "availabilityClosesAt")
            ):
                fields["timingMode"] = "unresolved"  # Window-only acceptance keeps no precise cutoff.
            cand = candidate_from(event, record)
            created = interpret.create_task(
                db,
                user["id"],
                {"profile": context(db, user["id"])["profile"]},
                record,
                event,
                cand,
                fields.get("subjectId"),
                "student_review",
                fields,
            )
            created.data = {
                **created.data,
                **(item.data.get("extra") or {}),
                "manualFieldOverrides": {
                    k: {"recordedAt": now().isoformat(), "via": "review"} for k in edits
                },
            }
            event.outcome = "accepted"
            if body.remember_alias and item.data.get("courseLabel") and fields.get("subjectId"):
                # A confirmed LMS course label becomes a subject alias for future matching.
                subject = owned(db, Subject, uuid.UUID(fields["subjectId"]), user["id"], True)
                labels = sorted({*subject.data.get("lmsCourseLabels", []), item.data["courseLabel"]})
                subject.data = {**subject.data, "lmsCourseLabels": labels}
                subject.revision += 1
            item.status, item.task_id = "resolved", created.id
            result["taskId"] = str(created.id)
        elif body.action == "link":
            target_id = body.task_id or item.task_id
            if not target_id or not event or not record:
                raise ApiError(422, "TASK_REQUIRED", "Choose the task this belongs to")
            target = owned(db, Task, target_id, user["id"], True)
            interpret.update_task(db, target, candidate_from(event, record), event, True, "student_link")
            event.outcome = "linked"
            if record.kind == "gmail_message":
                faculty.approve(db, user["id"], record.sender_email, "student")
            item.status, item.task_id = "resolved", target.id
            result["taskId"] = str(target.id)
        elif body.action in (
            "complete",
            "reopen",
            "delete_task",
            "keep_task",
            "apply_update",
            "keep_current",
        ):
            if not task:
                raise ApiError(409, "REVIEW_UNAVAILABLE", "The related task is no longer available")
            if body.action == "complete":
                if not task.completed_at:
                    task.completed_at = now()
                    task.data = {
                        **task.data,
                        "completion": {
                            "origin": "student_confirmed_evidence",
                            "eventId": str(event.id) if event else None,
                            "sourceTime": event.occurred_at.isoformat()
                            if event and event.occurred_at
                            else None,
                            "recordedAt": now().isoformat(),
                        },
                        "latestManualDecision": {"action": "completed", "recordedAt": now().isoformat()},
                    }
                    task.status, task.revision = "completed", task.revision + 1
                    manual_history(
                        db,
                        task,
                        "completed",
                        {
                            "status": "completed",
                            "via": "review",
                            "_eventId": str(event.id) if event else None,
                        },
                    )
            elif body.action == "reopen" and task.completed_at:
                task.completed_at = None
                task.data = {
                    **task.data,
                    "completion": None,
                    "latestManualDecision": {"action": "reopened", "recordedAt": now().isoformat()},
                }
                task.status, task.revision = effective_status(task, now()), task.revision + 1
                manual_history(db, task, "reopened", {"status": task.status, "via": "review"})
            elif body.action == "delete_task":
                from .privacy import task_suppression

                task_suppression(db, task)
                result["deletedTaskId"] = str(task.id)
                item.task_id = None
                db.flush()
                db.delete(task)
            elif body.action == "apply_update" and event and record:
                # The student chose the source values: clear those manual overrides, then apply.
                conflicts = item.data.get("conflicts") or {}
                overrides = {
                    k: v for k, v in task.data.get("manualFieldOverrides", {}).items() if k not in conflicts
                }
                task.data = {**task.data, "manualFieldOverrides": overrides}
                cand = candidate_from(event, record)
                cand.timing = {k: v["proposed"] for k, v in conflicts.items() if k in interpret.TIMING_FIELDS}
                interpret.update_task(db, task, cand, event, True, "student_review")
            item.status = "resolved"
        item.data = {**item.data, "resolution": {"action": body.action, "at": now().isoformat()}}
        item.resolved_at = now()
        item.revision += 1
        db.flush()
        if body.action in ("accept", "link") and record and record.kind == "gmail_message":
            from .reconcile import refresh_faculty_reviews

            refresh_faculty_reviews(db, user["id"])
        return finish(db, op, {**result, "review": review_out(item, db)})


# --- Rules -------------------------------------------------------------------------------------


def rule_out(r):
    return {
        "id": str(r.id),
        "name": r.name,
        "enabled": r.enabled,
        "position": r.position,
        "revision": r.revision,
        **r.data,
    }


def validate_rule(db, uid, body: rules.RuleBody):
    subject_ids = {str(s) for s in db.scalars(select(Subject.id).where(Subject.user_id == uid))}
    for cond in body.conditions + body.exceptions:
        values = cond.value if isinstance(cond.value, list) else [cond.value]
        if cond.field == "subjectId" and not set(values) <= subject_ids:
            raise ApiError(422, "INVALID_RULE", "Rules can refer only to your own subjects")
    return body.model_dump(mode="json", exclude={"name", "enabled"})


class RuleInput(rules.RuleBody):
    revision: int | None = Field(None, ge=1)


@router.get("/rules")
def list_rules(user=User):
    with work(user) as db:
        rows = db.scalars(
            select(Rule).where(Rule.user_id == user["id"]).order_by(Rule.position, Rule.created_at)
        )
        return {"items": [rule_out(r) for r in rows]}


@router.post("/rules", status_code=201)
def add_rule(body: RuleInput, user=User):
    with work(user) as db:
        position = (db.scalar(select(func.max(Rule.position)).where(Rule.user_id == user["id"])) or 0) + 1
        r = Rule(
            user_id=uuid.UUID(user["id"]),
            name=body.name,
            enabled=body.enabled,
            position=position,
            data=validate_rule(
                db, user["id"], rules.RuleBody.model_validate(body.model_dump(exclude={"revision"}))
            ),
        )
        db.add(r)
        db.flush()
        return rule_out(r)


@router.patch("/rules/{id}")
def edit_rule(id: uuid.UUID, body: RuleInput, user=User):
    with work(user) as db:
        r = owned(db, Rule, id, user["id"], True)
        revision(r, body.revision)
        r.name, r.enabled = body.name, body.enabled
        r.data = validate_rule(
            db, user["id"], rules.RuleBody.model_validate(body.model_dump(exclude={"revision"}))
        )
        r.revision += 1
        return rule_out(r)


@router.delete("/rules/{id}")
def delete_rule(id: uuid.UUID, revision_value: int = Query(alias="revision"), user=User):
    with work(user) as db:
        r = owned(db, Rule, id, user["id"], True)
        revision(r, revision_value)
        db.delete(r)
        return {"ok": True}


class RuleOrder(Input):
    ids: list[uuid.UUID] = Field(max_length=500)


@router.put("/rules/order")
def order_rules(body: RuleOrder, user=User):
    with work(user) as db:
        rows = {r.id: r for r in db.scalars(select(Rule).where(Rule.user_id == user["id"]).with_for_update())}
        if set(rows) != set(body.ids) or len(body.ids) != len(rows):
            raise ApiError(409, "RULES_CHANGED", "Your rules changed. Refresh and reorder again")
        for i, rid in enumerate(body.ids, 1):
            rows[rid].position = i
        return {"items": [rule_out(rows[rid]) for rid in body.ids]}


class Instruction(Input):
    instruction: str = Field(min_length=3, max_length=2000)


@router.post("/rules/interpret")
def interpret_rule(body: Instruction, user=User):
    with work(user) as db:
        subjects = [
            {"id": str(s.id), "name": s.name, "kind": s.kind}
            for s in db.scalars(select(Subject).where(Subject.user_id == user["id"]))
        ]
    try:
        preview, meta = ai.interpret_rule(body.instruction, subjects)
    except ai.AIUnavailable as exc:
        raise ApiError(503, "AI_UNAVAILABLE", f"{exc}. Use the simple rule editor instead")
    try:
        rule = rules.RuleBody.model_validate(
            {**preview.model_dump(exclude={"unsupported"}), "instruction": body.instruction, "enabled": True}
        )
    except ValueError:
        raise ApiError(422, "RULE_NOT_UNDERSTOOD", "That instruction could not become a supported rule")
    with work(user) as db:
        validate_rule(db, user["id"], rule)
    # A preview only: the student must confirm before the rule is saved and activated.
    return {"rule": rule.model_dump(mode="json"), "unsupported": preview.unsupported, "model": meta}


# --- Merges and evidence -----------------------------------------------------------------------


class MergeInput(Input):
    surviving_task_id: uuid.UUID
    absorbed_task_id: uuid.UUID
    surviving_revision: int = Field(ge=1)
    absorbed_revision: int = Field(ge=1)


@router.post("/task-merges", status_code=201)
def merge_tasks(body: MergeInput, request: Request, user=User):
    with work(user) as db:
        cached, op = replay(db, request, user, body.model_dump(mode="json"))
        if cached is not None:
            return cached
        if body.surviving_task_id == body.absorbed_task_id:
            raise ApiError(422, "INVALID_MERGE", "Choose two different tasks")
        keep = owned(db, Task, body.surviving_task_id, user["id"], True)
        gone = owned(db, Task, body.absorbed_task_id, user["id"], True)
        revision(keep, body.surviving_revision)
        revision(gone, body.absorbed_revision)
        if keep.data.get("mergedInto") or gone.data.get("mergedInto"):
            raise ApiError(409, "ALREADY_MERGED", "One of these tasks was already merged")
        if keep.type != gone.type:
            raise ApiError(422, "INVALID_MERGE", "An assignment and a test cannot be merged")
        if keep.subject_id and gone.subject_id and keep.subject_id != gone.subject_id:
            # Different theory/lab/tutorial subjects never merge, even with similar titles or codes.
            raise ApiError(422, "INVALID_MERGE", "Tasks for different subjects cannot be merged")
        moved = []
        for ev in db.scalars(
            select(TaskEvidence).where(TaskEvidence.task_id == gone.id, TaskEvidence.state == "active")
        ):
            ev.state = "reassigned"
            if not db.scalar(
                select(TaskEvidence).where(
                    TaskEvidence.task_id == keep.id, TaskEvidence.event_id == ev.event_id
                )
            ):
                db.add(
                    TaskEvidence(
                        user_id=keep.user_id,
                        task_id=keep.id,
                        event_id=ev.event_id,
                        method="merge",
                        state="active",
                    )
                )
            moved.append(str(ev.event_id))
        before = {
            "completedAt": keep.completed_at.isoformat() if keep.completed_at else None,
            "completion": keep.data.get("completion"),
        }
        if gone.completed_at and not keep.completed_at:
            keep.completed_at = gone.completed_at
            keep.data = {**keep.data, "completion": gone.data.get("completion") or {"origin": "manual"}}
        keep.data = {
            **keep.data,
            "sources": sorted({*keep.data.get("sources", []), *gone.data.get("sources", [])}) or None,
        }
        if not keep.data["sources"]:
            keep.data = {k: v for k, v in keep.data.items() if k != "sources"}
        keep.status = effective_status(keep, now())
        gone.data = {**gone.data, "mergedInto": str(keep.id)}
        keep.revision += 1
        gone.revision += 1
        merge = MergeOperation(
            user_id=keep.user_id,
            surviving_task_id=keep.id,
            absorbed_task_id=gone.id,
            data={"movedEvents": moved, "survivorBefore": before},
        )
        db.add(merge)
        db.flush()
        manual_history(db, keep, "merged", {"absorbedTaskId": str(gone.id), "mergeId": str(merge.id)})
        manual_history(db, gone, "merged_into", {"survivingTaskId": str(keep.id), "mergeId": str(merge.id)})
        return finish(
            db,
            op,
            {
                "id": str(merge.id),
                "survivingTaskId": str(keep.id),
                "absorbedTaskId": str(gone.id),
                "movedEvidence": len(moved),
            },
        )


@router.post("/task-merges/{id}/undo")
def undo_merge(id: uuid.UUID, request: Request, user=User):
    with work(user) as db:
        cached, op = replay(db, request, user, {})
        if cached is not None:
            return cached
        merge = owned(db, MergeOperation, id, user["id"], True)
        if merge.undone_at:
            raise ApiError(409, "ALREADY_UNDONE", "This merge was already undone")
        keep = db.scalar(select(Task).where(Task.id == merge.surviving_task_id).with_for_update())
        gone = db.scalar(select(Task).where(Task.id == merge.absorbed_task_id).with_for_update())
        moved = [uuid.UUID(e) for e in merge.data.get("movedEvents", [])]
        for ev in db.scalars(
            select(TaskEvidence).where(
                TaskEvidence.task_id == keep.id,
                TaskEvidence.event_id.in_(moved),
                TaskEvidence.method == "merge",
            )
        ):
            db.delete(ev)
        for ev in db.scalars(
            select(TaskEvidence).where(TaskEvidence.task_id == gone.id, TaskEvidence.event_id.in_(moved))
        ):
            ev.state = "active"
        before = merge.data.get("survivorBefore", {})
        decision = keep.data.get("latestManualDecision") or {}
        if decision.get("recordedAt", "") < merge.created_at.isoformat():
            # Restore the survivor's own completion unless the student decided again after merging.
            keep.completed_at = datetime_or_none(before.get("completedAt"))
            keep.data = {**keep.data, "completion": before.get("completion")}
        keep.status = effective_status(keep, now())
        gone.data = {k: v for k, v in gone.data.items() if k != "mergedInto"}
        keep.revision += 1
        gone.revision += 1
        merge.undone_at = now()
        manual_history(db, keep, "merge_undone", {"mergeId": str(merge.id)})
        manual_history(db, gone, "merge_undone", {"mergeId": str(merge.id)})
        return finish(db, op, {"ok": True, "restoredTaskId": str(gone.id)})


def datetime_or_none(value):
    from datetime import datetime

    return datetime.fromisoformat(value) if value else None


class Reassign(Input):
    task_id: uuid.UUID


@router.post("/evidence/{id}/reassign")
def reassign_evidence(id: uuid.UUID, body: Reassign, request: Request, user=User):
    with work(user) as db:
        cached, op = replay(db, request, user, body.model_dump(mode="json"))
        if cached is not None:
            return cached
        ev = owned(db, TaskEvidence, id, user["id"], True)
        if ev.state != "active":
            raise ApiError(409, "EVIDENCE_MOVED", "This evidence was already reassigned")
        source = db.scalar(select(Task).where(Task.id == ev.task_id).with_for_update())
        target = owned(db, Task, body.task_id, user["id"], True)
        if target.id == source.id or target.data.get("mergedInto"):
            raise ApiError(422, "INVALID_TARGET", "Choose another active task")
        event = db.get(SourceEvent, ev.event_id)
        ev.state = "reassigned"
        if not db.scalar(
            select(TaskEvidence).where(TaskEvidence.task_id == target.id, TaskEvidence.event_id == event.id)
        ):
            db.add(
                TaskEvidence(
                    user_id=target.user_id,
                    task_id=target.id,
                    event_id=event.id,
                    method="reassigned",
                    state="active",
                )
            )
        completion = source.data.get("completion") or {}
        if source.completed_at and completion.get("eventId") == str(event.id):
            # Recalculate from remaining evidence and decisions: this receipt no longer supports completion.
            source.completed_at = None
            source.data = {**source.data, "completion": None}
            source.status = effective_status(source, now())
            source.revision += 1
            manual_history(
                db,
                source,
                "reopened",
                {"reason": "completion evidence reassigned", "_eventId": str(event.id)},
            )
        manual_history(
            db, source, "evidence_reassigned", {"toTaskId": str(target.id), "_eventId": str(event.id)}
        )
        if event.event_type == "submission" and not target.completed_at:
            path = (
                "classroom_turned_in"
                if event.data.get("method") == "classroom_submission"
                else "lms_assignment_receipt"
            )
            if path in interpret.completion_paths():
                interpret.complete_task(db, target, event, path)
        manual_history(
            db, target, "evidence_reassigned", {"fromTaskId": str(source.id), "_eventId": str(event.id)}
        )
        target.revision += 1
        db.flush()
        return finish(
            db,
            op,
            {
                "ok": True,
                "fromTask": task_view(source, db, user["id"]),
                "toTask": task_view(target, db, user["id"]),
            },
        )


@router.get("/tasks/{id}/evidence")
def task_evidence(id: uuid.UUID, user=User):
    with work(user) as db:
        owned(db, Task, id, user["id"])
        out = []
        for ev, event, record in db.execute(
            select(TaskEvidence, SourceEvent, SourceRecord)
            .join(SourceEvent, SourceEvent.id == TaskEvidence.event_id)
            .join(SourceRecord, SourceRecord.id == SourceEvent.source_record_id)
            .where(TaskEvidence.task_id == id, TaskEvidence.user_id == user["id"])
            .order_by(SourceEvent.occurred_at.desc().nulls_last())
        ):
            out.append(
                {
                    "id": str(ev.id),
                    "eventId": str(event.id),
                    "eventType": event.event_type,
                    "method": ev.method,
                    "state": ev.state,
                    "occurredAt": event.occurred_at.isoformat() if event.occurred_at else None,
                    "sourceKind": record.kind,
                    "sender": record.sender_email,
                    "sourceTitle": record.title,
                    "links": event.data.get("links", []),
                    "excerpt": event.data.get("excerpt"),
                    "validation": event.data.get("validation"),
                    "targeting": event.data.get("targeting"),
                    "outcome": event.outcome,
                }
            )
        return {"items": out}


@router.get("/review-items/{id}")
def get_review(id: uuid.UUID, user=User):
    with work(user) as db:
        item = owned(db, ReviewItem, id, user["id"])
        record = db.get(SourceRecord, item.source_record_id) if item.source_record_id else None
        if record and record.expires_at and record.expires_at <= now():
            raise ApiError(410, "REVIEW_EXPIRED", "This review has expired")
        if item.status != "open":
            raise ApiError(410, "REVIEW_CLOSED", "This review has already been settled")
        return review_out(item, db)
