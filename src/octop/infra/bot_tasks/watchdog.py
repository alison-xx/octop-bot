"""Keeps a Bot's task honest without calling a model.

- Briefs the model on the task contract (when to plan, evidence, the finish gate), and puts the
  running task back in the prompt when compacting the conversation dropped it.
- Asks for a plan before the first real work of a turn: the first call that writes a file,
  runs a command or drives the screen without a running task is sent back once.
- Records the independent review of a deep task (a ``task`` sub-agent call whose description
  starts with "Review:"), which ``task_finish`` waits for.
- Counts the steps of the running task: a note at 80% of its step or time budget, and once
  the budget is spent, work tools are refused until the model finishes or asks the user.
- The same tool failing the same way three times gets a note to stop retrying it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.config import get_config
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from octop.i18n import tr
from octop.infra.bot_tasks.deliverables import inspect_file
from octop.infra.bot_tasks.model import Deliverable, Task
from octop.infra.bot_tasks.model_silence import ModelSilence, watch_model_output
from octop.infra.bot_tasks.store import TaskStore
from octop.infra.bot_tasks.tools import TASK_TOOL_NAMES
from octop.infra.utils.locale import resolve_user_locale

# Talking to the user and keeping the plan never count against the budget.
FREE_TOOLS = TASK_TOOL_NAMES | {
    "ask_user_question",
    "write_todos",
    "request_takeover",
    "request_approval",
}
# Tools that do real work; reading and looking around never need a plan.
WORK_TOOLS = frozenset({"write_file", "edit_file", "execute", "cloud_computer"})
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
4. Hand files to the user with `send_file_to_user` (writing a file alone does not deliver \
it). It is checked first: it must open, have real content and a name that says what it is \
(not output.xlsx); fix and resend if it is refused.
5. Call `task_finish` last, then reply in a sentence or two; the user sees the checklist as a \
card. If a criterion failed or was skipped, say plainly what is missing; never call it done. \
A deep task is checked by an independent reviewer first; task_finish tells you how.
Before anything with consequences outside your work (sending, publishing, submitting, deleting \
the user's data elsewhere, changing permissions, accepting terms), call `request_approval` and \
act only if allowed. Payments are always the user's: `request_takeover`."""

BUDGET_NEAR = (
    "Note: this task has used {used} of its {what} budget ({limit}). Wrap up: finish what "
    "matters most, verify it, and call task_finish."
)
BUDGET_SPENT = (
    "Refused: this task has used its whole {what} budget ({limit}). Call task_finish with what "
    "is done and what is not, or use task_extend_budget to ask for new total limits."
)
PLAN_FIRST = (
    "Not run yet: this is real work (writing files, running commands or using the screen), so "
    "call task_plan first with the goal and the checks that prove it is done, then do this "
    "again. If it truly is a one-off that needs no checking, just call it again."
)

RESTORED = """## Current task (restored: earlier messages were summarized)
Goal: {goal} ({tier})
Acceptance criteria:
{criteria}{assumptions}
Keep going from here; record verdicts with task_check and close with task_finish."""

REVIEW_PREFIXES = ("review", "复核")

DELIVERY_TOOL = "send_file_to_user"
# Bigger files are sent without the content checks (only the name is checked).
MAX_INSPECT_BYTES = 50 * 1024 * 1024
NOT_SENT = (
    "Not sent to the user: {problems}. Fix the file (or its name) and call send_file_to_user again."
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


def _result_text(result: ToolMessage | Command[Any]) -> str:
    messages: list[Any] = [result]
    if isinstance(result, Command) and isinstance(result.update, dict):
        messages = list(result.update.get("messages") or [])
    for message in messages:
        if isinstance(message, ToolMessage):
            return str(message.text)
    return ""


def restored_task(task: Task) -> str:
    lines = []
    for number, item in enumerate(task.criteria, 1):
        proof = f" - {item.evidence}" if item.evidence else ""
        lines.append(f"{number}. [{item.status}] {item.text}{proof}")
    assumptions = "\nAssumptions: " + "; ".join(task.assumptions) if task.assumptions else ""
    return RESTORED.format(
        goal=task.goal, tier=task.tier, criteria="\n".join(lines), assumptions=assumptions
    )


def _user_turn(messages: list[BaseMessage]) -> str:
    """Identifies the user's latest message (not a harness notification like a screenshot)."""
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, HumanMessage) and not message.additional_kwargs.get("lc_source"):
            return message.id or f"{index}:{str(message.content)[:80]}"
    return ""


def _sibling_calls(request: ToolCallRequest) -> set[str]:
    """Names of the tools the model called in the same message as this one (they may run at
    the same time, e.g. task_plan alongside the first write_file)."""
    state = getattr(request, "state", None)
    messages = (
        state.get("messages") if isinstance(state, dict) else getattr(state, "messages", None)
    )
    if not messages:
        return set()
    calls = getattr(messages[-1], "tool_calls", None) or []
    return {str(call.get("name") or "") for call in calls if isinstance(call, dict)}


def _mentions(messages: list[BaseMessage], task_id: str) -> bool:
    return any(task_id in str(message.content) for message in messages)


def _sent_file(result: ToolMessage | Command[Any]) -> dict[str, Any] | None:
    """The media block send_file_to_user returned: path, filename and a file:// URI."""
    if not isinstance(result, ToolMessage) or result.status == "error":
        return None
    content: Any = result.content
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except ValueError:
            return None
    blocks = content if isinstance(content, list) else [content]
    for block in blocks:
        if isinstance(block, dict) and isinstance(block.get("source"), dict):
            return block
    return None


def _local_file(block: dict[str, Any]) -> Path | None:
    url = str(block["source"].get("url") or "")
    if not url.startswith("file:"):
        return None
    path = Path(url2pathname(urlparse(url).path))
    return path if path.is_file() else None


def _error_text(result: ToolMessage | Command[Any]) -> str | None:
    if isinstance(result, ToolMessage) and result.status == "error":
        return str(result.content)[:200]
    return None


class TaskWatch:
    """Warn about the durable task budget and repeated errors on this run."""

    def __init__(self) -> None:
        self.warned: set[str] = set()

    def spent(self, task: Task, now: float) -> tuple[str, str] | None:
        """(what, limit) when a budget is used up, else None."""
        if task.steps_used >= task.budget.steps:
            return "step", f"{task.budget.steps} steps"
        if now - task.started_at >= task.budget.minutes * 60:
            return "time", f"{task.budget.minutes} minutes"
        return None

    def near(self, task: Task, now: float) -> str | None:
        if task.id in self.warned:
            return None
        steps = task.steps_used
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


def _call_key(request: ToolCallRequest) -> str:
    call = request.tool_call
    payload = json.dumps([call.get("name"), call.get("args")], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


class BotTaskMiddleware(AgentMiddleware[Any, Any]):
    """Task briefing in the system prompt plus the watchdog around tool calls.

    ``always``: on every turn (a cloud tenant's Bot); otherwise only on Octop Bot client turns,
    where the task tools are shown.
    """

    def __init__(
        self,
        store: TaskStore,
        *,
        always: bool = False,
        user_repo: object | None = None,
        owner: int = 0,
    ) -> None:
        self._users = user_repo
        self._owner = owner
        self._store = store
        self._always = always
        self._watch = TaskWatch()
        # Per conversation: the user's latest message, and whether this turn was already asked
        # to plan (asked once; a model that insists goes ahead).
        self._turns: dict[str, str] = {}
        self._asked: set[str] = set()

    def _active(self) -> bool:
        return self._always or _configurable().get("octop_bot_browser") is True

    def _brief(self, request: ModelRequest[Any]) -> tuple[ModelRequest[Any], Task | None]:
        if not self._active():
            return request, None
        text = BRIEFING
        thread = str(_configurable().get("thread_id") or "")
        turn = _user_turn(list(request.messages))
        if thread and self._turns.get(thread) != turn:
            self._turns[thread] = turn
            self._asked.discard(thread)
        task = self._store.running(thread) if thread else None
        # Only when compaction dropped every task result: the prompt stays the same (and
        # cached) on ordinary turns.
        if task is not None and not _mentions(list(request.messages), task.id):
            text = f"{text}\n\n{restored_task(task)}"
        blocks: list[Any] = (
            list(request.system_message.content_blocks) if request.system_message else []
        )
        blocks.append({"type": "text", "text": f"\n\n{text}" if blocks else text})
        return request.override(system_message=SystemMessage(content_blocks=blocks)), task

    def wrap_model_call(
        self, request: ModelRequest[Any], handler: Callable[[ModelRequest[Any]], ModelResponse[Any]]
    ) -> ModelResponse[Any]:
        briefed, _ = self._brief(request)
        return handler(briefed)

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        briefed, task = await asyncio.to_thread(self._brief, request)
        if task is None:
            return await handler(briefed)
        thread = str(_configurable().get("thread_id") or "")
        # Provider-executed tools can have side effects before their result reaches us.
        # Only retry inference for ordinary client-executed tool definitions.
        may_retry = all(not isinstance(tool, dict) for tool in briefed.tools)
        while True:
            try:
                return await watch_model_output(lambda: handler(briefed))
            except ModelSilence:
                stopped = await asyncio.to_thread(self._silence, thread, task.id, may_retry)
                if stopped:
                    return ModelResponse(result=[AIMessage(content=stopped)])

    def _silence(self, thread: str, task_id: str, may_retry: bool) -> str:
        locale = resolve_user_locale(user_repo=self._users, user_id=self._owner)
        message = tr("bot_tasks.model_silence", locale)
        with self._store.locked(thread):
            task = self._store.running(thread)
            if task is None or task.id != task_id:
                return message
            now = time.time()
            task.updated_at = now
            if may_retry and not task.silence_retry_used and not task.budget_exhausted(now):
                task.silence_retry_used = True
                self._store.save(thread, task)
                return ""
            task.status = "stopped"
            task.summary = message
            task.finished_at = now
            self._store.save(thread, task)
            return message

    # -- tool calls -------------------------------------------------------------

    def _before(self, request: ToolCallRequest) -> tuple[Task | None, ToolMessage | None]:
        name = str(request.tool_call.get("name") or "")
        if name in FREE_TOOLS or not self._active():
            return None, None
        thread = str(_configurable().get("thread_id") or "")
        if not thread:
            return None, None
        with self._store.locked(thread):
            task = self._store.running(thread)
            if task is None:
                if (
                    name in WORK_TOOLS
                    and thread
                    and thread not in self._asked
                    and "task_plan" not in _sibling_calls(request)
                ):
                    self._asked.add(thread)
                    return None, ToolMessage(
                        content=PLAN_FIRST,
                        name=name,
                        tool_call_id=str(request.tool_call.get("id") or ""),
                        status="error",
                    )
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
            failure = task.failed_calls.get(_call_key(request))
            if failure and failure[1] >= SAME_ERROR_LIMIT:
                return task, ToolMessage(
                    content=SAME_ERROR.format(tool=name, count=failure[1]),
                    name=name,
                    tool_call_id=str(request.tool_call.get("id") or ""),
                    status="error",
                )
            task.steps_used += 1
            task.updated_at = time.time()
            self._store.save(thread, task)
        return task, None

    def _after(
        self, request: ToolCallRequest, task: Task, result: ToolMessage | Command[Any]
    ) -> ToolMessage | Command[Any]:
        self._note_review(request, task, result)
        notes: list[str] = []
        error = _error_text(result)
        key = _call_key(request)
        if error is not None or key in task.failed_calls:
            thread = str(_configurable().get("thread_id") or "")
            with self._store.locked(thread):
                current = self._store.running(thread)
                if current is not None and current.id == task.id:
                    if error is None:
                        current.failed_calls.pop(key, None)
                    else:
                        digest = hashlib.sha256(error.encode()).hexdigest()
                        last, count = current.failed_calls.get(key, ("", 0))
                        count = count + 1 if last == digest else 1
                        current.failed_calls[key] = (digest, count)
                        if count >= SAME_ERROR_LIMIT:
                            notes.append(
                                SAME_ERROR.format(tool=request.tool_call.get("name"), count=count)
                            )
                    self._store.save(thread, current)
        near = self._watch.near(task, time.time())
        if near:
            notes.append(near)
        return _with_note(result, "\n".join(notes)) if notes else result

    def _note_review(
        self, request: ToolCallRequest, task: Task, result: ToolMessage | Command[Any]
    ) -> None:
        """A ``task`` sub-agent asked to review a deep task: remember that it ran, and its
        findings, for task_finish and the delivery report."""
        if task.tier != "deep" or request.tool_call.get("name") != "task":
            return
        args = request.tool_call.get("args")
        description = str(args.get("description") or "") if isinstance(args, dict) else ""
        if not description.strip().lower().startswith(REVIEW_PREFIXES):
            return
        if _error_text(result) is not None:
            return
        thread = str(_configurable().get("thread_id") or "")
        with self._store.locked(thread):
            fresh = self._store.running(thread)
            if fresh is None or fresh.id != task.id:
                return
            fresh.reviews += 1
            fresh.reviewed_at = fresh.updated_at = time.time()
            fresh.review = _result_text(result).strip()[:1000]
            self._store.save(thread, fresh)

    def _deliver(
        self, request: ToolCallRequest, result: ToolMessage | Command[Any]
    ) -> ToolMessage | Command[Any]:
        """Check a file the Bot sends before the user gets it; keep it on the running task."""
        if request.tool_call.get("name") != DELIVERY_TOOL or not self._active():
            return result
        block = _sent_file(result)
        local = _local_file(block) if block is not None else None
        if block is None or local is None:
            return result
        name = str(block.get("filename") or block.get("path") or "file")
        size = local.stat().st_size
        # Past the cap only the name is checked: a stand-in byte keeps it from reading as empty.
        inspection = inspect_file(name, local.read_bytes() if size <= MAX_INSPECT_BYTES else b"x")
        if size > MAX_INSPECT_BYTES:
            inspection.facts = []
        if not inspection.ok:
            return ToolMessage(
                content=NOT_SENT.format(problems="; ".join(inspection.problems)),
                name=DELIVERY_TOOL,
                tool_call_id=str(request.tool_call.get("id") or ""),
                status="error",
            )
        thread = str(_configurable().get("thread_id") or "")
        if thread:
            with self._store.locked(thread):
                task = self._store.running(thread)
                if task is not None:
                    same = [d for d in task.deliverables if d.name == name]
                    task.deliverables = [
                        *task.deliverables[-29:],
                        Deliverable(
                            name=name[:300],
                            path=str(block.get("path") or name)[:1000],
                            size=size,
                            version=len(same) + 1,
                            facts=inspection.facts,
                        ),
                    ]
                    task.updated_at = time.time()
                    self._store.save(thread, task)
        return result

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        task, refused = self._before(request)
        if refused is not None:
            return refused
        result = self._deliver(request, handler(request))
        return self._after(request, task, result) if task is not None else result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        task, refused = await asyncio.to_thread(self._before, request)
        if refused is not None:
            return refused
        result = await handler(request)
        # Reading and checking the file is blocking work: off the event loop.
        result = await asyncio.to_thread(self._deliver, request, result)
        return (
            await asyncio.to_thread(self._after, request, task, result)
            if task is not None
            else result
        )
