"""Deterministic reading of dates and times written in college sources.

Indian sources write numeric dates day first (10/8/26 is 10 August 2026). These helpers find the
calendar dates a text states, so model output can be checked against the source and a stated date
can still be recovered when AI is unavailable. They never guess: an ambiguous text yields nothing.
"""

import re
from datetime import date, datetime, time, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}  # fmt: skip
MONTH = (
    r"(?P<m>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
ORD = r"(?:st|nd|rd|th)?"
YEAR = r"(?P<y>\d{4}|'\d{2})"
PATTERNS = [
    re.compile(r"\b(?P<y>\d{4})-(?P<mn>\d{1,2})-(?P<d>\d{1,2})\b"),
    re.compile(
        r"(?<![\d/.\-])(?P<d>\d{1,2})\s*[/.\-]\s*(?P<mn>\d{1,2})\s*[/.\-]\s*(?P<y>\d{4}|\d{2})(?![\d/])"
    ),
    re.compile(rf"\b(?P<d>\d{{1,2}}){ORD}(?:\s+of)?[\s\-/,]*{MONTH}(?:[\s,\-/]*{YEAR})?\b", re.I),
    re.compile(rf"\b{MONTH}\s*(?P<d>\d{{1,2}}){ORD}\b(?:,?\s*{YEAR})?", re.I),
]
CLOCK = re.compile(
    r"(?<![\d:/.])(?P<h>\d{1,2})(?:\s*[:.]\s*(?P<min>[0-5]\d))?\s*(?P<ap>a\.?\s?m\.?|p\.?\s?m\.?)(?![a-z])"
    r"|(?<![\d:/.])(?P<h24>[01]?\d|2[0-3])\s*:\s*(?P<min24>[0-5]\d)(?![\d:])(?!\s*(?:a\.?m|p\.?m))"
    r"|\b(?P<noon>noon|midday)\b",
    re.I,
)
# "9-11am": the first figure inherits the meridiem of the second.
CLOCK_RANGE = re.compile(
    r"(?<![\d:/.])(?P<h>\d{1,2})(?:[:.](?P<min>[0-5]\d))?\s*(?:-|–|to)\s*\d{1,2}(?:[:.][0-5]\d)?\s*"
    r"(?P<ap>a\.?\s?m\.?|p\.?\s?m\.?)(?![a-z])",
    re.I,
)
SIGNAL = re.compile(
    r"\b(today|tonight|tomorrow|day after tomorrow|yesterday|this week|next week|this weekend|"
    r"(?:this|next|coming|on)\s+(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*|"
    r"mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:rs(?:day)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?|"
    r"deadline|due|by\s+\d|before\s+\d|on or before|last date)\b",
    re.I,
)


def _year(raw, ref):
    if not raw:
        return None
    raw = raw.lstrip("'")
    return int(raw) + 2000 if len(raw) == 2 else int(raw)


def _closest(month, day, ref):
    """A date written without a year is the occurrence nearest the source's own time."""
    options = []
    for year in (ref.year - 1, ref.year, ref.year + 1):
        try:
            options.append(date(year, month, day))
        except ValueError:
            continue
    return min(options, key=lambda d: abs((d - ref).days)) if options else None


def find_dates(text, ref):
    """Distinct calendar dates stated in text, in order of appearance. ref is a date."""
    found, spans = [], []
    for pattern in PATTERNS:
        for m in pattern.finditer(text or ""):
            if any(a < m.end() and m.start() < b for a, b in spans):
                continue
            g = m.groupdict()
            day = int(g["d"])
            month = MONTHS[g["m"][:3].lower()] if g.get("m") else int(g["mn"])
            if pattern is PATTERNS[1] and month > 12 and day <= 12:
                day, month = month, day  # Written month first; only possible reading.
            year = _year(g.get("y"), ref)
            try:
                value = date(year, month, day) if year else _closest(month, day, ref)
            except ValueError:
                value = None
            if value:
                spans.append((m.start(), m.end()))
                found.append((m.start(), value))
    out = []
    for _, value in sorted(found, key=lambda x: x[0]):
        if value not in out:
            out.append(value)
    return out


def find_times(text):
    """Distinct clock times stated in text. A range contributes only its start."""
    out, spans = [], []

    def add(h, minute, ap, start, end):
        if ap:
            if h > 12:
                return
            pm = ap.lower().startswith("p")
            h = (h % 12) + (12 if pm else 0)
        value = time(h, minute)
        spans.append((start, end))
        if value not in out:
            out.append(value)

    for m in CLOCK_RANGE.finditer(text or ""):
        add(int(m["h"]), int(m["min"] or 0), m["ap"], m.start(), m.end())
    for m in CLOCK.finditer(text or ""):
        if any(a < m.end() and m.start() < b for a, b in spans):
            continue
        if m["noon"]:
            add(12, 0, None, m.start(), m.end())
        elif m["h"]:
            add(int(m["h"]), int(m["min"] or 0), m["ap"], m.start(), m.end())
        else:
            add(int(m["h24"]), int(m["min24"]), None, m.start(), m.end())
    return out


def mentions_timing(text, ref):
    return bool(find_dates(text, ref)) or bool(SIGNAL.search(text or ""))


def day_first(value, text, ref):
    """Correct a model's month/day swap: keep a date the text states, else take its swapped reading
    when only that one is stated (10/8/26 read as 8 October becomes 10 August)."""
    if not value or value.day > 12 or value.day == value.month:
        return value
    stated = find_dates(text, ref)
    if value in stated:
        return value
    try:
        swapped = value.replace(month=value.day, day=value.month)
    except ValueError:
        return value
    return swapped if swapped in stated else value


def single(text, ref):
    """The one date (and time, when exactly one is stated) a short text gives, else None."""
    dates = find_dates(text, ref)
    if len(dates) != 1:
        return None
    times = find_times(text)
    clock = times[0] if len(times) == 1 else None
    return dates[0], clock


def at_ist(day, clock):
    return datetime.combine(day, clock, IST)
