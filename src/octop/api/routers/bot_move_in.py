"""Octop Bot cloud: receive what a desktop app kept on its own computer."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends

from octop.api.deps import current_user, get_server
from octop.infra.cloud.move_in import (
    Moved,
    MovedBot,
    MovedGroup,
    MovedNotes,
    MovedThread,
    move_bot,
    move_group,
    move_notes,
    move_thread,
)
from octop.infra.desktop import bot_cloud_enabled
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.server import OctopServer
from octop.infra.users.identity import User


def _cloud(server: Annotated[OctopServer, Depends(get_server)]) -> OctopServer:
    if not bot_cloud_enabled():
        raise OctopError.localized(ErrorCode.FORBIDDEN)
    assert server.services is not None and server.app_runtime is not None
    return server


Server = Annotated[OctopServer, Depends(_cloud)]
Owner = Annotated[User, Depends(current_user)]

router = APIRouter(prefix="/move-in")

_REPEAT = "Sending the same `source` again returns what it became the first time."


@router.post(
    "/bots",
    summary="Add a Bot moved from the desktop app",
    description="A Bot of the same name joins the existing one. The desktop's Chief joins "
    "the cloud Chief. " + _REPEAT,
)
async def moved_bot(body: MovedBot, user: Owner, server: Server) -> Moved:
    assert server.services is not None and server.app_runtime is not None
    return await move_bot(server.services, server.app_runtime.agent_registry, user, body)


@router.post(
    "/threads",
    summary="Add a chat moved from the desktop app",
    description="The Bot keeps the conversation as context and it shows in its history. " + _REPEAT,
)
async def moved_thread(body: MovedThread, user: Owner, server: Server) -> Moved:
    assert server.services is not None and server.app_runtime is not None
    runtime = server.app_runtime
    return await move_thread(
        server.services, runtime.agent_registry, runtime.gateway.thread_registry, user, body
    )


@router.post(
    "/groups",
    summary="Add a Bot group moved from the desktop app",
    description="Members are this server's Bot ids. Messages keep their times. " + _REPEAT,
)
async def moved_group(body: MovedGroup, user: Owner, server: Server) -> Moved:
    assert server.services is not None
    return await asyncio.to_thread(move_group, server.services, user, body)


@router.post(
    "/notes",
    status_code=204,
    summary="Add the desktop's team notes",
    description="Appended below the cloud's notes, once.",
)
async def moved_notes(body: MovedNotes, user: Owner, server: Server) -> None:
    assert server.services is not None
    await asyncio.to_thread(move_notes, server.services, user, body)
