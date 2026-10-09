"""Deterministic interpretation of recognized college LMS (Moodle) notification templates.

Only the configured LMS sender's known templates are parsed here; anything else goes to AI
interpretation. Labelled absolute dates (DUE, OPENS, CLOSES, When) are used; countdowns and
due/overdue labels are never status authority. Activity links are compared as identifiers and are
never visited.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from . import targeting

IST = ZoneInfo("Asia/Kolkata")
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], 1)}  # fmt: skip
DATE = re.compile(
    r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday),?\s+(\d{1,2})\s+([a-z]+)\s+(\d{4})"
    r"(?:,?\s+(\d{1,2}):(\d{2})\s*(am|pm))?",
    re.I,
)
CLOCK = re.compile(r"(\d{1,2}):(\d{2})\s*(am|pm)", re.I)
ACTIVITY = re.compile(r"/mod/(assign|quiz|forum)/(?:view|discuss)\.php", re.I)
RECEIPT = re.compile(r"you have submitted an assignment submission for '(.+?)'\.", re.I | re.S)
RECEIPT_HTML = re.compile(
    r"your assignment submission for ['\u2018\u2019](.+?)['\u2018\u2019] has been submitted\.", re.I
)
RECEIPT_SUBJECT = re.compile(
    r"^(?:assignment|quiz|test) submission confirmation\b|^submission confirmation\s*:", re.I
)
QUIZ_RECEIPT = re.compile(
    r"thank you for submitting your answers to ['\u2018\u2019](.+?)['\u2018\u2019] in course ['\u2018\u2019](.+?)['\u2018\u2019] at ",
    re.I,
)
QUIZ_AUTOSUBMIT = re.compile(
    r"the time for the quiz ['\u2018\u2019](.+?)['\u2018\u2019] in the course ['\u2018\u2019](.+?)['\u2018\u2019] expired\. "
    r"your answers were submitted automatically at ",
    re.I,
)


@dataclass
class Candidate:
    intent: str
    task_type: str | None
    title: str
    course_label: str | None
    identity_key: str | None
    timing: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)
    duration_minutes: int | None = None
    links: list = field(default_factory=list)
    template: str = ""
    row: int | None = None


def flat(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_date(text, default_time=None):
    """Absolute LMS date in IST. Returns (UTC iso, precision) or (None, None)."""
    m = DATE.search(flat(text))
    if not m or m.group(2).lower() not in MONTHS:
        return None, None
    day, month, year = int(m.group(1)), MONTHS[m.group(2).lower()], int(m.group(3))
    if m.group(4):
        hour, minute, half = int(m.group(4)), int(m.group(5)), m.group(6).lower()
    elif default_time:
        hour, minute, half = default_time
    else:
        return None, None
    hour = hour % 12 + (12 if half.lower() == "pm" else 0)
    return datetime(year, month, day, hour, minute, tzinfo=IST).astimezone(
        ZoneInfo("UTC")
    ).isoformat(), "source-exact"


def activity_key(url):
    """Namespaced activity identifier: host + module + id. An association signal, not authentication."""
    parsed = urlparse(url)
    m = ACTIVITY.search(parsed.path)
    query = parse_qs(parsed.query)
    ident = (query.get("id") or query.get("d") or [None])[0]
    if not m or not ident or not ident.isdigit():
        return None
    return f"lms:{parsed.hostname}:{m.group(1).lower()}:{ident}"


def first_activity(links):
    for link in links:
        key = activity_key(link)
        if key:
            return key
    return None


def subject_title(subject):
    """Title after the labelled time in subjects like 'Due on Monday, 5 October 2026, 10:06 AM: Exp 5'."""
    m = re.search(r"\d{1,2}:\d{2}\s*[AP]M:\s*(.+)$", subject, re.I)
    return flat(m.group(1)) if m else None


def footnotes(text):
    return {int(n): url for n, url in re.findall(r"^\[(\d+)\]\s+(https?://\S+)", text, re.M)}


def provenance(fields, phrase, template):
    return {
        f: {"basis": "source-exact", "timezone": "Asia/Kolkata", "phrase": phrase[:200], "template": template}
        for f in fields
    }


def course_from(text):
    m = re.search(r"in course (.+?_(?:ODD|EVEN)_\d{2}-\d{2})", flat(text))
    return m.group(1) if m else None


def parse(subject, text, links):
    """Return (template name, candidates) or (None, []) when the message is not a known template."""
    body, subject = text or "", flat(subject)
    plain = flat(body)
    m = RECEIPT.search(plain) or RECEIPT_HTML.search(plain)
    if subject.lower().startswith("assignment submission confirmation") and m:
        crumb = re.match(r"^(\S+?)\s*->\s*Assignment\s*->", plain)
        return "assignment_receipt", [
            Candidate(
                intent="submission",
                task_type="assignment",
                title=flat(m.group(1)),
                course_label=crumb.group(1) if crumb else None,
                identity_key=first_activity([lnk for lnk in links if "/mod/assign/view.php" in lnk]),
                template="assignment_receipt",
            )
        ]
    quiz = QUIZ_RECEIPT.search(plain) or QUIZ_AUTOSUBMIT.search(plain)
    if (
        RECEIPT_SUBJECT.search(subject)
        and quiz
        and "this message confirms that your answers have been saved" in plain.lower()
    ):
        return "quiz_receipt", [
            Candidate(
                intent="submission",
                task_type="test",
                title=flat(quiz.group(1)),
                course_label=flat(quiz.group(2)),
                identity_key=first_activity([lnk for lnk in links if "/mod/quiz/view.php" in lnk]),
                template="quiz_receipt",
            )
        ]
    if subject.lower().startswith("due on ") and "is due soon" in plain.lower():
        title = re.search(r"the assignment (.+?) in course", plain, re.I)
        due, _ = (
            parse_date(re.search(r"DUE:\s*(.+?)(?:Go to activity|$)", plain, re.I).group(1))
            if "DUE:" in plain.upper()
            else (None, None)
        )
        return "due_soon", [
            Candidate(
                intent="due_notice",
                task_type="assignment",
                title=subject_title(subject) or (flat(title.group(1)) if title else subject),
                course_label=course_from(plain),
                identity_key=first_activity(links),
                timing={"dueAt": due} if due else {},
                provenance=provenance(["dueAt"], "DUE", "due_soon") if due else {},
                template="due_soon",
            )
        ]
    if subject.lower().startswith("overdue:") and "was due on" in plain.lower():
        due, _ = parse_date(plain.split("was due on", 1)[1])
        return "overdue", [
            Candidate(
                intent="due_notice",
                task_type="assignment",
                title=flat(subject.split(":", 1)[1]),
                course_label=course_from(plain),
                identity_key=first_activity(links),
                timing={"dueAt": due} if due else {},
                provenance=provenance(["dueAt"], "was due on", "overdue") if due else {},
                template="overdue",
            )
        ]
    if subject.lower().startswith("opens on ") and "opening soon" in plain.lower():
        opens = re.search(r"OPENS:\s*(.+?)CLOSES:", plain, re.I)
        closes = re.search(r"CLOSES:\s*(.+?)(?:Go to quiz|$)", plain, re.I)
        o, _ = parse_date(opens.group(1)) if opens else (None, None)
        c, _ = parse_date(closes.group(1)) if closes else (None, None)
        title = re.search(r"the quiz (.+?) in course", plain, re.I)
        timing = {"availabilityOpensAt": o, "availabilityClosesAt": c}
        return "quiz_window", [
            Candidate(
                intent="new_work",
                task_type="test",
                title=subject_title(subject) or (flat(title.group(1)) if title else subject),
                course_label=course_from(plain),
                identity_key=first_activity(links),
                timing={k: v for k, v in timing.items() if v},
                provenance=provenance([k for k, v in timing.items() if v], "OPENS/CLOSES", "quiz_window"),
                template="quiz_window",
            )
        ]
    if subject.lower().startswith("you have assignments due"):
        heading = re.search(r"due on (.+?\d{4})\.", plain, re.I)
        notes = footnotes(body)
        rows = []
        for i, row in enumerate(re.finditer(
            r"^\*\s+(.+?) in course (.+?)\s*DUE:\s*(\d{1,2}:\d{2}\s*[AP]M)\s*Go to activity \[(\d+)\]",
            re.sub(r"\n(?!\*|\[)", " ", body), re.M | re.I,
        )):  # fmt: skip
            # Each digest row is parsed independently; the heading does not decide every row.
            clock = CLOCK.search(row.group(3))
            due, _ = (
                parse_date(heading.group(1), (int(clock.group(1)), int(clock.group(2)), clock.group(3)))
                if heading and clock
                else (None, None)
            )
            link = notes.get(int(row.group(4)))
            rows.append(
                Candidate(
                    intent="due_notice",
                    task_type="assignment",
                    title=flat(row.group(1)),
                    course_label=flat(row.group(2)),
                    identity_key=activity_key(link) if link else None,
                    timing={"dueAt": due} if due else {},
                    provenance=provenance(["dueAt"], "digest row DUE", "digest") if due else {},
                    template="digest",
                    row=i,
                )
            )
        return "digest", rows
    reminder = re.match(
        r"^\[LMS-Reminder\]\s*(OVERDUE:\s*)?\((.+?)-(Assignment|Quiz)\)\s*(.+?)\s+(is due|closes|opens)$",
        subject,
        re.I,
    )
    if reminder:
        kind, verb = reminder.group(3).lower(), reminder.group(5).lower()
        when = re.search(r"When\s*\|\s*(.+?)(?:Course\s*\||$)", plain, re.I)
        moment, _ = parse_date(when.group(1)) if when else (None, None)
        course = re.search(r"Course\s*\|\s*(.+?)\s*Activity\s*\|", plain, re.I)
        limit = re.search(r"Time limit\s*\|\s*(\d+)\s*min", plain, re.I)
        if kind == "assignment":
            field_name, task_type, intent = "dueAt", "assignment", "due_notice"
        else:
            field_name = "availabilityClosesAt" if verb == "closes" else "availabilityOpensAt"
            task_type, intent = "test", "due_notice"
        return "lms_reminder", [
            Candidate(
                intent=intent,
                task_type=task_type,
                title=flat(reminder.group(4)),
                course_label=flat(course.group(1)) if course else reminder.group(2),
                identity_key=first_activity(links),
                timing={field_name: moment} if moment else {},
                provenance=provenance([field_name], "When", "lms_reminder") if moment else {},
                duration_minutes=int(limit.group(1)) if limit else None,
                template="lms_reminder",
            )
        ]
    return None, []


def course_targeting(label):
    """Course-level audience from the course label, e.g. A-B-C-D_SY includes Division B."""
    return targeting.parse_course_label(label)


def course_name(label):
    parsed = targeting.parse_course_label(label or "")
    return parsed["course"] if parsed else label
