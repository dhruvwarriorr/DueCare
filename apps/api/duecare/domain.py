from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from .errors import ApiError
from .schemas import TaskInput

IST = ZoneInfo("Asia/Kolkata")


def task_data(payload: TaskInput):
    d = payload.model_dump(mode="json", by_alias=True)
    for name in (
        "dueAt",
        "submissionOpensAt",
        "availabilityOpensAt",
        "availabilityClosesAt",
        "loginByAt",
        "reportingAt",
        "startsAt",
        "endsAt",
    ):
        value = d.get(name)
        if value:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                raise ApiError(
                    422, "INVALID_TIME", "Precise times must include a timezone", {name: "Timezone required"}
                )
            d[name] = dt.astimezone(UTC).isoformat()
    if d["dueDate"] and d["dueAt"]:
        raise ApiError(422, "INVALID_TIME", "Choose a date-only deadline or an exact cutoff, not both")
    if d["dueDate"]:
        if d["type"] == "assignment":
            dt = datetime.combine(payload.due_date, time(23, 59), IST)
            d["dueAt"] = dt.astimezone(UTC).isoformat()
            d["timingMode"] = "deadline_only"
        else:
            d["timingMode"] = "unresolved"
    if d["timingMode"] == "fixed_session":
        if d["type"] != "test" or not d["startsAt"]:
            raise ApiError(422, "INVALID_TIME", "A fixed-session test requires a confirmed start")
        if d["dueAt"] and d["dueAt"] != d["startsAt"]:
            raise ApiError(422, "INVALID_TIME", "Fixed-session cutoff must equal the test start")
        d["dueAt"] = d["startsAt"]
    if d["timingMode"] == "attempt_window":
        if d["type"] != "test" or not d["availabilityClosesAt"]:
            raise ApiError(422, "INVALID_TIME", "An attempt-window test requires a closing time")
        if d["dueAt"] and d["dueAt"] != d["availabilityClosesAt"]:
            raise ApiError(422, "INVALID_TIME", "Attempt-window cutoff must equal the closing time")
        d["dueAt"] = d["availabilityClosesAt"]
    if d["timingMode"] == "undated" and d["dueAt"]:
        d["timingMode"] = "deadline_only"
    if d["timingMode"] == "unresolved" and d["dueAt"]:
        raise ApiError(422, "INVALID_TIME", "Unresolved timing cannot have a precise cutoff")
    for a, b in [
        ("startsAt", "endsAt"),
        ("availabilityOpensAt", "availabilityClosesAt"),
        ("submissionOpensAt", "dueAt"),
        ("dateWindowStart", "dateWindowEnd"),
    ]:
        if d[a] and d[b] and d[a] >= d[b]:
            raise ApiError(422, "INVALID_TIME", f"{a} must precede {b}")
    d["timingProvenance"] = {
        k: {"basis": "student-entered", "timezone": "Asia/Kolkata"}
        for k in (
            "dueAt",
            "submissionOpensAt",
            "availabilityOpensAt",
            "availabilityClosesAt",
            "reportingAt",
            "loginByAt",
            "startsAt",
            "endsAt",
            "dateWindowStart",
            "dateWindowEnd",
        )
        if d[k]
    }
    if d["dueDate"] and d["type"] == "assignment":
        d["timingProvenance"]["dueAt"]["basis"] = "student-date-only"
        d["timingProvenance"]["dueAt"]["defaultTime"] = "23:59 IST"
    return d


def effective_status(task, at):
    if task.completed_at:
        return "completed"
    if task.due_at and at >= task.due_at:
        return "missed" if task.type == "test" else "overdue"
    return "due"


def priority(task, at):
    # Precedence: student override, first matching priority rule, deadline-based default.
    if task.data.get("priorityOverride"):
        return task.data["priorityOverride"]
    if (task.data.get("rulePriority") or {}).get("value"):
        return task.data["rulePriority"]["value"]
    hours = (task.due_at - at).total_seconds() / 3600 if task.due_at else None
    return (
        "critical"
        if hours is not None and hours <= 24
        else "high"
        if hours is not None and hours <= 72
        else "medium"
        if hours is not None and hours <= 168
        else "low"
    )
