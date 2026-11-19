"""The current user's Lynxce credits and account-bound hosted recharge link."""

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from octop.api.common.bot_desktop import Owner, Services
from octop.infra.auth import lynxce_wallet as wallet

router = APIRouter(prefix="/wallet")


class CheckoutRequest(BaseModel):
    source: wallet.WalletSource
    expected_account_id: str | None = Field(
        default=None,
        max_length=256,
        description="Cloud user ID returned with the displayed balance.",
    )
    expected_connection_id: str | None = Field(
        default=None,
        max_length=256,
        description="Model connection ID returned with the displayed balance.",
    )


@router.get("", summary="Read the credit balance of my connected Lynxce account")
async def balance(
    source: wallet.WalletSource, response: Response, user: Owner, services: Services
) -> wallet.WalletBalance:
    response.headers["Cache-Control"] = "private, no-store"
    return await wallet.balance(services, user.id, source)


@router.post("/recharge", summary="Open a short-lived Lynxce checkout for the displayed account")
async def recharge(
    body: CheckoutRequest, response: Response, user: Owner, services: Services
) -> wallet.CheckoutLink:
    response.headers["Cache-Control"] = "private, no-store"
    return await wallet.recharge(
        services, user.id, body.source, body.expected_account_id, body.expected_connection_id
    )
