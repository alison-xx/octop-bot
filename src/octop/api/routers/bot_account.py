"""Octop Bot cloud: delete the signed-in Lynxce account from inside the app."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from octop.api.deps import current_user, get_server
from octop.infra.cloud.bot_cloud import accounts
from octop.infra.desktop import bot_cloud_enabled
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import User

router = APIRouter(prefix="/account")


class AccountDeletion(BaseModel):
    cooling_days: int = Field(description="Days Lynxce waits before erasing the account.")


@router.post(
    "/delete",
    summary="Delete my Lynxce account (Octop Bot cloud)",
    response_model=AccountDeletion,
    description="Asks Lynxce to delete the account (signed out everywhere, erased after a "
    "cooling-off period) and disables this account on the server right away.",
)
async def delete_account(
    user: User = Depends(current_user), server: Any = Depends(get_server)
) -> AccountDeletion:
    if not bot_cloud_enabled() or user.is_admin:
        raise OctopError.localized(ErrorCode.FORBIDDEN)
    days = await accounts.delete_account(server.services, server.user_manager, user)
    return AccountDeletion(cooling_days=days)
