"""The task watchdog: budgets, repeated failures and the briefing, without a model."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.types import Command

from octop.infra.bot_tasks import watchdog
from octop.infra.bot_tasks.model import Budget, Task
from octop.infra.bot_tasks.store import TaskStore


class _Settings:
    def __init__(self) -> None:
        self.rows: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.rows.get(key)

    def set(self, key: str, value: str) -> None:
        self.rows[key] = value


def _setup(
    monkeypatch: pytest.MonkeyPatch, *, steps: int = 10, bot_turn: bool = True
) -> tuple[watchdog.BotTaskMiddleware, TaskStore, Task]:
    configurable = {"thread_id": "thr1", **({"octop_bot_browser": True} if bot_turn else {})}
    monkeypatch.setattr(watchdog, "get_config", lambda: {"configurable": configurable})
    store = TaskStore(_Settings())  # type: ignore[arg-type]
    task = store.save("thr1", Task(goal="g", budget=Budget(steps=steps, minutes=30)))
    return watchdog.BotTaskMiddleware(store), store, task


def _call(name: str = "execute", call_id: str = "c1") -> Any:
    return SimpleNamespace(tool_call={"name": name, "id": call_id, "args": {}})


def _ok(request: Any) -> ToolMessage:
    return ToolMessage(content="fine", tool_call_id="c1", name=request.tool_call["name"])


def _fail(request: Any) -> ToolMessage:
    return ToolMessage(content="No such file", tool_call_id="c1", status="error")


def test_the_step_budget_warns_at_80_percent_then_refuses_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    middleware, _store, _task = _setup(monkeypatch, steps=5)
    contents = [str(middleware.wrap_tool_call(_call(), _ok).content) for _ in range(5)]
    assert all("budget" not in c for c in contents[:3])
    assert "has used 4 steps of its step budget (5 steps)" in contents[3]
    assert contents[3].startswith("fine")
    assert "budget" not in contents[4]  # warned once
    refused = middleware.wrap_tool_call(_call(), _ok)
    assert refused.status == "error" and "whole step budget (5 steps)" in str(refused.content)
    # Talking to the user and closing the task still work.
    for free in ("ask_user_question", "task_finish", "write_todos"):
        assert middleware.wrap_tool_call(_call(free), _ok).content == "fine"


def test_the_same_failure_three_times_gets_a_note(monkeypatch: pytest.MonkeyPatch) -> None:
    middleware, _store, _task = _setup(monkeypatch, steps=50)
    results = [str(middleware.wrap_tool_call(_call(), _fail).content) for _ in range(3)]
    assert "failed the same way" not in results[1]
    assert "`execute` has now failed the same way 3 times" in results[2]


def test_the_note_reaches_a_tool_that_returns_a_command(monkeypatch: pytest.MonkeyPatch) -> None:
    middleware, _store, _task = _setup(monkeypatch, steps=1)

    def screen(request: Any) -> Command[Any]:
        return Command(
            update={"messages": [ToolMessage(content="Did click.", tool_call_id="c1"), "pic"]}
        )

    # One step of one: the warning lands on the cloud_computer result inside the Command.
    result = middleware.wrap_tool_call(_call("cloud_computer"), screen)
    tool_message, picture = result.update["messages"]
    assert "Did click." in tool_message.content and "Wrap up" in tool_message.content
    assert picture == "pic"


def test_without_a_running_task_or_off_bot_turns_nothing_is_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    middleware, store, task = _setup(monkeypatch, steps=1, bot_turn=False)
    for _ in range(3):
        assert middleware.wrap_tool_call(_call(), _ok).content == "fine"
    task.status = "done"
    store.save("thr1", task)
    always = watchdog.BotTaskMiddleware(store, always=True)
    for _ in range(3):
        assert always.wrap_tool_call(_call(), _ok).content == "fine"


def test_the_briefing_is_added_on_bot_turns_only(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Request:
        def __init__(self, system_message: SystemMessage | None) -> None:
            self.system_message = system_message

        def override(self, *, system_message: SystemMessage) -> _Request:
            return _Request(system_message)

    def prompt(middleware: watchdog.BotTaskMiddleware) -> str:
        seen = middleware.wrap_model_call(_Request(SystemMessage(content="Hi.")), lambda r: r)  # type: ignore[arg-type,return-value]
        return "".join(b["text"] for b in seen.system_message.content_blocks)  # type: ignore[attr-defined]

    on, _store, _task = _setup(monkeypatch)
    assert prompt(on).startswith("Hi.\n\n## Tasks") and "task_finish" in prompt(on)
    off, _store, _task = _setup(monkeypatch, bot_turn=False)
    assert prompt(off) == "Hi."
