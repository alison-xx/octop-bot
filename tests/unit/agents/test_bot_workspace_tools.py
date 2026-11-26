"""Which Bot workspace tools the model sees on a turn."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from langchain.agents.middleware import ModelRequest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import SystemMessage
from langchain_core.tools import StructuredTool

from octop.infra.agents.middleware import bot_workspace
from octop.infra.agents.middleware.bot_workspace import BotWorkspaceTools


def _tool(name: str) -> StructuredTool:
    return StructuredTool.from_function(func=lambda: "ok", name=name, description=name)


class _Request:
    def __init__(self, tools: list[Any]) -> None:
        self.tools = tools

    def override(self, *, tools: list[Any]) -> _Request:
        return _Request(tools)


@pytest.mark.parametrize("bot_turn", [True, False])
def test_computer_tools_show_on_every_turn_and_bot_chat_tools_only_in_bot_chat(
    monkeypatch: pytest.MonkeyPatch, bot_turn: bool
) -> None:
    """Phone, IM and scheduled turns have no Bot web flag; the cloud computer is still there."""
    configurable = {"octop_bot_browser": True} if bot_turn else {}
    monkeypatch.setattr(bot_workspace, "get_config", lambda: {"configurable": configurable})
    chat, computer = _tool("show_view"), _tool("cloud_computer")
    middleware = BotWorkspaceTools([chat], [computer])
    assert {t.name for t in middleware.tools} == {"show_view", "cloud_computer"}
    seen = middleware.wrap_model_call(
        _Request([chat, computer, _tool("read_file")]),  # type: ignore[arg-type]
        lambda request: SimpleNamespace(names={t.name for t in request.tools}),  # type: ignore[arg-type,return-value]
    )
    expected = {"cloud_computer", "read_file"} | ({"show_view"} if bot_turn else set())
    assert seen.names == expected  # type: ignore[attr-defined]


@pytest.mark.parametrize(("chief", "bot_turn"), [(True, True), (True, False), (False, True)])
def test_one_call_team_setup_guidance_follows_the_chief_tool_scope(
    monkeypatch: pytest.MonkeyPatch, chief: bool, bot_turn: bool
) -> None:
    monkeypatch.setattr(
        bot_workspace, "get_config", lambda: {"configurable": {"octop_bot_browser": bot_turn}}
    )
    tools = [_tool("octop_bot_create_team")] if chief else []
    request = ModelRequest(
        model=FakeListChatModel(responses=["ok"]),
        tools=tools,
        messages=[],
        system_message=SystemMessage(content="Existing instructions."),
    )
    scoped = BotWorkspaceTools(tools)._scope(request)
    assert scoped.system_message is not None
    assert "Existing instructions." in scoped.system_message.text
    assert ("existing_bot_ids" in scoped.system_message.text) == (chief and bot_turn)
