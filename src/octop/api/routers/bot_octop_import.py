"""Octop Bot desktop: one-click import from an Octop install on this computer."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from octop.api.common.bot_desktop import Owner, Services
from octop.api.deps import get_server
from octop.infra.agents import bot_octop_import as octop_import
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.server import OctopServer

router = APIRouter(prefix="/octop-import")


class SourceAgentView(BaseModel):
    agent_id: str
    name: str
    threads: int = Field(description="Chats this assistant has in Octop.")
    exists: bool = Field(description="Already here (imported before); importing skips it.")


class OctopImportPreview(BaseModel):
    available: bool = Field(description="Whether Octop is installed on this computer.")
    home: str | None = Field(default=None, description="Octop's data folder, e.g. `~/.octop`.")
    agents: list[SourceAgentView] = Field(default_factory=list)
    providers: list[str] = Field(
        default_factory=list, description="Octop model providers not here yet."
    )


class ImportedAgentView(BaseModel):
    agent_id: str
    name: str
    status: str = Field(description="`imported`, `skipped` or `failed`.")
    reason: str = Field(
        description="Why it was skipped or failed: `exists`, `team`, `folder_exists`, `error`."
    )
    detail: str = ""
    threads: int
    channels: int = Field(description="IM channels brought in, paused.")
    cron_jobs: int = Field(description="Scheduled tasks brought in, paused.")


class OctopImportReport(BaseModel):
    home: str
    agents: list[ImportedAgentView]
    providers: list[str] = Field(description="Model providers added.")


@router.get(
    "",
    summary="Find an Octop install to import",
    description="Desktop app only. Lists the assistants of the Octop install in `~/.octop`.",
)
async def octop_import_preview(services: Services, _user: Owner) -> OctopImportPreview:
    home = octop_import.find_octop_home(services.paths.root)
    if home is None:
        return OctopImportPreview(available=False)
    found = await asyncio.to_thread(octop_import.preview, services, home)
    return OctopImportPreview(
        available=True,
        home=found.home,
        agents=[SourceAgentView(**vars(agent)) for agent in found.agents],
        providers=found.providers,
    )


@router.post(
    "",
    summary="Import Octop's assistants, chats and model keys",
    description="Copies; Octop is left as it is. Assistants already here are skipped, so "
    "importing again only adds new ones. IM channels and scheduled tasks arrive paused.",
)
async def octop_import_run(
    services: Services,
    user: Owner,
    server: Annotated[OctopServer, Depends(get_server)],
) -> OctopImportReport:
    home = octop_import.find_octop_home(services.paths.root)
    if home is None:
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    assert server.app_runtime is not None
    report = await octop_import.import_octop(
        services, server.app_runtime.agent_registry, home, user.id
    )
    return OctopImportReport.model_validate(report.to_dict())
