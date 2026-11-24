"""Tools the user's phone runs for a Bot: Health, Calendar and Reminders.

The server never runs these. ``DeviceTools`` is its own human-in-the-loop gate
with only ``respond`` and ``reject`` allowed, so a call pauses the turn the same
way ``ask_user_question`` does. The phone runs the system API and resumes with
``{"type": "respond", "message": <result JSON>}``; the middleware turns that
message into the tool result. The gate is separate from the agent's
``interrupt_on`` because harness drops that until a Bot finishes onboarding, and
because thread-level "approve all" must never skip the phone. The function body
only runs if nothing interrupts the call, and tells the model the phone is not there.

A tool is offered to the model only on threads whose latest user turn came
from a phone that declared it (``device_tools`` on the turn). The tool specs
live in ``device_tools.json``, which ``mobile/scripts/sync-assets.sh`` copies
into both apps so all three sides share one definition.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterable
from functools import cache
from importlib.resources import files
from typing import Any

from langchain.agents.middleware import HumanInTheLoopMiddleware, ModelRequest, ModelResponse
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.config import get_config

UNAVAILABLE = (
    "The user's phone did not run this tool: it only works while the user chats from the "
    "Octop Bot app with this connector turned on. Do not call it again in this turn; tell the "
    "user what you would have done and continue."
)

# Thread id -> device tools the phone declared on that thread's latest user turn.
_THREADS: dict[str, frozenset[str]] = {}


@cache
def device_specs() -> tuple[dict[str, Any], ...]:
    raw = files("octop.infra.agents").joinpath("device_tools.json").read_text(encoding="utf-8")
    return tuple(json.loads(raw)["tools"])


def device_tool_names() -> frozenset[str]:
    return frozenset(spec["name"] for spec in device_specs())


def device_tools() -> list[BaseTool]:
    def unavailable(**_: Any) -> str:
        return UNAVAILABLE

    return [
        StructuredTool.from_function(
            func=unavailable,
            name=spec["name"],
            description=spec["description"],
            args_schema=spec["parameters"],
        )
        for spec in device_specs()
    ]


def device_interrupts() -> dict[str, Any]:
    """The phone answers in place of the tool, or the user declines."""
    return {
        name: {
            "allowed_decisions": ["respond", "reject"],
            "description": "Runs on the user's phone.",
        }
        for name in device_tool_names()
    }


def remember_device_tools(thread_id: str, names: Iterable[str] | None) -> None:
    """Record what the phone offered on this turn; any other client clears it."""
    offered = frozenset(names or ()) & device_tool_names()
    if offered:
        _THREADS[thread_id] = offered
    else:
        _THREADS.pop(thread_id, None)


def thread_device_tools(thread_id: str | None) -> frozenset[str]:
    return _THREADS.get(thread_id or "", frozenset())


class DeviceTools(HumanInTheLoopMiddleware):
    """Mount the device tools, show the model only those the phone offered, and pause on each call."""

    def __init__(self) -> None:
        super().__init__(interrupt_on=device_interrupts())
        self.tools = device_tools()
        self._names = device_tool_names()

    def _scope(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
        thread_id = (get_config().get("configurable") or {}).get("thread_id")
        offered = thread_device_tools(str(thread_id) if thread_id else None)
        visible = [
            t
            for t in request.tools
            if not isinstance(t, BaseTool) or t.name not in self._names or t.name in offered
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
