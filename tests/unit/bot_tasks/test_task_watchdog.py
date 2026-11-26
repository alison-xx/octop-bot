"""The task watchdog: budgets, repeated failures and the briefing, without a model."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.types import Command

from octop.infra.bot_tasks import watchdog
from octop.infra.bot_tasks.model import Budget, Criterion, Task
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


def test_duplicate_edit_recovers_by_narrowing_the_target(monkeypatch, tmp_path):
    from deepagents.backends.filesystem import FilesystemBackend

    middleware, _store, _task = _setup(monkeypatch)
    file = tmp_path / "index.html"
    file.write_text("first: <b>38%</b>\nsecond: <b>38%</b>")
    backend = FilesystemBackend(root_dir=tmp_path, virtual_mode=True)
    request = _call("edit_file")
    request.tool_call["args"] = {
        "file_path": "/index.html",
        "old_string": "<b>38%</b>",
        "new_string": "<b>39%</b>",
    }

    def edit(call):
        result = backend.edit(**call.tool_call["args"])
        return ToolMessage(
            content=result.error or "Edited",
            status="error" if result.error else "success",
            tool_call_id="c1",
        )

    result = middleware.wrap_tool_call(request, edit)
    assert result.status == "error" and "read the target file" in result.content
    assert file.read_text().count("<b>38%</b>") == 2
    request.tool_call["args"].update(
        old_string="second: <b>38%</b>", new_string="second: <b>39%</b>"
    )
    assert middleware.wrap_tool_call(request, edit).status == "success"
    assert file.read_text() == "first: <b>38%</b>\nsecond: <b>39%</b>"


def test_the_same_failure_three_times_gets_a_note(monkeypatch: pytest.MonkeyPatch) -> None:
    middleware, store, _task = _setup(monkeypatch, steps=50)
    results = [str(middleware.wrap_tool_call(_call(), _fail).content) for _ in range(3)]
    assert "failed the same way" not in results[1]
    assert "`execute` has now failed the same way 3 times" in results[2]
    restarted = watchdog.BotTaskMiddleware(store)

    def unexpected(_: Any) -> Any:
        pytest.fail("the same failed call must not be executed again")

    assert restarted.wrap_tool_call(_call(), unexpected).status == "error"
    other = _call()
    other.tool_call["args"] = {"path": "corrected.txt"}
    assert restarted.wrap_tool_call(other, _ok).status == "success"


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
        assert always.wrap_tool_call(_call("read_file"), _ok).content == "fine"


def test_real_work_without_a_plan_is_sent_back_once_per_user_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langchain_core.messages import HumanMessage, add_notification_metadata

    middleware, store, task = _setup(monkeypatch)
    task.status = "done"
    store.save("thr1", task)

    class _Request:
        def __init__(self, messages: list[Any]) -> None:
            self.messages = messages
            self.system_message = None

        def override(self, *, system_message: SystemMessage) -> _Request:
            return self

    def turn(*messages: Any) -> None:
        middleware.wrap_model_call(_Request(list(messages)), lambda r: r)  # type: ignore[arg-type]

    first = HumanMessage(content="写个脚本", id="u1")
    turn(first)
    # Reading is free; the first write is sent back, the model may insist.
    assert middleware.wrap_tool_call(_call("read_file"), _ok).content == "fine"
    asked = middleware.wrap_tool_call(_call("write_file"), _ok)
    assert asked.status == "error" and "call task_plan first" in str(asked.content)
    assert middleware.wrap_tool_call(_call("write_file"), _ok).content == "fine"
    # A screenshot notification is not a new user turn; a new user message is.
    screenshot = add_notification_metadata(HumanMessage(content="screen"), source="cloud_computer")
    turn(first, screenshot)
    assert middleware.wrap_tool_call(_call("execute"), _ok).content == "fine"
    turn(first, screenshot, HumanMessage(content="再改一下", id="u2"))
    assert "call task_plan first" in str(middleware.wrap_tool_call(_call("execute"), _ok).content)


def test_the_briefing_is_added_on_bot_turns_only(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Request:
        def __init__(self, system_message: SystemMessage | None) -> None:
            self.system_message = system_message
            self.messages: list[Any] = []

        def override(self, *, system_message: SystemMessage) -> _Request:
            return _Request(system_message)

    def prompt(middleware: watchdog.BotTaskMiddleware) -> str:
        seen = middleware.wrap_model_call(_Request(SystemMessage(content="Hi.")), lambda r: r)  # type: ignore[arg-type,return-value]
        return "".join(b["text"] for b in seen.system_message.content_blocks)  # type: ignore[attr-defined]

    on, _store, _task = _setup(monkeypatch)
    assert prompt(on).startswith("Hi.\n\n## Tasks") and "task_finish" in prompt(on)
    off, _store, _task = _setup(monkeypatch, bot_turn=False)
    assert prompt(off) == "Hi."


def test_a_review_sub_agent_is_recorded_on_a_deep_task(monkeypatch: pytest.MonkeyPatch) -> None:
    middleware, store, task = _setup(monkeypatch, steps=50)
    task.tier = "deep"
    store.save("thr1", task)

    def reviewer(request: Any) -> Command[Any]:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="1. met: 表格 42 行。2. not met: 缺折扣\n**Verdict: 有问题**",
                        tool_call_id="c1",
                    )
                ]
            }
        )

    def sub_agent(description: str) -> Any:
        return watchdog.ToolCallRequest(
            tool=None,
            state={},
            runtime=None,
            tool_call={
                "name": "task",
                "id": "c1",
                "args": {"description": description, "subagent_type": "general-purpose"},
            },
        )

    middleware.wrap_tool_call(sub_agent("Collect prices from three sites"), reviewer)
    assert store.running("thr1").reviews == 0  # delegating work is not a review
    middleware.wrap_tool_call(sub_agent("Review: check each criterion"), reviewer)
    reviewed = store.running("thr1")
    assert reviewed.reviews == 1 and reviewed.reviewed_at is not None
    assert reviewed.review.startswith("1. met") and reviewed.review_status == "issues"

    def incomplete(request: Any) -> ToolMessage:
        assert "PASS or ISSUES" in request.tool_call["args"]["description"]
        return ToolMessage(content='{"name":"ls","arguments":{}}', tool_call_id="c1")

    middleware.wrap_tool_call(sub_agent("Review: follow up"), incomplete)
    fresh = store.running("thr1")
    assert fresh.reviews == 2 and fresh.review_status == "unverified"
    fresh.criteria = [Criterion(text="验收项", status="passed", evidence="已测")]
    assert fresh.verdict() == "partial"
    refused = middleware.wrap_tool_call(
        sub_agent("Review: repeat"), lambda _: pytest.fail("third invocation")
    )
    assert refused.status == "error"


@pytest.mark.parametrize("changed", [False, True])
def test_the_review_applies_only_to_the_verified_revision(
    monkeypatch: pytest.MonkeyPatch, changed: bool
) -> None:
    middleware, store, task = _setup(monkeypatch, steps=50)
    task.tier = "deep"
    task.criteria = [Criterion(text="Rows verified", status="passed", evidence="Two rows")]
    store.save("thr1", task)
    request = watchdog.ToolCallRequest(
        tool=None,
        state={},
        runtime=None,
        tool_call={
            "name": "task",
            "args": {"description": "Review: check table"},
            "id": "c1",
            "type": "tool_call",
        },
    )

    def reviewer(_: Any) -> ToolMessage:
        if changed:
            revised = store.running("thr1")
            revised.criteria[0].evidence = "Three rows in the new revision"
            store.save("thr1", revised)
        return ToolMessage(content="Two rows matched.\n- ** verdict**: 通过", tool_call_id="c1")

    middleware.wrap_tool_call(request, reviewer)
    result = store.running("thr1")
    assert result.review_status == ("unverified" if changed else "passed")
    assert result.verdict() == ("partial" if changed else "done")


def test_a_task_dropped_by_compaction_is_put_back_in_the_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langchain_core.messages import HumanMessage

    middleware, store, task = _setup(monkeypatch)
    task.criteria = [Criterion(text="三家都有", status="passed", evidence="42 行")]
    store.save("thr1", task)

    class _Request:
        def __init__(self, messages: list[Any], system_message: Any = None) -> None:
            self.messages = messages
            self.system_message = system_message

        def override(self, *, system_message: SystemMessage) -> _Request:
            return _Request(self.messages, system_message)

    def prompt(messages: list[Any]) -> str:
        seen = middleware.wrap_model_call(_Request(messages), lambda r: r)  # type: ignore[arg-type,return-value]
        return "".join(b["text"] for b in seen.system_message.content_blocks)  # type: ignore[attr-defined]

    summarized = [HumanMessage(content="Summary of the conversation so far ...")]
    restored = prompt(summarized)
    assert "## Current task (restored" in restored
    assert "1. [passed] 三家都有 - 42 行" in restored
    # While a task result is still in the conversation, the prompt is unchanged.
    still_there = [ToolMessage(content=f'{{"task": {{"id": "{task.id}"}}}}', tool_call_id="x")]
    assert "Current task" not in prompt(still_there)


def test_no_plan_request_when_task_plan_is_in_the_same_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """task_plan and the first write_file sent together run side by side: let the write run."""
    from langchain_core.messages import AIMessage

    middleware, store, task = _setup(monkeypatch)
    task.status = "done"
    store.save("thr1", task)
    batch = AIMessage(
        content="",
        tool_calls=[
            {"name": "task_plan", "args": {}, "id": "p1"},
            {"name": "write_file", "args": {}, "id": "w1"},
        ],
    )
    request = SimpleNamespace(
        tool_call={"name": "write_file", "id": "w1", "args": {}},
        state={"messages": [batch]},
    )
    assert middleware.wrap_tool_call(request, _ok).content == "fine"


def _sent(tmp: Any, name: str, body: bytes) -> Any:
    path = tmp / name
    path.write_bytes(body)

    def handler(request: Any) -> ToolMessage:
        return ToolMessage(
            content=[
                {
                    "type": "file",
                    "path": name,
                    "filename": name,
                    "source": {"type": "url", "url": path.as_uri(), "media_type": "text/csv"},
                }
            ],
            tool_call_id="c1",
            name="send_file_to_user",
        )

    return handler


def test_a_file_that_fails_the_checks_never_reaches_the_user(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    middleware, store, _task = _setup(monkeypatch)
    refused = middleware.wrap_tool_call(
        _call("send_file_to_user"), _sent(tmp_path, "output.csv", b"a\n")
    )
    assert refused.status == "error" and refused.content.startswith("Not sent to the user:")
    assert "does not say what it is" in refused.content and "no data rows" in refused.content
    assert store.running("thr1").deliverables == []


def test_failed_revision_is_reported_until_the_file_is_delivered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from io import BytesIO

    from pypdf import PdfWriter

    middleware, store, _task = _setup(monkeypatch)
    name = "quarterly-report.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    valid = BytesIO()
    writer.write(valid)
    for data, expected in [
        (valid.getvalue(), {}),
        (b"", {name: "validation"}),
        (b"%PDF", {name: "open"}),
        (valid.getvalue(), {}),
    ]:
        result = middleware.wrap_tool_call(_call("send_file_to_user"), _sent(tmp_path, name, data))
        saved = store.running("thr1")
        assert saved.delivery_failures == expected
        if expected:
            assert result.status == "error"
            assert [d.version for d in saved.deliverables] == [1]
    assert [d.version for d in saved.deliverables] == [1, 2]


def test_delivered_files_are_kept_on_the_task_with_versions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    middleware, store, _task = _setup(monkeypatch, steps=60)
    send = _sent(tmp_path, "价格对比.csv", "公司,价格\nA,1\n".encode())
    for _ in range(33):
        result = middleware.wrap_tool_call(_call("send_file_to_user"), send)
        assert result.status != "error"
    delivered = store.running("thr1").deliverables
    assert [(d.name, d.version) for d in delivered] == [("价格对比.csv", v) for v in range(4, 34)]
    assert delivered[0].facts == [{"k": "rows", "n": 1}] and delivered[0].size > 0


def test_reopening_the_task_does_not_grant_a_fresh_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    old, store, _task = _setup(monkeypatch, steps=1)
    assert old.wrap_tool_call(_call(), _ok).status == "success"
    reopened = watchdog.BotTaskMiddleware(store, always=True)
    assert reopened.wrap_tool_call(_call(), _ok).status == "error"
    assert store.running("thr1").steps_used == 1


@pytest.mark.asyncio
async def test_model_silence_retries_inference_once_then_preserves_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from langchain.agents.middleware import ModelRequest
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from octop.infra.bot_tasks import model_silence

    middleware, store, task = _setup(monkeypatch)
    task.criteria = [Criterion(text="one", status="passed", evidence="receipt")]
    store.save("thr1", task)
    model = FakeListChatModel(responses=["ok"])
    request = ModelRequest(model=model, messages=[], tools=[])
    attempts = []
    monkeypatch.setattr(model_silence, "SILENT_SECONDS", 0.04)

    async def silent(_: Any) -> Any:
        try:
            await asyncio.Event().wait()
        finally:
            attempts.append("cancelled")

    result = await middleware.awrap_model_call(request, silent)
    assert attempts == ["cancelled", "cancelled"]
    saved = store.tasks("thr1")[-1]
    assert saved.silence_retry_used and saved.status == "stopped"
    assert saved.criteria == task.criteria
    assert result.result[0].content == saved.summary


@pytest.mark.asyncio
async def test_streaming_tokens_extend_model_idle_window(monkeypatch: pytest.MonkeyPatch) -> None:
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from octop.infra.bot_tasks import model_silence

    monkeypatch.setattr(model_silence, "SILENT_SECONDS", 0.2)
    model = FakeListChatModel(responses=["abcdef"], sleep=0.05)

    async def tokens() -> str:
        return "".join([str(chunk.content) async for chunk in model.astream("sample")])

    assert await model_silence.watch_model_output(tokens) == "abcdef"


@pytest.mark.asyncio
async def test_provider_timeouts_and_user_cancellation_are_not_silence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from octop.infra.bot_tasks import model_silence

    async def immediately_raises(exc: BaseException) -> None:
        raise exc

    with pytest.raises(TimeoutError, match="upstream"):
        await model_silence.watch_model_output(lambda: immediately_raises(TimeoutError("upstream")))
    with pytest.raises(asyncio.CancelledError):
        await model_silence.watch_model_output(lambda: immediately_raises(asyncio.CancelledError()))


def test_owner_can_read_persisted_card_status_after_model_silence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import Mock

    from octop.api.routers.chat import history

    middleware, store, task = _setup(monkeypatch)
    middleware._silence("thr1", task.id, False)
    server = Mock()
    server.services.settings_repo = store._settings
    server.app_runtime.gateway.thread_registry.get_thread.return_value = SimpleNamespace(
        agent_id="bot", user_id=2
    )
    monkeypatch.setattr(history, "require_agent_row", Mock())
    result = history.read_task_statuses("bot", "thr1", SimpleNamespace(id=2), server)
    assert [(item.id, item.status) for item in result] == [(task.id, "stopped")]
    assert set(result[0].model_dump()) == {"id", "status", "summary", "updated_at", "finished_at"}


def test_large_delivery_only_checks_its_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    middleware, store, _task = _setup(monkeypatch)
    monkeypatch.setattr(watchdog, "MAX_INSPECT_BYTES", 4)
    result = middleware.wrap_tool_call(
        _call("send_file_to_user"), _sent(tmp_path, "价格对比.csv", b"name,value\nA,42\n")
    )
    assert result.status == "success"
    assert store.running("thr1").deliverables[0].facts == [{"k": "filenameOnly", "n": 1}]
    refused = middleware.wrap_tool_call(
        _call("send_file_to_user"), _sent(tmp_path, "output.csv", b"name,value\nA,42\n")
    )
    assert refused.status == "error"


@pytest.mark.parametrize("available", [False, True])
def test_office_delivery_requires_a_preview_for_the_exact_revision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, available: bool
) -> None:
    import hashlib
    import io
    import zipfile

    from octop.infra.cloud.computers.office import OfficePreviewError

    _, store, _ = _setup(monkeypatch)
    sample = io.BytesIO()
    with zipfile.ZipFile(sample, "w") as archive:
        archive.writestr("word/document.xml", "<document>样例甲有五件</document>".encode())
    doc = sample.getvalue()
    preview = "outbound/office-previews/" + hashlib.sha256(doc).hexdigest() + ".jpg"

    def check(path: str, digest: str) -> tuple[int, str]:
        assert path == "验收清单.docx" and digest == hashlib.sha256(doc).hexdigest()
        if not available:
            raise OfficePreviewError("Could not open the sample.")
        return 2, preview

    middleware = watchdog.BotTaskMiddleware(store, office_preview=check)
    result = middleware.wrap_tool_call(
        _call("send_file_to_user"), _sent(tmp_path, "验收清单.docx", doc)
    )
    delivered = store.running("thr1").deliverables
    if available:
        assert result.status == "success"
        assert result.content[0]["office_preview_path"] == preview
        assert delivered[0].preview == preview
        assert {"k": "pages", "n": 2} in delivered[0].facts
        assert {"k": "opened", "n": 1} in delivered[0].facts
    else:
        assert result.status == "error" and "Could not open the sample" in result.content
        assert delivered == []
