"""Authenticated pairing and the native desktop's outbound connection."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Literal

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError

from octop.api.deps import current_user, get_server
from octop.infra.agents.bot_workspace import is_private_bot
from octop.infra.bot_tasks.placement import Placement, bot_placement, set_bot_placement
from octop.infra.cloud.devices.hub import DeviceHub, DeviceId, DeviceSession, LocalResult
from octop.infra.cloud.devices.transfers import FileBytes
from octop.infra.db.repos.settings import SettingsRepo
from octop.infra.desktop import bot_cloud_enabled
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.server import OctopServer
from octop.infra.users.identity import User

router = APIRouter(prefix="/local-devices")


class DesktopIdentity(BaseModel):
    device_id: DeviceId
    label: str = Field(min_length=1, max_length=80)


class Ticket(BaseModel):
    owner: int
    ticket: str = Field(description="Single-use device connection ticket, valid for 30 seconds.")


class DesktopReply(BaseModel):
    kind: Literal["ready", "result"]
    id: str = Field(min_length=1, max_length=64)
    result: str = Field(default="", max_length=65_536)
    transfer: FileBytes | None = None


class PlacementChoice(BaseModel):
    default: Placement


class DevicePlacement(PlacementChoice):
    devices: dict[str, str] = Field(
        description="Currently connected device IDs and names owned by this account."
    )


def _owned_bot(server: OctopServer, user: User, agent_id: str) -> SettingsRepo:
    if server.services is None:
        raise OctopError.localized(ErrorCode.SETUP_REQUIRED)
    bot = server.services.agent_repo.get(agent_id)
    if (
        not bot_cloud_enabled()
        or user.is_admin
        or not bot
        or bot.user_id != user.id
        or bot.is_shared
        or is_private_bot(bot)
    ):
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    return server.services.settings_repo


@router.get(
    "/placement/{agent_id}",
    response_model=DevicePlacement,
    summary="Read computer locations for my Bot",
)
async def placement(
    agent_id: str, user: User = Depends(current_user), server: OctopServer = Depends(get_server)
) -> DevicePlacement:
    settings = await asyncio.to_thread(_owned_bot, server, user, agent_id)
    if server.app_runtime is None:
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    return DevicePlacement(
        default=await asyncio.to_thread(bot_placement, settings, agent_id),
        devices=server.app_runtime.agent_registry.local_devices.online(user.id),
    )


@router.put(
    "/placement/{agent_id}",
    response_model=PlacementChoice,
    summary="Choose a Bot's default computer location",
)
async def change_placement(
    agent_id: str,
    choice: PlacementChoice,
    user: User = Depends(current_user),
    server: OctopServer = Depends(get_server),
) -> PlacementChoice:
    settings = await asyncio.to_thread(_owned_bot, server, user, agent_id)
    await asyncio.to_thread(set_bot_placement, settings, agent_id, choice.default)
    return choice


@router.post("/ticket", response_model=Ticket, summary="Connect my desktop to my cloud Bots")
async def pair(
    identity: DesktopIdentity,
    user: User = Depends(current_user),
    server: OctopServer = Depends(get_server),
) -> Ticket:
    if not bot_cloud_enabled() or user.is_admin or server.app_runtime is None:
        raise OctopError.localized(ErrorCode.FORBIDDEN)
    try:
        key = server.app_runtime.agent_registry.local_devices.tickets.issue(
            user.id, identity.device_id, identity.label
        )
    except ValueError as exc:
        raise OctopError.localized(ErrorCode.FORBIDDEN) from exc
    return Ticket(ticket=key, owner=user.id)


async def _outbound(ws: WebSocket, session: DeviceSession) -> None:
    while True:
        call = await session.outgoing.get()
        if not call.result.done():
            await ws.send_json({"kind": "request", "id": call.id, **call.payload})
            await asyncio.wait([call.result])
            if call.result.cancelled():
                await ws.send_json({"kind": "cancel", "id": call.id})


@router.websocket("/ws")
async def device_socket(ws: WebSocket) -> None:
    # The native client has no browser Origin. Authentication is in the first frame so tickets
    # do not end up in URLs or HTTP access logs.
    if ws.headers.get("origin") or not bot_cloud_enabled():
        await ws.close(code=1008)
        return
    await ws.accept()
    hub: DeviceHub = ws.app.state.octop_server.app_runtime.agent_registry.local_devices
    try:
        raw = await asyncio.wait_for(ws.receive_text(), 5)
    except (TimeoutError, WebSocketDisconnect):
        with contextlib.suppress(RuntimeError):
            await ws.close(code=1008)
        return
    ticket = hub.tickets.consume(raw)
    if ticket is None:
        await ws.close(code=1008)
        return
    session = hub.connect(ticket.owner, ticket.device_id, ticket.label)

    async def receive() -> None:
        await ws.send_json({"kind": "connected"})
        while True:
            reply = DesktopReply.model_validate_json(await ws.receive_text())
            if reply.kind == "result":
                hub.answer(session, reply.id, LocalResult(reply.result, reply.transfer))
            elif (
                session.pending
                and session.pending.id == reply.id
                and not session.pending.result.done()
                and not session.pending.dispatched
            ):
                # The local user approved this still-live request. A late click after
                # cancellation, timeout or disconnect must not start an operation.
                session.pending.dispatched = True
                await ws.send_json(
                    {
                        "kind": "execute",
                        "id": reply.id,
                        "transfer": session.pending.download.model_dump()
                        if session.pending.download
                        else None,
                    }
                )

    tasks = [
        asyncio.create_task(_outbound(ws, session)),
        asyncio.create_task(receive()),
        asyncio.create_task(session.closed.wait()),
    ]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except (WebSocketDisconnect, ValidationError):
        pass
    finally:
        hub.disconnect(session)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await ws.close()
