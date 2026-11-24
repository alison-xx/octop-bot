"""``task_plan``, ``task_check`` and ``task_finish``: the model states the task, proves each
criterion, and cannot call it done while one has no verdict.

Every tool returns the whole task as JSON. The chat client reads the latest one to draw the
task card, and the model sees the same state it is working against.
"""

from __future__ import annotations

import json
import time
from typing import Any, Literal

from langchain_core.tools import StructuredTool
from langgraph.config import get_config
from pydantic import ValidationError

from octop.infra.bot_tasks.model import (
    DEFAULT_BUDGET,
    MAX_CRITERIA,
    STALE_SECONDS,
    Budget,
    Criterion,
    Task,
    Tier,
)
from octop.infra.bot_tasks.store import TaskStore

TASK_TOOL_NAMES = frozenset({"task_plan", "task_check", "task_finish"})

PLAN_DESCRIPTION = """Start (or revise) the task for this conversation before doing real work: \
several steps, the computer, or files to deliver. Not for questions or one-step requests.

goal: what the user wants, in their words. criteria: 2-5 checks that prove it is done, each \
one you can verify (e.g. "the sheet lists Q3 prices for all three companies in CNY"). \
assumptions: what you decided instead of asking. tier: "deep" only for long or irreversible \
work. Track the steps with write_todos. Calling it again while the task runs revises it."""

CHECK_DESCRIPTION = """Record the verdict on one acceptance criterion (1-based number) with \
evidence you actually observed: a command's output, a file check (pages, rows), a screenshot \
you looked at, a message or receipt id. status: passed, failed (say what is wrong) or skipped \
(say why). Never mark passed what you did not verify."""

REVIEW_FIRST = (
    "Refused: this is a deep task, so an independent reviewer checks it before it is done. "
    'Call `task` with a description starting with "Review:" and give the reviewer only the '
    "user's request, the acceptance criteria with your evidence, and where the results are, "
    "not your reasoning. Ask it to report each criterion as met or not and why. Fix what it "
    "finds (task_check again), then call task_finish. Anything still wrong after the second "
    "review goes into open_issues."
)

FINISH_DESCRIPTION = """Close the task once every criterion has a verdict from task_check. \
summary: one or two sentences on the result. open_issues: what is not done or not verified. \
After this, reply briefly; the user sees the checklist as a card. Refused while a criterion \
has no verdict."""


def _thread_id() -> str:
    try:
        return str((get_config().get("configurable") or {}).get("thread_id") or "")
    except RuntimeError:  # outside a graph run
        return ""


def snapshot(task: Task, note: str = "") -> str:
    """The task as the tool result: JSON the client parses and the model reads."""
    payload: dict[str, Any] = {"task": task.model_dump(mode="json")}
    if note:
        payload["note"] = note
    return json.dumps(payload, ensure_ascii=False)


def _clean(items: list[str], limit: int) -> list[str]:
    return [s.strip()[:300] for s in items if s and s.strip()][:limit]


def task_tools(store: TaskStore) -> list[StructuredTool]:
    def _plan(
        goal: str,
        criteria: list[str],
        assumptions: list[str] | None = None,
        tier: Tier = "standard",
    ) -> str:
        thread = _thread_id()
        texts = _clean(criteria, MAX_CRITERIA)
        if not goal.strip() or not texts:
            return "Refused: give a goal and at least one checkable criterion."
        now = time.time()
        current = store.running(thread)
        if current is not None and now - current.updated_at > STALE_SECONDS:
            current.status = "stopped"
            current.finished_at = now
            store.save(thread, current)
            current = None
        steps, minutes = DEFAULT_BUDGET[tier]
        try:
            if current is None:
                task = Task(
                    goal=goal.strip()[:200],
                    tier=tier,
                    criteria=[Criterion(text=t) for t in texts],
                    assumptions=_clean(assumptions or [], 10),
                    budget=Budget(steps=steps, minutes=minutes),
                )
                note = "Task started. Do the work, then task_check each criterion."
            else:
                # Revising keeps the verdicts of criteria whose wording did not change.
                kept = {c.text: c for c in current.criteria}
                task = current.model_copy(
                    update={
                        "goal": goal.strip()[:200],
                        "tier": tier,
                        "criteria": [kept.get(t) or Criterion(text=t) for t in texts],
                        "assumptions": _clean(assumptions or [], 10) or current.assumptions,
                        "budget": Budget(steps=steps, minutes=minutes)
                        if tier != current.tier
                        else current.budget,
                        "updated_at": now,
                    }
                )
                note = "Task revised."
        except ValidationError as exc:
            return f"Refused: {exc.errors()[0].get('msg', 'invalid task')}"
        return snapshot(store.save(thread, task), note)

    def _check(
        criterion: int,
        status: Literal["passed", "failed", "skipped"],
        evidence: str,
    ) -> str:
        thread = _thread_id()
        task = store.running(thread)
        if task is None:
            return "Refused: no task is running in this conversation; call task_plan first."
        if not 1 <= criterion <= len(task.criteria):
            return f"Refused: criterion must be 1 to {len(task.criteria)}."
        proof = evidence.strip()
        if not proof:
            return "Refused: give the evidence you observed (or, for skipped, the reason)."
        task.criteria[criterion - 1] = Criterion(
            text=task.criteria[criterion - 1].text, status=status, evidence=proof[:1000]
        )
        task.updated_at = task.checked_at = time.time()
        return snapshot(store.save(thread, task))

    def _finish(summary: str, open_issues: list[str] | None = None) -> str:
        thread = _thread_id()
        task = store.running(thread)
        if task is None:
            return "Refused: no task is running in this conversation."
        missing = task.unchecked()
        if missing:
            numbers = ", ".join(str(n) for n in missing)
            return (
                f"Refused: criteria {numbers} have no verdict yet. Verify them and call "
                "task_check (passed, failed or skipped with a reason) first."
            )
        if task.needs_review():
            return REVIEW_FIRST
        now = time.time()
        task.status = task.verdict()
        task.summary = summary.strip()[:2000]
        task.open_issues = _clean(open_issues or [], 10)
        task.finished_at = task.updated_at = now
        note = (
            "Done. Reply in a sentence or two; do not repeat the checklist."
            if task.status == "done"
            else "Finished, not complete. Tell the user plainly what is missing; do not "
            "call it done."
        )
        return snapshot(store.save(thread, task), note)

    # Each call reads, changes and saves the conversation's task under its lock.
    def task_plan(
        goal: str,
        criteria: list[str],
        assumptions: list[str] | None = None,
        tier: Tier = "standard",
    ) -> str:
        with store.locked(_thread_id()):
            return _plan(goal, criteria, assumptions, tier)

    def task_check(
        criterion: int,
        status: Literal["passed", "failed", "skipped"],
        evidence: str,
    ) -> str:
        with store.locked(_thread_id()):
            return _check(criterion, status, evidence)

    def task_finish(summary: str, open_issues: list[str] | None = None) -> str:
        with store.locked(_thread_id()):
            return _finish(summary, open_issues)

    return [
        StructuredTool.from_function(
            func=task_plan, name="task_plan", description=PLAN_DESCRIPTION
        ),
        StructuredTool.from_function(
            func=task_check, name="task_check", description=CHECK_DESCRIPTION
        ),
        StructuredTool.from_function(
            func=task_finish, name="task_finish", description=FINISH_DESCRIPTION
        ),
    ]
