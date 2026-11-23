"""What an Octop Bot client can expect from this server, before anyone signs in."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from octop.api.deps import get_server
from octop.infra.cloud.computers.manager import current_manager
from octop.infra.desktop import bot_cloud_enabled, bot_desktop_enabled, bot_web_enabled
from octop.infra.setup.self_update import get_local_version

router = APIRouter()


class ServerCapabilities(BaseModel):
    wallet: bool = Field(
        description="Lynxce balance and recharge through this server (desktop shell only)."
    )
    cloud_computer: bool = Field(
        default=False, description="Each Bot can run on its own cloud computer."
    )
    file_store: Literal["local", "object"] = Field(
        default="local",
        description="Where attachments and Bot outputs are kept: this server's disk, or an object "
        "store that hands out signed download links.",
    )


class ServerInfo(BaseModel):
    product: Literal["octop-bot"] = "octop-bot"
    version: str
    edition: Literal["desktop", "web", "cloud", "server"] = Field(
        description="desktop: the Octop Bot app's local service; web: the Bot web/NAS build; "
        "cloud: Octop Bot cloud, where every Lynxce account gets its own account; "
        "server: a plain Octop server."
    )
    setup_required: bool = Field(description="No account exists yet; the first sign-in sets it up.")
    sign_in: list[Literal["lynxce", "password"]] = Field(
        description="Ways to sign in: as the instance's Lynxce owner, or with a local password."
    )
    capabilities: ServerCapabilities


@router.get(
    "/server-info",
    summary="Describe this server to Octop Bot clients",
    response_model=ServerInfo,
)
async def server_info(response: Response, server: Any = Depends(get_server)) -> ServerInfo:
    """Public: lets a client that was given this address check it before showing a sign-in form."""
    response.headers["Cache-Control"] = "no-store"
    if bot_cloud_enabled():
        edition: Literal["desktop", "web", "cloud", "server"] = "cloud"
    elif bot_desktop_enabled():
        edition = "desktop"
    elif bot_web_enabled():
        edition = "web"
    else:
        edition = "server"
    users = server.user_manager.count() if server.user_manager is not None else 0
    sign_in: list[Literal["lynxce", "password"]] = {
        "cloud": ["lynxce"],
        "web": ["lynxce", "password"],
    }.get(edition, ["password"])  # type: ignore[assignment]
    return ServerInfo(
        version=get_local_version(),
        edition=edition,
        # A cloud server is set up by its operator; tenants never see the wizard.
        setup_required=users == 0 and edition != "cloud",
        sign_in=sign_in,
        capabilities=ServerCapabilities(
            wallet=edition in ("desktop", "cloud"),
            cloud_computer=edition == "cloud" and current_manager() is not None,
            file_store="object" if edition == "cloud" else "local",
        ),
    )
