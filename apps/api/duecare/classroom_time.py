"""Classroom deadline conversion shared by import and interpretation."""

from datetime import UTC, datetime


def due_at(item):
    date, clock = item.get("dueDate"), item.get("dueTime")
    # A due time of 00:00 UTC arrives as an empty object ({}), which still means midnight.
    if not date or clock is None or not all(k in date for k in ("year", "month", "day")):
        return None
    # Classroom due dates and times are UTC values.
    return datetime(
        date["year"], date["month"], date["day"], clock.get("hours", 0), clock.get("minutes", 0), tzinfo=UTC
    )
