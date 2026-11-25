"""Desktop operations for an owner's private cloud chat. The native app asks on each call."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.config import get_config
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command, interrupt
from octop_harness.builtin.tools.ask_user import ASK_USER_TOOL_NAME
from pydantic import Field

from octop.i18n import tr
from octop.infra.bot_tasks.placement import (
    Placement,
    placement_for_turn,
    tool_at_location,
)
from octop.infra.cloud.devices.hub import DeviceHub, DeviceId, LocalRequest
from octop.infra.cloud.devices.transfers import fetch_file, inbound_path
from octop.infra.db.repos.threads import ThreadRepo
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.utils.locale import resolve_user_locale


def _current_thread() -> str:
    try:
        return str((get_config().get("configurable") or {}).get("thread_id") or "")
    except RuntimeError:
        return ""


def local_device_tool(
    hub: DeviceHub,
    owner: int,
    bot_name: str,
    allowed: Callable[[str], bool],
    workspace: Callable[[], Any],
) -> StructuredTool:
    class DeviceRequest(LocalRequest):
        device_id: DeviceId = Field(
            description="Copy the exact 32-character device_id from the connected devices list."
        )

    async def locally(device_id: str, **args: Any) -> str:
        if not await asyncio.get_running_loop().run_in_executor(None, allowed, _current_thread()):
            return "Local devices are available only in the owner’s private chat."
        request = LocalRequest.model_validate(args)
        try:
            download = (
                await fetch_file(workspace(), request.cloud_path)
                if request.action == "fetch_from_cloud"
                else None
            )
            destination = inbound_path(request.path) if request.action == "send_to_cloud" else ""
            result = await hub.request(
                owner, device_id, bot_name, request, download=download, destination=destination
            )
            if result.transfer is not None and destination:
                await workspace().aupload_bytes(destination, result.transfer.decode())
                return f"Received {destination} ({result.transfer.size} bytes)."
            return result.message
        except ValueError as exc:
            return str(exc)

    return StructuredTool.from_function(
        coroutine=locally,
        name="local_computer",
        args_schema=DeviceRequest,
        description=(
            "Only for a task explicitly requiring the user's connected computer. Use the device_id "
            "from the device_id field in the execution environment. Paths are relative to the folder the user selects. "
            "List, read text, create text, request a command, send_to_cloud or fetch_from_cloud (1 MiB; cloud_path required for fetch). Each operation requires native "
            "confirmation. Read and command output return to this cloud conversation. "
            "Never ask for passwords, codes or payment details. Stop if declined or offline."
        ),
    )


def device_wait_tool(
    hub: DeviceHub, owner: int, allowed: Callable[[str], bool], user_repo: object
) -> StructuredTool:
    def wait_for_local_device() -> str:
        if not allowed(_current_thread()):
            return "This wait belongs to the owner's private chat."
        locale = resolve_user_locale(user_repo=user_repo, user_id=owner)
        header = tr("octop_bot.device_wait.header", locale)
        resume = tr("octop_bot.device_wait.resume", locale)
        answer = interrupt(
            {
                "action_requests": [
                    {
                        "name": ASK_USER_TOOL_NAME,
                        "description": header,
                        "args": {
                            "local_device_wait": True,
                            "questions": [
                                {
                                    "header": header,
                                    "question": tr("octop_bot.device_wait.question", locale),
                                    "options": [
                                        {"label": resume},
                                        {"label": tr("octop_bot.device_wait.cancel", locale)},
                                    ],
                                    "multiSelect": False,
                                }
                            ],
                        },
                    }
                ],
                "review_configs": [
                    {"action_name": ASK_USER_TOOL_NAME, "allowed_decisions": ["respond"]}
                ],
            }
        )
        decisions = answer.get("decisions") if isinstance(answer, dict) else None
        choice = decisions[0] if isinstance(decisions, list) and len(decisions) == 1 else None
        if (
            not isinstance(choice, dict)
            or choice.get("type") != "respond"
            or choice.get("message") not in (resume, f"{header}: {resume}")
        ):
            return "The owner stopped this wait. End the local step."
        if not hub.online(owner):
            return "The desktop is still offline. End this turn and tell the owner to reconnect before continuing."
        return "The owner resumed the local step. Check current state before proposing a new operation; native confirmation is still required."

    return StructuredTool.from_function(
        func=wait_for_local_device,
        name="wait_for_local_device",
        description="Pause a required local step until the owner connects the desktop and chooses Continue. This never queues or executes a command.",
    )


class LocalDesktopTools(AgentMiddleware[Any, Any]):
    def __init__(
        self,
        hub: DeviceHub,
        owner: int,
        bot_name: str,
        agent_id: str,
        threads: ThreadRepo,
        workspace: Callable[[], Any],
        user_repo: object,
    ) -> None:
        self._hub = hub
        self._owner = owner
        self._agent_id = agent_id
        self._threads = threads
        self.tools = [
            local_device_tool(hub, owner, bot_name, self._allowed, workspace),
            device_wait_tool(hub, owner, self._allowed, user_repo),
        ]

    def _allowed(self, thread_id: str) -> bool:
        row = self._threads.get(thread_id) if thread_id else None
        return bool(
            row
            and row.user_id == self._owner
            and row.agent_id == self._agent_id
            and row.channel_type == ThreadRegistry.CHANNEL_DASHBOARD
        )

    def _mode(self, state: Any, thread: str) -> Placement:
        chosen = placement_for_turn(state, self._owner)
        return chosen if chosen is not None and self._allowed(thread) else "cloud"

    def _scope(self, request: ModelRequest[Any], mode: Placement) -> ModelRequest[Any]:
        devices = self._hub.online(self._owner) if mode != "cloud" else {}
        visible = []
        for tool in request.tools:
            name = tool.name if isinstance(tool, BaseTool) else tool.get("name", "")
            if name == "wait_for_local_device" and (devices or mode != "local"):
                continue
            if tool_at_location(name, mode) and (name != "local_computer" or devices):
                visible.append(tool)
        request = request.override(tools=visible)
        if not devices and mode != "local":
            return request
        blocks = list(request.system_message.content_blocks) if request.system_message else []
        blocks.append(
            {
                "type": "text",
                "text": (
                    "When a local step requires an offline device, call wait_for_local_device. Never queue a command or switch to cloud to do that step. "
                    "Otherwise prefer connectors or the Bot's own cloud computer. Use local_computer only when "
                    "the user asks for something on their own device. The desktop user confirms each "
                    "operation. Copy the selected device_id exactly. The display_name is a label. "
                    + json.dumps(
                        {
                            "location": mode,
                            "devices": [
                                {"device_id": device_id, "display_name": name}
                                for device_id, name in devices.items()
                            ],
                        }
                    )
                ),
            }
        )
        return request.override(system_message=SystemMessage(content_blocks=blocks))

    def wrap_model_call(
        self, request: ModelRequest[Any], handler: Callable[[ModelRequest[Any]], ModelResponse[Any]]
    ) -> ModelResponse[Any]:
        return handler(self._scope(request, self._mode(request.state, _current_thread())))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        mode = await asyncio.to_thread(self._mode, request.state, _current_thread())
        return await handler(self._scope(request, mode))

    def _blocked(self, request: ToolCallRequest, thread: str) -> ToolMessage | None:
        name = str(request.tool_call.get("name") or "")
        if not tool_at_location(name, self._mode(request.state, thread)):
            return ToolMessage(
                content="This operation is unavailable at the computer location the user selected.",
                name=name,
                tool_call_id=str(request.tool_call.get("id") or ""),
                status="error",
            )
        return None

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        return self._blocked(request, _current_thread()) or handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        blocked = await asyncio.to_thread(self._blocked, request, _current_thread())
        return blocked or await handler(request)
