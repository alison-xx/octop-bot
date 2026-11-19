"""Expose the workspace's rich chat and management tools only on Octop Bot turns."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.tools import BaseTool
from langgraph.config import get_config


class BotWorkspaceTools(AgentMiddleware[Any, Any]):
    def __init__(self, tools: Sequence[BaseTool]) -> None:
        self.tools = tuple(tools)
        self._names = {tool.name for tool in tools}

    def _scope(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
        if (get_config().get("configurable") or {}).get("octop_bot_browser") is True:
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
