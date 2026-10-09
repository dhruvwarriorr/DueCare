"""Fixed KJSSE BTech profile context and the student's selectable branch."""

import re

BRANCHES = {
    "COMPS": "Computer Engineering",
    "IT": "Information Technology",
    "AIDS": "Artificial Intelligence & Data Science",
    "CSBS": "Computer Science & Business Systems",
    "VLSI": "Electronics Engineering (VLSI Design & Technology)",
    "CCE": "Computer & Communication Engineering",
    "EXTC": "Electronics & Telecommunication Engineering",
    "EXCP": "Electronics & Computer Engineering",
    "MECH": "Mechanical Engineering",
    "RAI": "Robotics & Artificial Intelligence",
    "CIVIL": "Civil Engineering",
}


def normalized(value):
    return re.sub(r"[^a-z0-9]", "", (value or "").lower().replace("&", "and"))


def branch_code(value):
    """Resolve an exact code/full-name equivalent, never a fuzzy branch guess."""
    needle = normalized(value)
    return next(
        (code for code, name in BRANCHES.items() if needle in (normalized(code), normalized(name))),
        None,
    )


def profile_data(data):
    """Read legacy departments safely; persist the canonical shape on the next profile save."""
    code = branch_code(data.get("branchCode") or data.get("department"))
    out = {k: v for k, v in data.items() if k not in ("department", "admissionYear", "branchName")}
    return {
        **out,
        "institution": "KJSSE",
        "programme": "BTech",
        "branchCode": code,
        "branchName": BRANCHES.get(code),
    }


def context(data):
    p = profile_data(data)
    return {
        k: p.get(k)
        for k in (
            "institution",
            "programme",
            "branchCode",
            "branchName",
            "classYear",
            "currentSemester",
            "division",
            "generalBatch",
        )
    }
