"""Small, content-free inbox events written in the same transaction as their trigger."""

import uuid

from sqlalchemy import select

from .models import Activity


def notify(db, uid, event_type, target_type, target_id, message, key=None):
    key = key or str(uuid.uuid4())
    if not db.scalar(select(Activity.id).where(Activity.user_id == uid, Activity.event_key == key)):
        db.add(
            Activity(
                user_id=uid,
                event_key=key,
                event_type=event_type,
                target_type=target_type,
                target_id=target_id,
                message=message,
            )
        )


def task_changed(db, task, action, changes, event=None):
    if action in ("created", "imported"):
        kind, message = "new_task", "New work was added to your tasks."
    elif action == "reopened":
        kind, message = "reopened", "A task was reopened."
    elif action in ("edited", "source_update") and changes:
        kind, message = "revision", "Task details changed. Open the task to see its history."
    else:
        return
    key = f"{event.id}:{kind}" if event else None
    notify(db, task.user_id, kind, "task", task.id, message, key)
