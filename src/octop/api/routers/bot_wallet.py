"""The current user's Lynxce credits and account-bound hosted recharge link."""

from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from octop.api.common.bot_desktop import AccountServices, Owner
from octop.infra.auth import lynxce_cloud
from octop.infra.auth import lynxce_wallet as wallet
from octop.infra.desktop import bot_cloud_enabled
from octop.infra.errors import ErrorCode, OctopError

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
    source: wallet.WalletSource, response: Response, user: Owner, services: AccountServices
) -> wallet.WalletBalance:
    response.headers["Cache-Control"] = "private, no-store"
    return await wallet.balance(services, user.id, source)


@router.post("/recharge", summary="Open a short-lived Lynxce checkout for the displayed account")
async def recharge(
    body: CheckoutRequest, response: Response, user: Owner, services: AccountServices
) -> wallet.CheckoutLink:
    response.headers["Cache-Control"] = "private, no-store"
    return await wallet.recharge(
        services, user.id, body.source, body.expected_account_id, body.expected_connection_id
    )


def _require_cloud() -> None:
    if not bot_cloud_enabled():
        raise OctopError.localized(ErrorCode.NOT_FOUND)


class ApplePurchaseIntentRequest(BaseModel):
    package_id: str = Field(min_length=1, max_length=128, description="Lynxce credit pack id.")


class AppleTransactionRequest(BaseModel):
    signed_transaction: str = Field(
        min_length=1, max_length=64 * 1024, description="StoreKit 2 JWS of the purchase."
    )


@router.get(
    "/packs",
    summary="Credit packs sold in the iOS app (Octop Bot cloud)",
    description="Lynxce's recharge-packages response for Octop Bot's App Store products, "
    "fetched with the signed-in tenant's Lynxce session.",
)
async def credit_packs(response: Response, user: Owner, services: AccountServices) -> Any:
    _require_cloud()
    response.headers["Cache-Control"] = "private, no-store"
    return await lynxce_cloud.tenant_call(
        services, user.id, "GET", "/api/billing/app/recharge-packages"
    )


@router.post(
    "/apple/intent",
    summary="Start an App Store credit pack purchase (Octop Bot cloud)",
    description="Returns Lynxce's {productId, appAccountToken} for StoreKit.",
)
async def apple_intent(
    body: ApplePurchaseIntentRequest, user: Owner, services: AccountServices
) -> Any:
    _require_cloud()
    return await lynxce_cloud.tenant_call(
        services,
        user.id,
        "POST",
        "/api/billing/apple/purchase-intents",
        {"packageId": body.package_id},
    )


@router.post(
    "/apple/transaction",
    summary="Report an App Store transaction for crediting (Octop Bot cloud)",
    description="Lynxce verifies the JWS with Apple and credits the wallet once.",
)
async def apple_transaction(
    body: AppleTransactionRequest, user: Owner, services: AccountServices
) -> Any:
    _require_cloud()
    return await lynxce_cloud.tenant_call(
        services,
        user.id,
        "POST",
        "/api/billing/apple/transactions",
        {"signedTransaction": body.signed_transaction},
    )
