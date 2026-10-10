"""Ordered hide and priority rules over an allowlisted condition structure.

Rules run only after the complete sender blocklist and academic applicability checks. They apply to
every task, existing and new, and are re-applied whenever rules change: a priority rule sets the
task's rule priority, a hide rule keeps imported work out of the student's lists (never deletes it).
They never suppress submission evidence, never define batches, and never execute code or queries.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FIELDS = ("source", "sender", "subjectId", "subjectKind", "taskType", "keyword", "assessmentLabel")


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: Literal["source", "sender", "subjectId", "subjectKind", "taskType", "keyword", "assessmentLabel"]
    op: Literal["equals", "contains", "in"] = "equals"
    value: str | list[str]

    @model_validator(mode="after")
    def shape(self):
        values = self.value if isinstance(self.value, list) else [self.value]
        if not values or any(not isinstance(v, str) or not v.strip() or len(v) > 300 for v in values):
            raise ValueError("Condition values must be short non-empty text")
        if len(values) > 50:
            raise ValueError("Too many condition values")
        return self


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["include", "exclude", "priority"]
    priority: Literal["low", "medium", "high", "critical"] | None = None

    @model_validator(mode="after")
    def shape(self):
        if (self.type == "priority") != (self.priority is not None):
            raise ValueError("Priority actions need a priority; relevance actions do not")
        return self


class RuleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    instruction: str | None = Field(None, max_length=2000)
    match: Literal["all", "any"] = "all"
    conditions: list[Condition] = Field(min_length=1, max_length=10)
    exceptions: list[Condition] = Field(default_factory=list, max_length=10)
    action: Action


def _matches(cond, facts):
    actual = facts.get(cond.field)
    values = [v.strip().lower() for v in (cond.value if isinstance(cond.value, list) else [cond.value])]
    if cond.field == "keyword":
        text = (facts.get("text") or "").lower()
        return any(v in text for v in values)
    if actual is None:
        return False
    # A task can come from several sources and senders: any of them matches.
    for one in actual if isinstance(actual, (list, set, tuple)) else [actual]:
        one = str(one).lower()
        if (cond.op == "contains" and any(v in one for v in values)) or one in values:
            return True
    return False


def rule_matches(body: RuleBody, facts):
    hits = [_matches(c, facts) for c in body.conditions]
    hit = all(hits) if body.match == "all" else any(hits)
    return hit and not any(_matches(c, facts) for c in body.exceptions)


def evaluate(rules, facts):
    """Return (relevance action or None, priority or None, matched rule ids)."""
    relevance = priority = None
    matched = {}
    for rule in rules:
        body = RuleBody.model_validate({"name": rule.get("name") or "rule", **rule["data"]})
        if not rule["enabled"] or not rule_matches(body, facts):
            continue
        if body.action.type in ("include", "exclude") and relevance is None:
            relevance, matched["relevance"] = body.action.type, rule["id"]
        if body.action.type == "priority" and priority is None:
            priority, matched["priority"] = body.action.priority, rule["id"]
    return relevance, priority, matched


# --- Plain-language rules without AI ---------------------------------------------------------------

PRIORITY_WORDS = [
    ("critical", r"\b(critical|urgent|top priority|most important)\b"),
    ("high", r"\b(high|important|higher)\b"),
    ("medium", r"\b(medium|normal|moderate)\b"),
    ("low", r"\b(low|lower|unimportant|not important)\b"),
]
HIDE_WORDS = re.compile(
    r"\b(hide|ignore|skip|exclude|remove|don'?t (show|add|track|want)|do not (show|add|track))\b", re.I
)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
QUOTED = re.compile(r"[\"“”']([^\"“”']{2,60})[\"“”']")
ABOUT = re.compile(
    r"\b(?:containing|contains|mentioning|mentions|with the word|about|saying|titled)\s+(.{2,60}?)\s*$", re.I
)


def parse(instruction, subjects, named_subject=None):
    """A rule from a plain sentence, when its words settle it ("make itvc high priority", "hide
    hackathon mail", "tests from classroom are critical"); None when AI is needed."""
    text = instruction.strip()
    low = text.lower()
    if HIDE_WORDS.search(low):
        action = {"type": "exclude"}
    else:
        level = next((p for p, pattern in PRIORITY_WORDS if re.search(pattern, low)), None)
        if not level:
            return None
        action = {"type": "priority", "priority": level}
    conditions = []
    if named_subject:
        many = isinstance(named_subject, list) and len(named_subject) > 1
        value = (
            named_subject
            if many
            else (named_subject[0] if isinstance(named_subject, list) else named_subject)
        )
        conditions.append({"field": "subjectId", "op": "in" if many else "equals", "value": value})
    if re.search(r"\b(tests?|exams?|quiz(zes)?|vivas?)\b", low) and not re.search(r"\bassignments?\b", low):
        conditions.append({"field": "taskType", "op": "equals", "value": "test"})
    elif re.search(r"\bassignments?\b", low) and not re.search(r"\b(tests?|exams?)\b", low):
        conditions.append({"field": "taskType", "op": "equals", "value": "assignment"})
    if re.search(r"\bclassroom\b", low):
        conditions.append({"field": "source", "op": "equals", "value": "classroom"})
    elif re.search(r"\bgmail\b", low):  # "hackathon mail" means messages, not every Gmail task.
        conditions.append({"field": "source", "op": "equals", "value": "gmail"})
    sender = EMAIL.search(text)
    if sender:
        conditions.append({"field": "sender", "op": "equals", "value": sender.group(0).lower()})
    keyword = QUOTED.search(text) or ABOUT.search(text)
    if keyword:
        conditions.append({"field": "keyword", "op": "contains", "value": keyword.group(1).strip(" .")})
    elif not conditions and action["type"] == "exclude":
        # "hide hackathon mail": the leftover word after the action is what to hide.
        rest = re.sub(
            r"\b(hide|ignore|skip|exclude|remove|don'?t|do not|show|add|track|want|any|all|"
            r"every|tasks?|work|mails?|e-?mails?|posts?|things?|stuff|the|from|about|for)\b",
            " ",
            low,
        )
        words = [w for w in re.findall(r"[a-z0-9][a-z0-9-]{2,}", rest)]
        if len(words) == 1:
            conditions.append({"field": "keyword", "op": "contains", "value": words[0]})
    if not conditions:
        return None
    name = text[:1].upper() + text[1:80]
    return RuleBody.model_validate(
        {"name": name, "instruction": text, "conditions": conditions, "action": action, "enabled": True}
    )
