"""Increase a task's time limit only after the user accepts the new totals."""

from __future__ import annotations

import time
from typing import Any

from langchain_core.tools import StructuredTool
from langgraph.config import get_config
from pydantic import ValidationError

from octop.i18n import tr
from octop.infra.bot_tasks.approvals import ApprovalRules, ask
from octop.infra.bot_tasks.model import Budget
from octop.infra.bot_tasks.store import TaskStore
from octop.infra.bot_tasks.tools import snapshot
from octop.infra.utils.locale import resolve_user_locale


def task_budget_tool(
    store: TaskStore, rules: ApprovalRules, users: Any, agent: str, owner: int
) -> StructuredTool:
    def extend(task_id: str, minutes: int) -> str:
        config = get_config().get("configurable") or {}
        if config.get("octop_scheduled_turn"):
            return "This scheduled task reached its limit. Finish with the verified results."
        thread = str(config.get("thread_id") or "")
        task = store.running(thread)
        if not task or task.id != task_id:
            return "The task is no longer running."
        try:
            proposed = Budget(minutes=minutes)
        except ValidationError:
            return "Use a total time limit of 1–600 minutes."
        old = task.budget
        if old == proposed:
            return snapshot(task)
        if not task.budget_exhausted(time.time()) or minutes < old.minutes:
            return "Only exhausted budgets can be extended; increase the time limit."
        if time.time() - task.started_at >= minutes * 60:
            return "The requested totals have already been used."
        detail = tr(
            "octop_bot.approval.budget_detail",
            resolve_user_locale(user_repo=users, user_id=owner),
            old_minutes=old.minutes,
            minutes=minutes,
        )
        allowed, note = ask(
            rules=rules,
            user_repo=users,
            agent_id=agent,
            user_id=owner,
            category="budget",
            target=task.goal,
            detail=detail,
            offer_always=False,
        )
        if not allowed:
            return note
        with store.locked(thread):
            current = store.running(thread)
            if current is None or current.id != task_id or current.budget != old:
                return (
                    "The task or its limits changed while the card was open. Read the current task."
                )
            current.budget = proposed
            current.updated_at = time.time()
            return snapshot(store.save(thread, current))

    return StructuredTool.from_function(
        func=extend,
        name="task_extend_budget",
        description="Ask the user once to increase an exhausted task's time limit. Supply its task_id and new total minutes. If the user declines, finish with the verified results.",
    )
