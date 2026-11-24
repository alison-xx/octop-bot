"""Desktop app: move this computer's Bots, chats and groups into the Octop Bot cloud."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from octop.api.common.bot_desktop import Owner, Services
from octop.api.deps import get_server
from octop.infra.cloud.move_out import MoveStatus, move_status, start_move
from octop.infra.desktop import bot_cloud_origin
from octop.infra.server import OctopServer
from octop.infra.utils.locale import resolve_request_locale

router = APIRouter(prefix="/cloud/move")


@router.post(
    "",
    summary="Move this computer's team to the Octop Bot cloud",
    description=(
        "Desktop app only, after signing in with Lynxce. Hands the Lynxce sign-in to the "
        "cloud, then sends every Bot, its chats, the groups and the team notes. Runs in the "
        "background: poll `GET /api/octop-bot/cloud/move`. Starting again after a failure "
        "only sends what is missing. Nothing on this computer is deleted."
    ),
)
async def move(
    request: Request,
    user: Owner,
    services: Services,
    server: Annotated[OctopServer, Depends(get_server)],
) -> MoveStatus:
    assert server.app_runtime is not None
    return start_move(
        services,
        server.app_runtime.agent_registry,
        user.id,
        bot_cloud_origin(),
        resolve_request_locale(request),
    )


@router.get(
    "",
    summary="Progress of moving to the Octop Bot cloud",
    description="When done, `access_token` signs the desktop in to the cloud.",
)
async def moving(user: Owner, services: Services) -> MoveStatus:
    del services  # desktop only
    return move_status(user.id)
