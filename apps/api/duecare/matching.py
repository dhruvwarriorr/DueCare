"""Whether two notices describe the same piece of coursework.

Faculty announce one piece of work many ways: two or three teachers mail the same notice, a notice
is resent, a reminder or a follow-up arrives, a deadline moves. Within one subject and task type,
what names the work is its kind (assignment, experiment, IA, OST ...), its identifiers (Assignment 2,
Exp 5, IA-II, Part B, Module 3) and its topic; never who sent it, how it is phrased, which batch or
room it mentions, or when it is due. Dates are judged by the caller: a moved deadline is an update.

This module is pure text comparison. It never reads the database and never decides completion.
"""

import re
from dataclasses import dataclass

from . import naming, subject_link

# Canonical work kinds. Spelling variants, plurals and short forms map onto one word.
SYNONYMS = {
    "assignments": "assignment", "assign": "assignment", "asgn": "assignment", "assgn": "assignment",
    "asg": "assignment", "homework": "assignment", "hw": "assignment",
    "exp": "experiment", "expt": "experiment", "expts": "experiment", "exps": "experiment",
    "experiments": "experiment", "prac": "experiment", "pract": "experiment",
    "tut": "tutorial", "tuts": "tutorial", "tutorials": "tutorial",
    "quizzes": "quiz", "quizes": "quiz", "tests": "test", "exams": "exam", "examination": "exam",
    "examinations": "exam", "mcqs": "mcq", "oral": "viva", "orals": "viva", "vivas": "viva",
    "presentations": "presentation", "ppt": "presentation", "seminars": "seminar",
    "projects": "project", "reports": "report", "journals": "journal", "writeups": "writeup",
    "modules": "module", "mod": "module", "chapters": "chapter", "ch": "chapter", "chap": "chapter",
    "units": "unit", "parts": "part", "sets": "set", "sheets": "sheet", "worksheet": "sheet",
    "worksheets": "sheet", "lectures": "lecture", "weeks": "week", "labs": "lab",
}  # fmt: skip
# Phrases rewritten to one token before splitting into words.
PHRASES = [
    (r"internal\s+assessments?(?:\s+tests?)?", " ia "),
    (r"\bunit\s+tests?\b", " ut "),
    (r"\bcase\s+stud(?:y|ies)\b", " casestudy "),
    (r"\bmini[\s-]*projects?\b", " miniproject "),
    (r"\bwrite[\s-]*ups?\b", " writeup "),
    (r"\bend[\s-]*sem(?:ester)?(?:\s+exam(?:ination)?)?\b", " ese "),
    (r"\bmid[\s-]*sem(?:ester)?(?:\s+exam(?:ination)?)?\b", " mse "),
    (r"\bre[\s-]*(?:test|exam|examination|attempt|conduct(?:ion)?)\b", " retake "),
    (r"\bmake[\s-]*up\b", " retake "),
    (r"\b(?:a?tkt|backlog|supplementary|improvement)\b", " retake "),
    (r"\bpractical\s+(?:exam(?:ination)?|test)\b", " practicalexam "),
    (r"\bpractical\s+(?=(?:no\.?\s*|#\s*)?\d)", " experiment "),
    (r"\blab\s+(?=(?:no\.?\s*|#\s*)?\d)", " experiment "),
    (r"\bpart\s*[-:]?\s*([a-e])\b", r" part \1 "),
]
# Kinds of work. A notice naming no kind is generic within its task type.
KINDS = {"assignment", "experiment", "tutorial", "ia", "ut", "quiz", "test", "exam", "mcq", "viva", "ost",
         "ese", "mse", "practicalexam", "presentation", "seminar", "project", "miniproject", "report",
         "writeup", "journal", "casestudy", "sheet"}  # fmt: skip
# Kinds that only say how the work is handed in or held; they agree with any specific kind.
LOOSE_KINDS = {"test", "exam", "report", "writeup", "journal", "submission"}
# An assessment label covers the test words used with it ("IA 1 MCQ test" is IA 1).
ASSESSMENTS = {"ia", "ut", "ost", "ese", "mse"}
# Assessments held once per subject and term: naming one names the work.
SINGLE_SITTING = {"ost", "ese", "mse"}
TEST_WORDS = {"quiz", "test", "exam", "mcq"}
# Words that take a number: kinds name the work; scopes say which syllabus part it covers.
SCOPES = {"module", "chapter", "unit", "lecture"}
LABELS = KINDS | SCOPES | {"part", "set", "week", "no", "number"}
ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
            "eighth": 8, "ninth": 9, "tenth": 10}  # fmt: skip
# Delivery, audience and scheduling words: how a notice is phrased, not which work it is.
NOISE = naming.FILLER | {
    "re", "fw", "fwd", "reminder", "remind", "gentle", "kind", "kindly", "please", "pls", "plz", "dear",
    "students", "student", "all", "everyone", "class", "notice", "notification", "regarding", "reg",
    "update", "updated", "important", "urgent", "imp", "final", "last", "submit", "submission",
    "submissions", "submitted", "upload", "uploaded", "uploading", "deadline", "deadlines", "extended",
    "extension", "extend", "postponed", "postpone", "preponed", "prepone", "rescheduled", "reschedule",
    "revised", "revision", "change", "changed", "changes", "shifted", "moved", "new", "today", "tomorrow",
    "tonight", "yesterday", "week", "weeks", "day", "days", "mail", "email", "info", "information",
    "about", "related", "your", "you", "is", "are", "will", "be", "has", "have", "been", "of", "in",
    "with", "before", "after", "details", "detail", "schedule", "complete", "completion", "pending",
    "given", "conducted", "note", "attention", "follow", "up", "followup", "again", "once", "more",
    "same", "this", "that", "it", "as", "per", "only", "also", "should", "must", "can", "an", "a",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "mon", "tue", "tues",
    "wed", "thu", "thur", "thurs", "fri", "sat", "sun", "am", "pm", "hrs", "hours", "hour", "noon",
    "midnight", "eod", "batch", "batches", "division", "div", "divisions", "room", "lab", "labs",
    "classroom", "google", "online", "offline", "portal", "moodle", "lms", "link", "form", "sem",
    "semester", "year", "fy", "sy", "ty", "ly", "fe", "se", "te", "be", "marks", "mark", "out",
    "held", "scheduled", "conduct", "dated", "date", "time", "timing", "timings", "venue",
}  # fmt: skip
WORD = re.compile(r"[a-z]+|\d+(?:\.\d+)?(?:st|nd|rd|th)?")
# Batches (B2, Batch 2, A1-A4), rooms (B115A, 604), semesters and years are audience and venue.
AUDIENCE = re.compile(
    r"\b(?:batch(?:es)?|div(?:ision)?s?|sem(?:ester)?|room|venue|lab\s+no)\s*[-:.#]?\s*"
    r"(?:[a-z]?\d{1,4}[a-z]?|[ivx]+|[a-e])(?:\s*(?:,|/|&|and|-|to)\s*(?:[a-z]?\d{1,4}[a-z]?|[a-e]))*\b"
    r"|\b[a-e]\s?-?[1-9]\s*batch\b|\b[a-e][1-9]\b|\b[a-z]{1,2}\d{3,}[a-z]?\b",
    re.I,
)


@dataclass(frozen=True)
class Signature:
    kinds: frozenset  # Canonical kinds the text names.
    ids: frozenset  # (label, value): ("assignment", "2"), ("part", "b"), ("", "3") for a bare number.
    scopes: frozenset  # (scope, value): ("module", "3").
    topic: frozenset  # Remaining words: what the work is about.
    retake: bool  # A re-test, make-up or KT sitting is different work from the regular one.

    @property
    def specific_kinds(self):
        return self.kinds - LOOSE_KINDS


def _subject_words(subject):
    """Every word of the subject's name, code and short forms; they say which course, not which work."""
    if not subject:
        return set()
    names = [subject.get("name"), subject.get("code"), *(subject.get("aliases") or [])]
    folded = {re.sub(r"[^a-z0-9]", "", (n or "").lower()) for n in names if n}
    for key, aliases in subject_link.COURSE_NAMES.items():  # DBMS, COA ... and their long names
        variants = [key, *aliases]
        if folded & {re.sub(r"[^a-z0-9]", "", v.lower()) for v in variants}:
            names.extend(variants)
    return {w for n in names if n for w in re.findall(r"[a-z]+", n.lower())}


def signature(*texts, subject=None):
    """Signature of a notice from its title and labels (assessment, deliverable)."""
    text = " ".join(t for t in texts if t)
    text = naming.undated(naming.PREFIX.sub("", text)).casefold()
    text = AUDIENCE.sub(" ", text)
    for pattern, replacement in PHRASES:
        text = re.sub(pattern, replacement, text)
    # Split joined identifiers: "ia1", "exp-5", "assignment#2", "ia-ii".
    text = re.sub(r"([a-z])[-_#.]*(?=\d)", r"\1 ", text)
    text = re.sub(r"(\d)(?=[a-z]{2,})", r"\1 ", text)
    words = [SYNONYMS.get(w, w) for w in WORD.findall(text)]
    course = _subject_words(subject)
    kinds, ids, scopes, topic, retake = set(), set(), set(), set(), False
    label = None  # The last label word still waiting for its number.
    for i, w in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else None
        if w == "retake":
            retake = True
            continue
        if w in LABELS:
            if w in KINDS:
                kinds.add(w)
            if w not in ("no", "number"):
                label = w
            continue
        value = None
        if re.fullmatch(r"\d+(?:\.\d+)?", w):
            value = w
        elif re.fullmatch(r"\d+(?:st|nd|rd|th)", w) or w in ORDINALS:
            # "2nd assignment" names the work; a lone "15th" is a date the date reader missed.
            if nxt in LABELS or label:
                value = str(ORDINALS.get(w) or int(re.match(r"\d+", w).group()))
        elif w in ROMAN and label:
            value = str(ROMAN[w])
        elif len(w) == 1 and label == "part":
            value = w
        if value is not None:
            if value.isdigit() and len(value) >= 3:
                label = None
                continue  # A year, room or roll number, not an identifier.
            if value.isdigit():
                value = str(int(value))
            elif "." in value:
                value = value.rstrip("0").rstrip(".")
            if label in SCOPES:
                scopes.add((label, value))
            elif label:
                ids.add((label, value))
            elif nxt in KINDS:
                ids.add((nxt, value))  # "2nd assignment"
            else:
                ids.add(("", value))
            label = None
            continue
        label = None
        if w in course or w in NOISE or w in ORDINALS or w in ROMAN or len(w) < 2 or not w.isalpha():
            continue
        topic.add(w)
    if kinds & ASSESSMENTS:
        kinds -= TEST_WORDS
        ids = {(k if k not in TEST_WORDS else next(iter(kinds & ASSESSMENTS)), v) for k, v in ids}
    return Signature(frozenset(kinds), frozenset(ids), frozenset(scopes), frozenset(topic), retake)


def _ids_agree(a, b):
    """None when the identifiers contradict, True when they are the same, False when one adds detail."""
    for label in {lab for lab, _ in a} & {lab for lab, _ in b} - {""}:
        if {v for lab, v in a if lab == label} != {v for lab, v in b if lab == label}:
            return None  # Exp 5 / Exp 6, IA 1 / IA 2.
    values_a, values_b = {v for _, v in a}, {v for _, v in b}
    if values_a == values_b:
        return True  # A bare number agrees with the same number under a label.
    if values_a <= values_b or values_b <= values_a:
        return False  # Assignment 2 / Assignment 2 Part B.
    return None


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


SAME, LIKELY, GENERIC, POSSIBLE, DIFFERENT = "same", "likely", "generic", "possible", "different"
RANK = {SAME: 0, LIKELY: 1, GENERIC: 2, POSSIBLE: 3, DIFFERENT: 9}


def compare(a, b):
    """How surely two signatures (same subject and task type) are the same work.

    same      identical identifiers (Assignment 2 / Asgn-2 reminder / 2nd assignment): the same work
              whatever dates the notices state.
    likely    the same topic, or agreeing identifiers with extra detail: the same work when the dates
              agree, or when the newer notice says the date moved.
    generic   one notice names no identifier or topic ("DBMS assignment submission"): the same work
              only when both state the same day.
    possible  partial overlap: the student is asked.
    different contradicting identifiers, kinds, scopes, or a re-test against the regular sitting.
    """
    if a.retake != b.retake:
        return DIFFERENT
    if a.specific_kinds and b.specific_kinds and not a.specific_kinds & b.specific_kinds:
        return DIFFERENT
    for scope, value in a.scopes:
        theirs = {v for s, v in b.scopes if s == scope}
        if theirs and value not in theirs:
            return DIFFERENT
    if a.specific_kinds & b.specific_kinds & SINGLE_SITTING and not (
        a.ids and b.ids and _ids_agree(a.ids, b.ids) is None
    ):
        return SAME  # "DBMS OST" / "OST examination on 13th Oct".
    topic_a, topic_b = a.topic | {f"{s}{v}" for s, v in a.scopes}, b.topic | {f"{s}{v}" for s, v in b.scopes}
    overlap = jaccard(topic_a, topic_b)
    unrelated = bool(topic_a and topic_b) and not topic_a & topic_b
    if a.ids and b.ids:
        agree = _ids_agree(a.ids, b.ids)
        if agree is None:
            return DIFFERENT
        if agree:
            # Identifiers decide; two disjoint, substantial topics suggest a typo in one notice.
            return LIKELY if unrelated and min(len(a.topic), len(b.topic)) >= 2 else SAME
        return LIKELY if not unrelated else POSSIBLE
    if a.ids or b.ids:
        if topic_a and topic_b:
            return LIKELY if overlap >= 0.6 else POSSIBLE if overlap >= 0.34 else DIFFERENT
        return GENERIC
    if topic_a and topic_b:
        small = min(len(topic_a), len(topic_b))
        if overlap >= 0.6 or (small >= 2 and (topic_a <= topic_b or topic_b <= topic_a)):
            return LIKELY
        return POSSIBLE if overlap >= 0.34 else DIFFERENT
    return GENERIC


RESCHEDULED = re.compile(
    r"\b(postpon\w*|prepon\w*|reschedul\w*|extend\w*|extension|revis\w*|chang\w*|shift\w*|moved|"
    r"new\s+(?:date|deadline|time)|instead\s+of|now\s+(?:on|due|be)|delay\w*|updated?)\b",
    re.I,
)


def says_rescheduled(*texts):
    return bool(RESCHEDULED.search(" ".join(t for t in texts if t)))
