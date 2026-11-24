"""Keeps a Bot's task honest without calling a model.

- Briefs the model on the task contract (when to plan, evidence, the finish gate).
- Counts the steps of the running task: a note at 80% of its step or time budget, and once
  the budget is spent, work tools are refused until the model finishes or asks the user.
- The same tool failing the same way three times gets a note to stop retrying it.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.config import get_config
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from octop.infra.bot_tasks.model import Task
from octop.infra.bot_tasks.store import TaskStore
from octop.infra.bot_tasks.tools import TASK_TOOL_NAMES

# Talking to the user and keeping the plan never count against the budget.
FREE_TOOLS = TASK_TOOL_NAMES | {"ask_user_question", "write_todos", "request_takeover"}
WARN_AT = 0.8
SAME_ERROR_LIMIT = 3

BRIEFING = """## Tasks
When a request needs real work (several steps, the computer, files to deliver), treat it as \
a task. Questions and one-step requests are not tasks: just answer.
1. Call `task_plan` first: the goal in the user's words, 2-5 acceptance criteria you can \
check, and the assumptions you made instead of asking. Keep the steps with `write_todos`.
2. Ask at most one round of questions, and only when the answer changes what you make; \
otherwise write it down as an assumption and go on.
3. Verify each criterion and record it with `task_check` and real evidence: a command's \
output, a file check (pages, rows, opens without error), a screenshot you looked at, a \
receipt or message id. Never mark passed what you did not check.
4. Call `task_finish` last, then reply in a sentence or two; the user sees the checklist as a \
card. If a criterion failed or was skipped, say plainly what is missing; never call it done."""

BUDGET_NEAR = (
    "Note: this task has used {used} of its {what} budget ({limit}). Wrap up: finish what "
    "matters most, verify it, and call task_finish."
)
BUDGET_SPENT = (
    "Refused: this task has used its whole {what} budget ({limit}). Call task_finish with what "
    "is done and what is not, or ask the user (ask_user_question) whether to continue."
)
SAME_ERROR = (
    "Note: `{tool}` has now failed the same way {count} times in this task. Do not try it "
    "again the same way: change the approach, or tell the user what is blocking you."
)


def _configurable() -> dict[str, Any]:
    try:
        return dict(get_config().get("configurable") or {})
    except RuntimeError:  # outside a graph run
        return {}


def _with_note(result: ToolMessage | Command[Any], note: str) -> ToolMessage | Command[Any]:
    """Append ``note`` to the tool's own message (also inside a Command's update)."""

    def noted(message: ToolMessage) -> ToolMessage:
        content = message.content
        if isinstance(content, str):
            return message.model_copy(update={"content": f"{content}\n\n{note}"})
        if isinstance(content, list):
            return message.model_copy(
                update={"content": [*content, {"type": "text", "text": note}]}
            )
        return message

    if isinstance(result, ToolMessage):
        return noted(result)
    update = result.update if isinstance(result.update, dict) else None
    if update and isinstance(update.get("messages"), list):
        messages = [noted(m) if isinstance(m, ToolMessage) else m for m in update["messages"]]
        return replace(result, update={**update, "messages": messages})
    return result


def _error_text(result: ToolMessage | Command[Any]) -> str | None:
    if isinstance(result, ToolMessage) and result.status == "error":
        return str(result.content)[:200]
    return None


class TaskWatch:
    """Per-process counters for running tasks (a restart forgets them, which is harmless)."""

    def __init__(self) -> None:
        self.steps: dict[str, int] = {}
        self.warned: set[str] = set()
        self.errors: dict[str, dict[str, int]] = {}

    def spent(self, task: Task, now: float) -> tuple[str, str] | None:
        """(what, limit) when a budget is used up, else None."""
        if self.steps.get(task.id, 0) >= task.budget.steps:
            return "step", f"{task.budget.steps} steps"
        if now - task.started_at >= task.budget.minutes * 60:
            return "time", f"{task.budget.minutes} minutes"
        return None

    def near(self, task: Task, now: float) -> str | None:
        if task.id in self.warned:
            return None
        steps = self.steps.get(task.id, 0)
        minutes = (now - task.started_at) / 60
        if steps >= WARN_AT * task.budget.steps:
            self.warned.add(task.id)
            return BUDGET_NEAR.format(
                used=f"{steps} steps", what="step", limit=f"{task.budget.steps} steps"
            )
        if minutes >= WARN_AT * task.budget.minutes:
            self.warned.add(task.id)
            return BUDGET_NEAR.format(
                used=f"{int(minutes)} minutes", what="time", limit=f"{task.budget.minutes} minutes"
            )
        return None

    def failed(self, task: Task, tool: str, error: str) -> int:
        seen = self.errors.setdefault(task.id, {})
        key = f"{tool}\n{error}"
        seen[key] = seen.get(key, 0) + 1
        return seen[key]


class BotTaskMiddleware(AgentMiddleware[Any, Any]):
    """Task briefing in the system prompt plus the watchdog around tool calls.

    ``always``: on every turn (a cloud tenant's Bot); otherwise only on Octop Bot client turns,
    where the task tools are shown.
    """

    def __init__(self, store: TaskStore, *, always: bool = False) -> None:
        self._store = store
        self._always = always
        self._watch = TaskWatch()

    def _active(self) -> bool:
        return self._always or _configurable().get("octop_bot_browser") is True

    def _brief(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
        if not self._active():
            return request
        blocks: list[Any] = (
            list(request.system_message.content_blocks) if request.system_message else []
        )
        blocks.append({"type": "text", "text": f"\n\n{BRIEFING}" if blocks else BRIEFING})
        return request.override(system_message=SystemMessage(content_blocks=blocks))

    def wrap_model_call(
        self, request: ModelRequest[Any], handler: Callable[[ModelRequest[Any]], ModelResponse[Any]]
    ) -> ModelResponse[Any]:
        return handler(self._brief(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        return await handler(self._brief(request))

    # -- tool calls -------------------------------------------------------------

    def _before(self, request: ToolCallRequest) -> tuple[Task | None, ToolMessage | None]:
        name = str(request.tool_call.get("name") or "")
        if name in FREE_TOOLS or not self._active():
            return None, None
        thread = str(_configurable().get("thread_id") or "")
        task = self._store.running(thread) if thread else None
        if task is None:
            return None, None
        spent = self._watch.spent(task, time.time())
        if spent:
            what, limit = spent
            return task, ToolMessage(
                content=BUDGET_SPENT.format(what=what, limit=limit),
                name=name,
                tool_call_id=str(request.tool_call.get("id") or ""),
                status="error",
            )
        self._watch.steps[task.id] = self._watch.steps.get(task.id, 0) + 1
        return task, None

    def _after(
        self, request: ToolCallRequest, task: Task, result: ToolMessage | Command[Any]
    ) -> ToolMessage | Command[Any]:
        notes: list[str] = []
        error = _error_text(result)
        if error is not None:
            name = str(request.tool_call.get("name") or "")
            count = self._watch.failed(task, name, error)
            if count >= SAME_ERROR_LIMIT:
                notes.append(SAME_ERROR.format(tool=name, count=count))
        near = self._watch.near(task, time.time())
        if near:
            notes.append(near)
        return _with_note(result, "\n".join(notes)) if notes else result

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        task, refused = self._before(request)
        if refused is not None:
            return refused
        result = handler(request)
        return self._after(request, task, result) if task is not None else result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        task, refused = self._before(request)
        if refused is not None:
            return refused
        result = await handler(request)
        return self._after(request, task, result) if task is not None else result
