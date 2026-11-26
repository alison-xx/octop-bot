"""Expose the workspace's rich chat and management tools only on Octop Bot turns."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool
from langgraph.config import get_config

TEAM_SETUP = """When the user asks only to assemble a Bot team, the team itself is the deliverable.
Read octop_bot_roster once if you need the owner's existing members or groups. If the roster is
already known this turn, use it. Call octop_bot_create_team directly with existing_bot_ids and
the missing roles. When the user leaves the size open, choose a small complementary team with
at most three new roles and concise, distinct instructions. The tool creates the group and
sidebar section together. Use its returned IDs and section as the receipt, report any partial
failure, and retry only missing work. This one workspace operation needs no separate task_plan,
write_todos or verification round. If the user also asks for business work, plan that separately."""


class BotWorkspaceTools(AgentMiddleware[Any, Any]):
    """``tools`` show only on Octop Bot client turns; ``anywhere`` show on every turn.

    A cloud tenant's computer tools are ``anywhere``: the Bot works on its cloud computer
    whether the turn came from the web, the phone apps, an IM channel or a schedule.
    """

    def __init__(self, tools: Sequence[BaseTool], anywhere: Sequence[BaseTool] = ()) -> None:
        self.tools = (*tools, *anywhere)
        self._names = {tool.name for tool in tools}

    def _scope(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
        if (get_config().get("configurable") or {}).get("octop_bot_browser") is True:
            if "octop_bot_create_team" in self._names:
                blocks = (
                    list(request.system_message.content_blocks) if request.system_message else []
                )
                return request.override(
                    system_message=SystemMessage(
                        content_blocks=[*blocks, {"type": "text", "text": "\n\n" + TEAM_SETUP}]
                    )
                )
            return request
        visible = [
            t for t in request.tools if not isinstance(t, BaseTool) or t.name not in self._names
        ]
        return request.override(tools=visible) if len(visible) != len(request.tools) else request

    def wrap_model_call(
        self, request: ModelRequest[Any], handler: Callable[[ModelRequest[Any]], ModelResponse[Any]]
    ) -> ModelResponse[Any]:
        return handler(self._scope(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        return await handler(self._scope(request))
