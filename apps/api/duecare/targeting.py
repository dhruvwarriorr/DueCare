"""Academic applicability: compare observed source targeting with the student's profile.

Outcomes are processing results, separate from task statuses:
- ``applicable``: continue extraction and matching.
- ``mismatch``: explicit targeting excludes the student; ignore without task, review, or activity.
- ``review``: missing, ambiguous, or conflicting targeting; ask the student.

The profile's single general batch is the only student batch. Observed labels are evidence only and
never rewrite the profile. Room codes such as B115A are venues, not batches.
"""

import re

from .academic import branch_code, profile_data

YEARS = {
    "fy": 1, "first": 1, "1st": 1, "i": 1, "1": 1,
    "sy": 2, "second": 2, "2nd": 2, "ii": 2, "2": 2,
    "ty": 3, "third": 3, "3rd": 3, "iii": 3, "3": 3,
    "ly": 4, "fourth": 4, "final": 4, "4th": 4, "be": 4, "iv": 4, "4": 4,
}  # fmt: skip
ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}
# Course labels such as DS_B_ODD_26-27 or ITVC_A-B-C-D_SY_ODD_26-27.
COURSE_LABEL = re.compile(
    r"^(?P<course>.+?)_(?P<divisions>[A-Z](?:-[A-Z])*)(?:_(?P<year>FY|SY|TY|LY))?_(?P<term>ODD|EVEN)_(?P<span>\d{2}-\d{2})$"
)
BATCH = re.compile(r"\b([A-Z])\s?-?([1-9])\s*batch\b|\bbatch\s*-?\s*([A-Z]?\s?[1-9])\b", re.I)


def year_number(value):
    if value is None:
        return None
    text = str(value).strip().lower().replace(".", "").replace(" year", "")
    text = re.sub(r"\s+", " ", text)
    if text in YEARS:
        return YEARS[text]
    first = text.split(" ")[0]
    return YEARS.get(first)


def semester_number(value):
    if value is None:
        return None
    text = str(value).strip().lower().replace("semester", "").replace("sem", "").strip()
    if text.isdigit():
        return int(text)
    return ROMAN.get(text)


def student_context(profile):
    division = (profile.get("division") or "").strip().upper()
    batch = (profile.get("generalBatch") or "").strip().upper()
    labels = {batch}
    if division and batch.isdigit():
        labels.add(division + batch)  # Division B plus general batch 2 corresponds to B2.
    if division and batch.startswith(division) and batch[len(division) :].isdigit():
        labels.add(batch[len(division) :])
    return {
        "year": year_number(profile.get("classYear")),
        "semester": semester_number(profile.get("currentSemester")),
        "division": division,
        "batchLabels": {label for label in labels if label},
        "batch": batch,
    }


def parse_course_label(label):
    """Context from an LMS course short name; never a deadline."""
    if not label:
        return None
    match = COURSE_LABEL.match(label.strip())
    if not match:
        return None
    return {
        "course": match["course"],
        "divisions": match["divisions"].split("-"),
        "classYears": [match["year"]] if match["year"] else [],
        "term": f"{match['term']} {match['span']}",
        "scope": "course",
        "evidence": label.strip(),
    }


def batch_labels(text):
    """Explicit batch qualifiers such as 'B2 Batch' or 'Batch 2' (not room codes like B115A)."""
    found = set()
    for m in BATCH.finditer(text or ""):
        if m.group(1):
            found.add((m.group(1) + m.group(2)).upper())
        elif m.group(3):
            found.add(m.group(3).replace(" ", "").upper())
    return sorted(found)


def merge(*observations):
    """Combine course- and activity-level observations; activity qualifiers stay separate."""
    out = {"course": {}, "activity": {}}
    for obs in observations:
        if not obs:
            continue
        scope = "course" if obs.get("scope") == "course" else "activity"
        target = out[scope]
        for key in ("branches", "classYears", "semesters", "divisions", "batches"):
            if obs.get(key):
                target[key] = sorted({*target.get(key, []), *map(str, obs[key])})
        for key in ("allBatches", "allDivisions", "excludesStudent", "conditional"):
            if obs.get(key):
                target[key] = True
        if obs.get("evidence"):
            target.setdefault("evidence", []).append(str(obs["evidence"])[:300])
    return out


def evaluate(observed, profile, *, subject_kind=None, trusted=False):
    """Return (outcome, reason, question). ``trusted`` means a student-confirmed source context
    (an explicitly linked Classroom course or a personal LMS notification) establishes membership."""
    student = student_context(profile)
    student_branch = profile_data(profile)["branchCode"]
    question = None
    for scope in ("activity", "course"):
        obs = observed.get(scope, {})
        if obs.get("excludesStudent"):
            return "mismatch", f"{scope} explicitly excludes this class or batch", None
        branches = {branch_code(b) for b in obs.get("branches", [])}
        if branches:
            if student_branch and None not in branches and student_branch not in branches:
                return "mismatch", f"{scope} targets another branch", None
            if not student_branch or (None in branches and student_branch not in branches):
                question = "Does this branch targeting apply to you?"
        years = {year_number(y) for y in obs.get("classYears", [])} - {None}
        if years and student["year"] and student["year"] not in years:
            return "mismatch", f"{scope} targets another class/year", None
        semesters = {semester_number(s) for s in obs.get("semesters", [])} - {None}
        if semesters and student["semester"] and student["semester"] not in semesters:
            return "mismatch", f"{scope} targets another semester", None
        divisions = {d.strip().upper() for d in obs.get("divisions", [])}
        if divisions and not obs.get("allDivisions") and student["division"] not in divisions:
            return "mismatch", f"{scope} targets another division", None
        batches = {b.strip().upper() for b in obs.get("batches", [])}
        if batches and not obs.get("allBatches"):
            if not batches & student["batchLabels"]:
                # A naked digit cannot resolve division context; only explicit combined labels exclude.
                if all(b.isdigit() for b in batches) and not student["batch"].isdigit():
                    question = "Does this batch apply to you?"
                else:
                    return "mismatch", f"{scope} targets another batch", None
    activity, course = observed.get("activity", {}), observed.get("course", {})
    if activity.get("conditional") or course.get("conditional"):
        return "review", "conditional eligibility", "Does this eligibility condition apply to you?"
    if question:
        return "review", "ambiguous academic targeting", question
    batch_known = bool(
        ({b.upper() for b in activity.get("batches", [])} & student["batchLabels"])
        or activity.get("allBatches")
        or course.get("allBatches")
    )
    division_known = bool(
        student["division"]
        in {d.upper() for d in activity.get("divisions", []) + course.get("divisions", [])}
        or activity.get("allDivisions")
        or course.get("allDivisions")
        or batch_known
    )
    if subject_kind == "lab" and not (batch_known or trusted):
        return "review", "lab batch not stated", "Is this lab work for your batch?"
    if not (division_known or trusted):
        return "review", "audience not stated", "Is this work for your class and division?"
    return "applicable", "targeting confirmed", None
