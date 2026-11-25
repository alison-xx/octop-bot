"""Octop Bot's hosted work, using the connected account on this desktop."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, ConfigDict, Field

from octop.api.common.bot_desktop import AccountServices, Owner, Services
from octop.api.deps import get_server
from octop.infra.cloud import bot_work_models as dto
from octop.infra.cloud.bot_work import CloudWorkspace
from octop.infra.cloud.legacy_conversations import RestorePage, restore_page
from octop.infra.server import OctopServer

router = APIRouter(prefix="/cloud")


class RestoreLegacyPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cursor: str | None = Field(None, max_length=256)


@router.post(
    "/legacy-conversations/restore",
    summary="Restore a page of my legacy mobile conversations",
    description="Uses the cloud tenant's own Lynxce identity. Reuse next_cursor until it is null. Existing conversations and the source are preserved.",
    response_model=RestorePage,
)
async def restore_legacy(
    body: RestoreLegacyPage,
    user: Owner,
    services: AccountServices,
    server: Annotated[OctopServer, Depends(get_server)],
) -> RestorePage:
    assert server.app_runtime is not None
    return await restore_page(services, server.app_runtime.agent_registry, user.id, body.cursor)


async def read_workspace(
    user: Owner,
    services: Services,
    expected: Annotated[str | None, Header(alias="X-Octop-Cloud-Account", max_length=256)] = None,
) -> CloudWorkspace:
    return await CloudWorkspace.current(services, user.id, expected)


ReadWorkspace = Annotated[CloudWorkspace, Depends(read_workspace)]


@router.get("/capabilities", summary="Read my hosted work availability and cloud-capable models")
async def capabilities(workspace: ReadWorkspace) -> dto.Capabilities:
    return await workspace.capabilities()


@router.get("/sessions", summary="List my Octop Bot cloud conversations across devices")
async def sessions(
    workspace: ReadWorkspace, cursor: Annotated[str | None, Query(max_length=200)] = None
) -> dto.Sessions:
    return await workspace.list_sessions(cursor)


@router.get(
    "/sessions/{session_id}", summary="Read a cloud conversation and its hosted work status"
)
async def session(session_id: dto.Id, workspace: ReadWorkspace) -> dto.Session:
    return await workspace.session(session_id)


@router.post(
    "/turns",
    status_code=202,
    summary="Submit a turn for cloud execution",
    description="The hosted worker continues after this client closes. Only the typed message and an explicitly selected Bot's public role are sent.",
)
async def submit(turn: dto.Turn, user: Owner, services: Services) -> dto.Task:
    return await CloudWorkspace(services, user.id, turn.account_id).submit(turn)


@router.post("/tasks/{task_id}/cancel", summary="Stop a hosted task in my Octop Bot conversation")
async def cancel_task(
    task_id: dto.Id, body: dto.CancelTask, user: Owner, services: Services
) -> dto.Task:
    return await CloudWorkspace(services, user.id, body.account_id).cancel_task(task_id, body)


@router.get("/schedules", summary="List my Octop Bot schedules on the hosted scheduler")
async def schedules(workspace: ReadWorkspace) -> dto.Schedules:
    return await workspace.list_schedules()


@router.post("/schedules", status_code=201, summary="Create a hosted schedule for my cloud account")
async def create_schedule(
    body: dto.CreateSchedule, user: Owner, services: Services
) -> dto.Schedule:
    return await CloudWorkspace(services, user.id, body.account_id).create_schedule(body)


@router.put("/schedules/{task_id}/enabled", summary="Pause or resume an Octop Bot cloud schedule")
async def enable_schedule(
    task_id: dto.Id, body: dto.EnableSchedule, user: Owner, services: Services
) -> dto.Schedule:
    return await CloudWorkspace(services, user.id, body.account_id).enable_schedule(
        task_id, body.enabled
    )
