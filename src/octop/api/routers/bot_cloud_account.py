"""Authenticated local user's ordinary Lynxce Cloud login."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, SecretStr

from octop.api.common.bot_desktop import Owner, Services
from octop.infra.auth.lynxce_cloud import (
    CloudAccountStatus,
    cloud_account,
    login_cloud,
    login_cloud_workbuddy,
    logout_cloud,
)
from octop.infra.errors import ErrorCode, OctopError


class _AccountRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handle = super().get_route_handler()

        async def sanitized(request: Request) -> Response:
            try:
                return await handle(request)
            except RequestValidationError:
                # Default validation errors echo the submitted input, including malformed passwords.
                raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS, status=422) from None

        return sanitized


router = APIRouter(prefix="/cloud", route_class=_AccountRoute)


class CloudLogin(BaseModel):
    account: str
    password: SecretStr


@router.get("/account", summary="Read my saved Lynxce Cloud identity")
async def status(user: Owner, services: Services) -> CloudAccountStatus:
    """Name and avatar of the signed-in Lynxce account (avatar read from Lynxce once if missing)."""
    return await cloud_account(services, user.id)


@router.post("/account", summary="Sign in to Lynxce Cloud with my existing account")
async def login(body: CloudLogin, user: Owner, services: Services) -> CloudAccountStatus:
    return await login_cloud(services, user.id, body.account, body.password.get_secret_value())


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
    body: WorkbuddyLogin, user: Owner, services: Services
) -> CloudAccountStatus:
    return await login_cloud_workbuddy(services, user.id, body.handoff_code.get_secret_value())


@router.delete("/account", summary="Sign out of Lynxce Cloud on this device")
async def logout(
    user: Owner, services: Services, expected_account_id: str | None = None
) -> CloudAccountStatus:
    return await logout_cloud(services, user.id, expected_account_id=expected_account_id)
