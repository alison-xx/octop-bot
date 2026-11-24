"""Octop Bot cloud: shadow Bots that give a desktop app's Bots a cloud computer.

See ``octop.infra.cloud.bot_cloud.shadows`` and ``docs/octop-bot-accounts.md`` §7. The desktop
signs in with ``POST /api/auth/lynxce/token-login``, registers each Bot that uses a cloud
computer here, and then drives that computer through ``/api/octop-bot/computers/{agent_id}``.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response
from pydantic import BaseModel, Field

from octop.api.deps import current_user, get_server
from octop.infra.cloud.bot_cloud import shadows
from octop.infra.db.services import SharedServices
from octop.infra.desktop import bot_cloud_enabled
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.server import OctopServer
from octop.infra.users.identity import User


def _services(server: Annotated[OctopServer, Depends(get_server)]) -> SharedServices:
    if not bot_cloud_enabled():
        raise OctopError.localized(ErrorCode.FORBIDDEN)
    assert server.services is not None
    return server.services


Services = Annotated[SharedServices, Depends(_services)]
Owner = Annotated[User, Depends(current_user)]
Origin = Annotated[
    str,
    Path(
        description="`<desktop install id>:<desktop agent_id>`, e.g. "
        "`01JD3Q8Z2N6W4M5X7Y9A0B1C2D:K7Q2PZ`.",
        max_length=128,
    ),
]

router = APIRouter(prefix="/remote-bots")


class RemoteBot(BaseModel):
    name: str = Field(min_length=1, max_length=shadows.MAX_NAME, description="The Bot's name.")
    avatar: str | None = Field(
        default=None,
        max_length=shadows.MAX_AVATAR,
        description="Optional avatar (URL or the desktop's look id), shown in operator views.",
    )


class RemoteBotRef(BaseModel):
    agent_id: str = Field(
        description="The shadow Bot's id: use it with `/api/octop-bot/computers/{agent_id}`."
    )
    origin: str
    created: bool = Field(description="True when this call made the shadow Bot.")


def _origin(origin: str) -> str:
    if not shadows.valid_origin(origin):
        raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS, status=422)
    return origin


@router.put(
    "/{origin}",
    summary="Register a desktop Bot that uses a cloud computer",
    description=(
        "Creates (or updates the name and avatar of) the hidden shadow Bot for this desktop "
        "Bot and returns its id. It never appears in Bot lists, group pickers or the phone "
        "apps, runs no agent, and only owns a cloud computer, which starts when it is first "
        "used. Calling this again also marks it in use: a shadow Bot nobody has updated or "
        "used for 30 days is deleted with its computer."
    ),
    response_model=RemoteBotRef,
)
async def put_remote_bot(
    origin: Origin, body: RemoteBot, user: Owner, services: Services
) -> RemoteBotRef:
    key = _origin(origin)
    row, created = await asyncio.to_thread(
        shadows.put_shadow,
        services,
        user.id,
        key,
        name=body.name.strip(),
        avatar=body.avatar,
    )
    return RemoteBotRef(agent_id=row.agent_id, origin=key, created=created)


@router.delete(
    "/{origin}",
    summary="Remove a desktop Bot's cloud computer",
    description="For a Bot deleted on the desktop: deletes its shadow Bot; its cloud computer "
    "is stopped and billed up to now within a minute. Deleting one that does not exist is fine.",
    status_code=204,
)
async def delete_remote_bot(origin: Origin, user: Owner, services: Services) -> Response:
    await asyncio.to_thread(shadows.delete_shadow, services, user.id, _origin(origin))
    return Response(status_code=204)
