"""Ordered relevance and priority rules over an allowlisted condition structure.

Rules run only after the complete sender blocklist and academic applicability checks. They decide
inclusion of newly detected tasks and rule priority; they never suppress submission evidence or
updates to existing tasks, never define batches, and never execute code or queries.
"""

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
    actual = str(actual).lower()
    if cond.op == "contains":
        return any(v in actual for v in values)
    return actual in values


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
