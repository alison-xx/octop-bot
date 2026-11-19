"""Confirm a visible local transcript before appending it to the signed-in cloud workspace."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends

from octop.api.common.bot_desktop import Owner, Services
from octop.api.deps import get_server
from octop.api.routers.chat.share import _queue_projection
from octop.infra.cloud.bot_import import Imported, ImportRequest, Preview, import_chat, preview
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.server import OctopServer

router = APIRouter(prefix="/cloud/import")


@router.get(
    "/{bot_id}/{thread_id}", summary="Preview recent visible text from my personal dashboard chat"
)
async def preview_import(
    bot_id: str,
    thread_id: str,
    user: Owner,
    services: Services,
    server: Annotated[OctopServer, Depends(get_server)],
) -> Preview:
    try:
        return await asyncio.to_thread(preview, services, user.id, bot_id, thread_id)
    except OctopError as exc:
        if exc.code == ErrorCode.AGENT_BUSY:
            _queue_projection(server, bot_id, thread_id, user)
        raise


@router.post(
    "/{bot_id}/{thread_id}",
    summary="Append the confirmed text to my Octop Bot cloud workspace",
    description="Requires the same preview revision and connected cloud account. Repeating the request preserves hosted messages.",
)
async def confirm_import(
    bot_id: str, thread_id: str, body: ImportRequest, user: Owner, services: Services
) -> Imported:
    return await import_chat(services, user.id, bot_id, thread_id, body)
