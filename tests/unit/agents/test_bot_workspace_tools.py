"""Which Bot workspace tools the model sees on a turn."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
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
