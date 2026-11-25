"""Authenticated local user's ordinary Lynxce Cloud login."""

import asyncio
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, SecretStr

from octop.api.common.bot_desktop import AccountServices, Owner, Services
from octop.api.common.sensitive_input import SensitiveInputRoute
from octop.api.deps import get_server
from octop.infra.agents.providers import lynxce as account_models
from octop.infra.auth import lynxce_wechat as wechat
from octop.infra.auth.lynxce_cloud import (
    CloudAccountStatus,
    cloud_account,
    login_cloud,
    login_cloud_code,
    login_cloud_workbuddy,
    logout_cloud,
    request_login_code,
)
from octop.infra.desktop import bot_cloud_enabled, bot_desktop_enabled
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.server import OctopServer

logger = logging.getLogger(__name__)
Server = Annotated[OctopServer, Depends(get_server)]


async def _signed_in(
    server: OctopServer, services: Services, user_id: int, status: CloudAccountStatus
) -> CloudAccountStatus:
    """Desktop: one Lynxce sign-in also brings the account's chat models (no browser grant)."""
    if not bot_desktop_enabled() or not status.connected or not status.account_id:
        return status
    try:
        changed = await account_models.adopt_cloud_account(services, user_id, status.account_id)
    except OctopError:
        # Sign-in still stands; Settings offers to connect a model again.
        logger.warning("could not set up the Lynxce chat key for user %s", user_id)
        return status
    if changed and server.app_runtime is not None:
        await server.app_runtime.agent_registry.on_account_model_selected(user_id)
    return status


router = APIRouter(prefix="/cloud", route_class=SensitiveInputRoute)


class CloudLogin(BaseModel):
    account: str
    password: SecretStr


@router.get("/account", summary="Read my saved Lynxce Cloud identity")
async def status(user: Owner, services: AccountServices) -> CloudAccountStatus:
    """Returns the current user’s bound Lynxce name and portrait on the desktop or cloud."""
    return await cloud_account(services, user.id)


@router.post("/account", summary="Sign in to Lynxce Cloud with my existing account")
async def login(
    body: CloudLogin, user: Owner, services: Services, server: Server
) -> CloudAccountStatus:
    status = await login_cloud(services, user.id, body.account, body.password.get_secret_value())
    return await _signed_in(server, services, user.id, status)


class CodeRequest(BaseModel):
    target: str = Field(
        min_length=1,
        max_length=256,
        description="Lynxce phone number or email to send the code to.",
    )
    locale: str | None = Field(
        default=None, max_length=16, description="Language of the emailed code (zh or en)."
    )


class CodeSent(BaseModel):
    channel: Literal["phone", "email"] = Field(description="Where Lynxce sent the code.")


class CodeLogin(BaseModel):
    target: str = Field(min_length=1, max_length=256, description="The phone number or email.")
    code: SecretStr = Field(description="Six-digit code from the text message or email.")
    password: SecretStr | None = Field(
        default=None,
        description="Only after a `LYNXCE_SIGNUP_PASSWORD_REQUIRED` reply: the sign-in password "
        "for the new Lynxce account (a new email needs one). Sent with the same code.",
    )


@router.post(
    "/account/code",
    summary="Send me a Lynxce sign-in code",
    description=(
        "Lynxce texts or emails a six-digit code. Accounts that do not exist yet are created "
        "on first sign-in; a new email also needs a sign-in password."
    ),
)
async def send_code(body: CodeRequest, user: Owner) -> CodeSent:
    del user  # any signed-in local user; the code goes to the target, not to us
    if not bot_desktop_enabled():
        raise OctopError.localized(ErrorCode.FORBIDDEN)
    return CodeSent(channel=await request_login_code(body.target, body.locale))


@router.post("/account/code-login", summary="Sign in to Lynxce Cloud with a one-time code")
async def login_code(
    body: CodeLogin, user: Owner, services: Services, server: Server
) -> CloudAccountStatus:
    password = body.password.get_secret_value() if body.password else None
    status = await login_cloud_code(
        services, user.id, body.target, body.code.get_secret_value(), password
    )
    return await _signed_in(server, services, user.id, status)


class WorkbuddyLogin(BaseModel):
    handoff_code: SecretStr = Field(
        description="One-time code from Lynxce's WorkBuddy sign-in, captured by the desktop shell."
    )


@router.post(
    "/account/workbuddy",
    summary="Sign in to Lynxce Cloud with my WorkBuddy account",
    description=(
        "Exchanges the one-time code Lynxce issues after a WorkBuddy authorization for a "
        "Lynxce session. The account is the Lynxce account bound to that WorkBuddy identity, "
        "which may differ from an account signed in with a password. Desktop client only."
    ),
)
async def login_workbuddy(
    body: WorkbuddyLogin, user: Owner, services: Services, server: Server
) -> CloudAccountStatus:
    status = await login_cloud_workbuddy(services, user.id, body.handoff_code.get_secret_value())
    return await _signed_in(server, services, user.id, status)


@router.delete("/account", summary="Sign out of Lynxce Cloud on this device")
async def logout(
    user: Owner, services: Services, expected_account_id: str | None = None
) -> CloudAccountStatus:
    if bot_desktop_enabled():
        await account_models.revoke_cloud_key(services, user.id, expected_account_id)
    status = await logout_cloud(services, user.id, expected_account_id=expected_account_id)
    if bot_desktop_enabled() and not status.connected:
        await asyncio.to_thread(account_models.release_cloud_account, services, user.id)
    return status


def _wechat_desktop_only() -> None:
    if bot_cloud_enabled():
        raise OctopError.localized(ErrorCode.FORBIDDEN)


wechat_router = APIRouter(
    prefix="/account/wechat",
    route_class=SensitiveInputRoute,
    dependencies=[Depends(_wechat_desktop_only)],
)


class WechatFinish(BaseModel):
    flow_id: str = Field(max_length=128)
    code: SecretStr
    state: SecretStr


class WechatBind(BaseModel):
    flow_id: str = Field(max_length=128)
    phone: str = Field(max_length=64)
    code: SecretStr
    password: SecretStr | None = None


@wechat_router.post("/start", summary="Start desktop WeChat sign-in")
async def wechat_start(user: Owner, services: Services) -> wechat.StartResult:
    del services
    return await wechat.start(user.id)


@wechat_router.post("/finish", summary="Finish desktop WeChat authorization")
async def wechat_finish(
    body: WechatFinish, user: Owner, services: Services, server: Server
) -> CloudAccountStatus | wechat.BindRequired:
    result = await wechat.finish(
        services, user.id, body.flow_id, body.code.get_secret_value(), body.state.get_secret_value()
    )
    if isinstance(result, CloudAccountStatus):
        return await _signed_in(server, services, user.id, result)
    return result


@wechat_router.post("/bind", summary="Bind a phone to a WeChat account")
async def wechat_bind(
    body: WechatBind, user: Owner, services: Services, server: Server
) -> CloudAccountStatus:
    result = await wechat.bind(
        services,
        user.id,
        body.flow_id,
        body.phone,
        body.code.get_secret_value(),
        body.password.get_secret_value() if body.password else None,
    )
    return await _signed_in(server, services, user.id, result)
