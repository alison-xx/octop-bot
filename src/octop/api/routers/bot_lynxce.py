"""The current Octop Bot user's connection to Lynxce's personal model gateway."""

from __future__ import annotations

import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from octop.api.common.bot_desktop import Owner, Services
from octop.api.deps import get_server
from octop.i18n import tr
from octop.infra.agents.providers import lynxce as models
from octop.infra.auth import lynxce as account
from octop.infra.server import OctopServer
from octop.infra.utils.locale import resolve_request_locale

router = APIRouter(prefix="/lynxce")


class AccountStatus(BaseModel):
    connected: bool
    selected_model: str | None


class BrowserLogin(BaseModel):
    attempt_id: str
    authorization_url: str = Field(description="Open this URL in the user's system browser.")


class LoginProgress(BaseModel):
    state: Literal["pending", "connected", "failed"]
    detail: str | None = None


class ChatModel(BaseModel):
    id: str
    name: str


class ModelCatalog(BaseModel):
    models: list[ChatModel]


class ModelSelection(BaseModel):
    model_id: str = Field(
        min_length=1, max_length=512, description="ID from this account's chat model catalog."
    )


@router.get("/status", summary="Read my Lynxce connection and workspace model")
def status(user: Owner, services: Services) -> AccountStatus:
    return AccountStatus(
        connected=account.is_connected(services, user.id),
        selected_model=models.selected_account_model(services, user.id),
    )


@router.post("/login", summary="Start Lynxce authorization in the system browser")
async def login(user: Owner, services: Services) -> BrowserLogin:
    attempt_id, url = await account.start_login(services, user.id)
    return BrowserLogin(attempt_id=attempt_id, authorization_url=url)


@router.get("/login/{attempt_id}", summary="Check my browser authorization")
async def login_progress(
    attempt_id: str, request: Request, user: Owner, services: Services
) -> LoginProgress:
    state, detail = await account.poll_login(services, user.id, attempt_id)
    if state == "connected":
        return LoginProgress(state="connected")
    if state == "pending":
        return LoginProgress(state="pending")
    key = state if state in {"expired", "cancelled"} else detail
    if key not in {"expired", "cancelled", "access_denied", "missing_chat_scope"}:
        key = "token_exchange_failed"
    return LoginProgress(
        state="failed",
        detail=tr(f"octop_bot.lynxce.{key}", user.locale or resolve_request_locale(request)),
    )


@router.delete(
    "/login/{attempt_id}", status_code=204, summary="Cancel my pending Lynxce authorization"
)
async def cancel_login(attempt_id: str, user: Owner, services: Services) -> None:
    await account.cancel_login(services, user.id, attempt_id)


@router.get("/models", summary="List chat models available to my Lynxce account")
async def catalog(user: Owner, services: Services) -> ModelCatalog:
    entries = await models.list_account_models(services, user.id)
    return ModelCatalog(models=[ChatModel.model_validate(entry) for entry in entries])


@router.put("/model", summary="Use a Lynxce chat model in my Bot workspace")
async def select_model(
    body: ModelSelection,
    user: Owner,
    services: Services,
    server: Annotated[OctopServer, Depends(get_server)],
) -> AccountStatus:
    selected = await models.select_account_model(services, user.id, body.model_id)
    if server.app_runtime is not None:
        await server.app_runtime.agent_registry.on_account_model_selected(user.id)
    return AccountStatus(connected=True, selected_model=selected)


@router.delete("/model", status_code=204, summary="Switch back to my configured Octop providers")
def clear_model(user: Owner, services: Services) -> None:
    models.clear_account_model(services, user.id)


@router.delete(
    "/session", status_code=204, summary="Disconnect my Lynxce account from this desktop"
)
async def disconnect(user: Owner, services: Services) -> None:
    await account.disconnect(services, user.id)
    await asyncio.to_thread(models.clear_account_model, services, user.id)
