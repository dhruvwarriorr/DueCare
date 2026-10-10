"""Merging two tasks that are the same work, by the student or automatically.

The absorbed task's evidence moves to the survivor, completion carries over, and a merge record
keeps everything needed to undo it. The absorbed task stays as a hidden "merged into" stub.
"""

from sqlalchemy import select

from .domain import effective_status
from .models import MergeOperation, TaskEvidence, now


def merge(db, keep, gone, note):
    """Merge gone into keep. note(task, action, changes) records history in the caller's voice."""
    moved = []
    for ev in db.scalars(
        select(TaskEvidence).where(TaskEvidence.task_id == gone.id, TaskEvidence.state == "active")
    ):
        ev.state = "reassigned"
        if not db.scalar(
            select(TaskEvidence).where(TaskEvidence.task_id == keep.id, TaskEvidence.event_id == ev.event_id)
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
    sources = sorted({*keep.data.get("sources", []), *gone.data.get("sources", [])})
    keep.data = {k: v for k, v in keep.data.items() if k != "sources"}
    if sources:
        keep.data = {**keep.data, "sources": sources}
    keep.status = effective_status(keep, now())
    gone.data = {**gone.data, "mergedInto": str(keep.id)}
    keep.revision += 1
    gone.revision += 1
    operation = MergeOperation(
        user_id=keep.user_id,
        surviving_task_id=keep.id,
        absorbed_task_id=gone.id,
        data={"movedEvents": moved, "survivorBefore": before},
    )
    db.add(operation)
    db.flush()
    note(keep, "merged", {"absorbedTaskId": str(gone.id), "mergeId": str(operation.id)})
    note(gone, "merged_into", {"survivingTaskId": str(keep.id), "mergeId": str(operation.id)})
    return operation
