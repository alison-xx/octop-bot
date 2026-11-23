"""What an Octop Bot client can expect from this server, before anyone signs in."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from octop.api.deps import get_server
from octop.infra.desktop import bot_desktop_enabled, bot_web_enabled
from octop.infra.setup.self_update import get_local_version

router = APIRouter()


class ServerCapabilities(BaseModel):
    wallet: bool = Field(
        description="Lynxce balance and recharge through this server (desktop shell only)."
    )
    cloud_computer: bool = Field(
        default=False, description="Each Bot can run on its own cloud computer."
    )
    file_store: Literal["local"] = Field(
        default="local", description="Where attachments and Bot outputs are kept."
    )


class ServerInfo(BaseModel):
    product: Literal["octop-bot"] = "octop-bot"
    version: str
    edition: Literal["desktop", "web", "server"] = Field(
        description="desktop: the Octop Bot app's local service; web: the Bot web/NAS build; "
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
    if bot_desktop_enabled():
        edition: Literal["desktop", "web", "server"] = "desktop"
    elif bot_web_enabled():
        edition = "web"
    else:
        edition = "server"
    users = server.user_manager.count() if server.user_manager is not None else 0
    return ServerInfo(
        version=get_local_version(),
        edition=edition,
        setup_required=users == 0,
        sign_in=["lynxce", "password"] if edition == "web" else ["password"],
        capabilities=ServerCapabilities(wallet=edition == "desktop"),
    )
