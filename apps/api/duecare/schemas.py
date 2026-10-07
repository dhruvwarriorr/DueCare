from datetime import date, datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class Input(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid", str_strip_whitespace=True
    )


class ProfilePatch(Input):
    revision: int = Field(ge=1)
    institution: str | None = Field(None, min_length=1, max_length=200)
    programme: str | None = Field(None, min_length=1, max_length=200)
    department: str | None = Field(None, min_length=1, max_length=200)
    admission_year: int | None = Field(None, ge=1950, le=2200)
    class_year: str | None = Field(None, min_length=1, max_length=100)
    current_semester: int | None = Field(None, ge=1, le=30)
    division: str | None = Field(None, min_length=1, max_length=50)
    general_batch: str | None = Field(None, min_length=1, max_length=50)
    roll_number: str | None = Field(None, min_length=1, max_length=100)
    theme: Literal["system", "light", "dark"] | None = None


class SubjectInput(Input):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["theory", "lab", "tutorial"]
    code: str | None = Field(None, max_length=100)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    term: str | None = Field(None, max_length=100)
    class_code: str | None = Field(None, max_length=100)
    revision: int | None = Field(None, ge=1)


class SlotInput(Input):
    id: UUID | None = None
    weekday: int = Field(ge=1, le=7)
    start_time: time
    end_time: time
    location: str | None = Field(None, max_length=200)
    instructor: str | None = Field(None, max_length=200)
    valid_from: date | None = None
    valid_until: date | None = None

    @model_validator(mode="after")
    def interval(self):
        if self.start_time.tzinfo or self.end_time.tzinfo:
            raise ValueError("Weekly slots use local Asia/Kolkata times")
        if self.end_time <= self.start_time:
            raise ValueError("End time must be after start time")
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("Validity end must not precede its start")
        return self


class TimetableInput(Input):
    revision: int = Field(ge=1)
    slots: list[SlotInput]


class TaskInput(Input):
    title: str = Field(min_length=1, max_length=300)
    type: Literal["assignment", "test"]
    subject_id: UUID | None = None
    instructions: str = Field("", max_length=20000)
    notes: str = Field("", max_length=20000)
    estimated_effort_minutes: int | None = Field(None, gt=0, le=100000)
    priority_override: Literal["low", "medium", "high", "critical"] | None = None
    assessment_label: str | None = Field(None, max_length=200)
    deliverable_label: str | None = Field(None, max_length=200)
    location: str | None = Field(None, max_length=200)
    syllabus: str | None = Field(None, max_length=10000)
    permitted_tools: str | None = Field(None, max_length=10000)
    preparation_instructions: str | None = Field(None, max_length=10000)
    timing_mode: Literal["deadline_only", "fixed_session", "attempt_window", "unresolved", "undated"] = (
        "undated"
    )
    due_at: datetime | None = None
    due_date: date | None = None
    submission_opens_at: datetime | None = None
    availability_opens_at: datetime | None = None
    availability_closes_at: datetime | None = None
    login_by_at: datetime | None = None
    reporting_at: datetime | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    date_window_start: date | None = None
    date_window_end: date | None = None
    duration_minutes: int | None = Field(None, gt=0)


class TaskPatch(Input):
    revision: int = Field(ge=1)
    # Field validation is applied to the merged TaskInput, preventing partial-update bypasses.
    title: str | None = None
    type: Literal["assignment", "test"] | None = None
    subject_id: UUID | None = None
    instructions: str | None = None
    notes: str | None = None
    estimated_effort_minutes: int | None = None
    priority_override: Literal["low", "medium", "high", "critical"] | None = None
    assessment_label: str | None = None
    deliverable_label: str | None = None
    location: str | None = None
    syllabus: str | None = None
    permitted_tools: str | None = None
    preparation_instructions: str | None = None
    timing_mode: str | None = None
    due_at: datetime | None = None
    due_date: date | None = None
    submission_opens_at: datetime | None = None
    availability_opens_at: datetime | None = None
    availability_closes_at: datetime | None = None
    login_by_at: datetime | None = None
    reporting_at: datetime | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    date_window_start: date | None = None
    date_window_end: date | None = None
    duration_minutes: int | None = None
    status: Literal["due", "completed"] | None = None


class AuthorizeInput(Input):
    service: Literal["gmail", "classroom", "both"] = "both"
    account_id: UUID | None = None


class SyncInput(Input):
    trigger: Literal["open", "focus", "manual"] = "manual"


class SenderPreferenceInput(Input):
    action: Literal["include", "block"]
    revision: int | None = Field(None, ge=1)
