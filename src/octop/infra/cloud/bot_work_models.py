"""Octop Bot's personal, hosted conversations and schedules."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

Id = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,159}$")]
AccountId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]
Status = Literal["queued", "running", "waiting_user", "paused", "completed", "failed", "cancelled"]


class Write(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    account_id: AccountId = Field(description="The cloud account shown when the user confirmed.")


class Turn(Write):
    request_id: UUID = Field(description="Keep this ID when reconciling an uncertain submission.")
    session_id: Id | None = None
    message: str = Field(min_length=1, max_length=32000)
    model: str | None = Field(default=None, min_length=1, max_length=160)
    bot_id: Id | None = Field(
        default=None, description="An explicitly selected, locally owned Bot."
    )
    input_task_id: Id | None = None

    @model_validator(mode="after")
    def answer_targets_one_task(self) -> Self:
        if self.input_task_id and (not self.session_id or self.bot_id or self.model):
            raise ValueError("A task answer requires its session and uses its existing role/model")
        return self


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frequency: Literal["once", "daily", "weekdays", "weekly", "monthly"]
    weekdays: list[Annotated[int, Field(ge=1, le=7)]] = Field(default_factory=list, max_length=7)
    month_day: int = Field(default=1, ge=1, le=31, serialization_alias="monthDay")
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    timezone: str = Field(min_length=1, max_length=64)
    once_at: AwareDatetime | None = Field(default=None, serialization_alias="onceAt")

    @model_validator(mode="after")
    def validate_rule(self) -> Self:
        if self.frequency == "weekly" and not self.weekdays:
            raise ValueError("Select at least one weekday")
        if self.frequency == "once" and self.once_at is None:
            raise ValueError("Select the time of the first run")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Unknown timezone") from exc
        return self


class CreateSchedule(Write):
    name: str = Field(min_length=1, max_length=45)
    instruction: str = Field(min_length=1, max_length=4000)
    bot_id: Id | None = None
    rule: Rule


class EnableSchedule(Write):
    enabled: bool


class CancelTask(Write):
    session_id: Id
    request_id: UUID


class Capabilities(BaseModel):
    enabled: bool
    reason: str | None = None
    models: list[str]
    default_model: str | None = None


class Task(BaseModel):
    id: Id
    session_id: Id
    status: Status
    model: str
    created_at: str
    updated_at: str
    result: str | None = None
    error: str | None = None
    question: str | None = None
    waiting_for: str | None = None
    can_answer: bool


class SessionSummary(BaseModel):
    id: Id
    title: str
    model: str
    updated_at: str
    message_count: int


class Sessions(BaseModel):
    items: list[SessionSummary]
    next_cursor: str | None = None


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: str | None = None
    task_id: str | None = None


class Session(BaseModel):
    id: Id
    title: str
    model: str
    updated_at: str
    items: list[Message]
    tasks: list[Task]


class Schedule(BaseModel):
    id: Id
    name: str
    instruction: str
    bot_name: str | None
    rule_text: str
    finished_once: bool
    enabled: bool
    next_run_at: str | None
    last_run_at: str | None
    last_status: str
    last_result_preview: str
    last_error: str
    session_id: Id
    run_count: int


class Schedules(BaseModel):
    items: list[Schedule]
