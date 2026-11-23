"""Octop Bot cloud: each Bot's cloud computer, for the Bot profile's "Cloud computer" panel."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from octop.api.deps import current_user, get_server
from octop.infra.cloud.computers.manager import computer_manager
from octop.infra.desktop import bot_cloud_enabled
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import User

router = APIRouter(prefix="/computers")


class ComputerStatus(BaseModel):
    state: Literal["none", "running", "paused"] = Field(
        description="none: not started yet (it starts on the Bot's first tool use)."
    )
    spec: str = Field(description="Size of the computer, e.g. standard.")
    running_since: float | None = Field(default=None, description="Unix time it last started.")
    paid_until: float | None = Field(
        default=None, description="Unix time the running time already paid for runs out."
    )


def _owned(server: Any, user: User, agent_id: str) -> Any:
    if not bot_cloud_enabled():
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    manager = computer_manager(server.services)
    row = server.services.agent_repo.get(agent_id)
    if manager is None or row is None or row.user_id != user.id:
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    return manager


def _status(manager: Any, agent_id: str, user_id: int) -> ComputerStatus:
    record = manager.record(agent_id, user_id)
    if record.instance_id is None:
        return ComputerStatus(state="none", spec=record.spec)
    return ComputerStatus(
        state="running" if record.running else "paused",
        spec=record.spec,
        running_since=record.running_since,
        paid_until=record.paid_until if record.running else None,
    )


@router.get("/{agent_id}", summary="Read a Bot's cloud computer", response_model=ComputerStatus)
async def computer_status(
    agent_id: str, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> ComputerStatus:
    manager = _owned(server, user, agent_id)
    return await asyncio.to_thread(_status, manager, agent_id, user.id)


@router.post(
    "/{agent_id}/pause",
    summary="Pause a Bot's cloud computer now",
    description="Stops billing for running time; the next tool use resumes it with its files.",
    response_model=ComputerStatus,
)
async def pause_computer(
    agent_id: str, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> ComputerStatus:
    manager = _owned(server, user, agent_id)
    await asyncio.to_thread(manager.pause, agent_id, user.id)
    return await asyncio.to_thread(_status, manager, agent_id, user.id)
