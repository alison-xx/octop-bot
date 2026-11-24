"""A Bot's profile: upcoming scheduled tasks and the files it made for me."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from octop.api.deps import current_user, get_server
from octop.infra.agents.bot_library import bot_library
from octop.infra.agents.bot_workspace import require_own_bot
from octop.infra.agents.workspace.dir import agent_facing_workspace_dir_from_config
from octop.infra.cloud.computers.manager import current_manager
from octop.infra.cron.upcoming import upcoming_jobs
from octop.infra.desktop import bot_cloud_enabled
from octop.infra.users.identity import User
from octop.infra.utils.locale import resolve_request_locale

router = APIRouter(prefix="/bots/{agent_id}")


class UpcomingJob(BaseModel):
    id: str = Field(
        description="Cron job id; toggle it with PATCH /api/agents/{agent_id}/cron/{id}."
    )
    name: str
    enabled: bool
    trigger: str
    schedule: str = Field(
        description="One line, localized, in the server timezone (e.g. 'Weekdays, 8:50')."
    )
    next_run_at: int | None = Field(
        description="Unix seconds of the next run; null when paused or not on a clock."
    )
    can_toggle: bool = Field(description="False for script tasks and one-time tasks already past.")


class Upcoming(BaseModel):
    timezone: str
    jobs: list[UpcomingJob]


@router.get(
    "/upcoming",
    summary="List a Bot's scheduled tasks, soonest first",
    response_model=Upcoming,
    description="Enabled tasks by next run, then tasks without a clock time, then paused ones.",
)
async def upcoming(
    agent_id: str,
    request: Request,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> Upcoming:
    await asyncio.to_thread(require_own_bot, server.services, user.id, agent_id)
    manager = server.app_runtime.cron_manager
    timezone = server.services.config.default_timezone
    rows = await asyncio.to_thread(manager.list_by_agent, agent_id, user_id=user.id)
    jobs = upcoming_jobs(
        rows,
        next_run=manager.next_run_time,
        locale=resolve_request_locale(request),
        timezone=timezone,
    )
    return Upcoming(timezone=timezone, jobs=[UpcomingJob.model_validate(job) for job in jobs])


class LibraryFile(BaseModel):
    name: str
    path: str = Field(description="Workspace-relative path, or a host path on the desktop app.")
    size: int | None = Field(description="Bytes, when the store reports it.")
    mime: str | None
    created_at: int = Field(description="Unix seconds the file was last written.")
    thread_id: str = Field(description="The conversation that produced it.")
    period: Literal["today", "week", "older"] = Field(
        description="Recency on the server's calendar: today, the last seven days, or older."
    )
    url: str = Field(
        description="Download link (/api/agents/{id}/workspace/download?path=…). "
        "On Octop Bot cloud, POST the same path to …/workspace/download-link for a signed URL."
    )


class Library(BaseModel):
    files: list[LibraryFile]


@router.get(
    "/library",
    summary="List the files a Bot made for me, newest first",
    response_model=Library,
    description="Files the Bot wrote or sent in my conversations with it that still exist.",
)
async def library(
    agent_id: str,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> Library:
    await asyncio.to_thread(require_own_bot, server.services, user.id, agent_id)
    registry = server.app_runtime.agent_registry

    def where() -> tuple[Any, list[str]]:
        facing = agent_facing_workspace_dir_from_config(registry.get_config(agent_id))
        host = str(registry.resolve_workspace_dir(agent_id, persist_if_missing=False))
        return registry.workspace_for_agent(agent_id), [root for root in (facing, host) if root]

    workspace, roots = await asyncio.to_thread(where)
    cloud = bot_cloud_enabled()
    files = await bot_library(
        thread_repo=server.services.thread_repo,
        workspace=workspace,
        roots=roots,
        agent_id=agent_id,
        user_id=user.id,
        timezone=server.services.config.default_timezone,
        cloud=cloud,
        # On cloud computers the files live on the Bot's computer: never wake it to list them.
        check=not (cloud and current_manager() is not None),
    )
    return Library(files=[LibraryFile.model_validate(item) for item in files])
