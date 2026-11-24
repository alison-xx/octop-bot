"""A Bot task: what the user asked for, how to tell it is done, and what proves it."""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field

from octop.infra.utils.ulid import new_ulid

Tier = Literal["standard", "deep"]
TaskStatus = Literal["running", "done", "partial", "stopped"]
CheckStatus = Literal["pending", "passed", "failed", "skipped"]

MAX_CRITERIA = 8
# Defaults until the user sets their own; a deep task gets more room.
DEFAULT_BUDGET: dict[str, tuple[int, int]] = {"standard": (60, 30), "deep": (150, 90)}
# A running task nobody touched for this long is treated as abandoned by the next plan.
STALE_SECONDS = 6 * 60 * 60


class Criterion(BaseModel):
    text: str = Field(max_length=300)
    status: CheckStatus = "pending"
    evidence: str = Field(default="", max_length=1000)


class Budget(BaseModel):
    steps: int = Field(ge=1, le=500)
    minutes: int = Field(ge=1, le=600)


class Task(BaseModel):
    id: str = Field(default_factory=new_ulid)
    goal: str = Field(max_length=200)
    tier: Tier = "standard"
    status: TaskStatus = "running"
    criteria: list[Criterion] = Field(default_factory=list, max_length=MAX_CRITERIA)
    assumptions: list[str] = Field(default_factory=list, max_length=10)
    budget: Budget
    started_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    finished_at: float | None = None
    summary: str = Field(default="", max_length=2000)
    open_issues: list[str] = Field(default_factory=list, max_length=10)

    def unchecked(self) -> list[int]:
        """1-based numbers of criteria still without a verdict."""
        return [i + 1 for i, c in enumerate(self.criteria) if c.status == "pending"]

    def verdict(self) -> TaskStatus:
        return "done" if all(c.status == "passed" for c in self.criteria) else "partial"
