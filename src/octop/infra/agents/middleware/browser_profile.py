"""Force browser tool calls onto the current user's isolated profile."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.config import get_config
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from octop.infra.control.browser.bundled import browser_enabled
from octop.infra.control.browser.handoff import control_owner_for
from octop.infra.utils.browser_media import parse_octop_user_id, user_browser_profile

logger = logging.getLogger(__name__)

_BROWSER_TOOL = "browser_use"
_MISSING_USER = (
    "browser_use blocked: the current turn has no Octop user id, "
    "so a browser profile cannot be isolated."
)
_NOT_ENABLED = (
    "browser_use blocked: Chromium is installed but not enabled. "
    "Ask the user to enable it on the Remote Browser page."
)


def _bind_browser_profile(
    request: ToolCallRequest, agent_id: str | None
) -> ToolCallRequest | ToolMessage:
    tool_call = request.tool_call
    if str(tool_call.get("name") or "") != _BROWSER_TOOL:
        return request

    if not browser_enabled():
        return ToolMessage(
            content=_NOT_ENABLED,
            tool_call_id=str(tool_call.get("id") or ""),
            status="error",
        )

    configurable = dict(get_config().get("configurable") or {})
    user_id = parse_octop_user_id(configurable.get("user"))
    if user_id is None:
        logger.warning("browser_use blocked: configurable.user is missing or invalid")
        return ToolMessage(
            content=_MISSING_USER,
            tool_call_id=str(tool_call.get("id") or ""),
            status="error",
        )

    raw_args = tool_call.get("args")
    args = dict(raw_args) if isinstance(raw_args, dict) else {}
    bot_id = agent_id if configurable.get("octop_bot_browser") is True else None
    profile = user_browser_profile(user_id, bot_id)
    if bot_id and control_owner_for(profile) == "user":
        return ToolMessage(
            content="browser_use paused while the user has control of this Bot browser.",
            tool_call_id=str(tool_call.get("id") or ""),
            status="error",
        )
    args["profile"] = profile
    return request.override(tool_call={**tool_call, "args": args})


class BrowserProfileMiddleware(AgentMiddleware[Any, Any]):
    """Prevent model-selected profiles from crossing Octop user boundaries."""

    def __init__(self, agent_id: str | None = None) -> None:
        self.agent_id = agent_id

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        bound = _bind_browser_profile(request, self.agent_id)
        if isinstance(bound, ToolMessage):
            return bound
        return handler(bound)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        bound = _bind_browser_profile(request, self.agent_id)
        if isinstance(bound, ToolMessage):
            return bound
        return await handler(bound)


__all__ = ["BrowserProfileMiddleware"]
