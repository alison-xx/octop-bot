"""User-managed native app grants and manual takeover for one personal Bot."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from octop.api.deps import get_server, require_permission
from octop.infra.control.desktop.bot_apps import AllowedApp, BotComputer, ComputerState, Level
from octop.infra.db.services import RepoBundle
from octop.infra.server import OctopServer
from octop.infra.users.identity import User

router = APIRouter(prefix="/bots/{bot_id}/computer")
Owner = Annotated[User, Depends(require_permission("desktop"))]


def host(server: OctopServer = Depends(get_server)) -> tuple[BotComputer, RepoBundle]:
    assert server.services and server.app_runtime
    return server.app_runtime.agent_registry.bot_computer, server.services.repos


Host = Annotated[tuple[BotComputer, RepoBundle], Depends(host)]


class AppGrants(BaseModel):
    level: Level
    app_ids: list[str] = Field(max_length=100)


class Handoff(BaseModel):
    paused: bool


@router.get("", summary="Read native app grants and current Bot control")
def state(bot_id: str, user: Owner, conn: Host) -> ComputerState:
    computer, repos = conn
    return computer.state(repos, user.id, bot_id)


@router.get("/apps", summary="Choose running local applications to grant to my Bot")
async def apps(bot_id: str, user: Owner, conn: Host) -> list[AllowedApp]:
    computer, repos = conn
    await asyncio.to_thread(computer.key, repos, user.id, bot_id)
    return await computer.choices()


@router.put("", summary="Set local application grants and permitted input level")
async def configure(bot_id: str, body: AppGrants, user: Owner, conn: Host) -> ComputerState:
    computer, repos = conn
    return await computer.configure(repos, user.id, bot_id, body.level, body.app_ids)


@router.put("/handoff", summary="Take over this Bot's local applications or hand them back")
def handoff(bot_id: str, body: Handoff, user: Owner, conn: Host) -> ComputerState:
    computer, repos = conn
    return computer.pause(repos, user.id, bot_id, body.paused)
