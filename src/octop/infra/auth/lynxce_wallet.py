"""Read the connected account's wallet and hand off to Lynxce's hosted checkout."""

from __future__ import annotations

import asyncio
import math
import re
import threading
import time
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel

from octop.infra.agents.providers.lynxce import personal_gateway
from octop.infra.auth import lynxce, lynxce_cloud
from octop.infra.auth.lynxce._grants import auth_required
from octop.infra.db.services import SharedServices
from octop.infra.errors import ErrorCode, OctopError

WalletSource = Literal["cloud", "model"]
_PORTAL = "https://admin.lynxce.cn/recharge?token="
_TICKETS = {
    "cloud": re.compile(r"(?!mcrt1\.)[A-Za-z0-9_-]{1,4096}\.[A-Za-z0-9_-]{43}"),
    "model": re.compile(r"mcrt1\.[A-Za-z0-9_-]{40,4090}"),
}


class WalletBalance(BaseModel):
    source: WalletSource
    account_id: str | None = None
    connection_id: str | None = None
    credits: float
    status: Literal["available"] = "available"
    recharge_mode: Literal["ticket"] = "ticket"


class CheckoutLink(BaseModel):
    url: str
    expires_at: datetime


def _credits(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OctopError.localized(ErrorCode.NETWORK_ERROR)
    try:
        if math.isfinite(value):
            return float(value)
    except OverflowError:
        pass
    raise OctopError.localized(ErrorCode.NETWORK_ERROR)


def _checkout(data: object, source: WalletSource) -> CheckoutLink:
    if not isinstance(data, dict):
        raise OctopError.localized(ErrorCode.NETWORK_ERROR)
    url, deadline = data.get("url"), data.get("expiresAt" if source == "cloud" else "expires_at")
    if not isinstance(url, str) or not url.startswith(_PORTAL) or not isinstance(deadline, str):
        raise OctopError.localized(ErrorCode.NETWORK_ERROR)
    ticket = url[len(_PORTAL) :]
    if not _TICKETS[source].fullmatch(ticket) or data.get("token", ticket) != ticket:
        raise OctopError.localized(ErrorCode.NETWORK_ERROR)
    try:
        expires_at = datetime.fromisoformat(deadline)
        remaining = expires_at - datetime.now(UTC)
    except (ValueError, TypeError, OverflowError):
        raise OctopError.localized(ErrorCode.NETWORK_ERROR) from None
    # The official checkout ticket lasts 15 minutes. Allow for clock skew.
    if not timedelta(0) < remaining <= timedelta(minutes=16):
        raise OctopError.localized(ErrorCode.NETWORK_ERROR)
    # Open on the credits tab. Lynxce's own query (the ticket) is kept byte for byte.
    parts = urlsplit(url)
    query = f"{parts.query}&tab=boost" if parts.query else "tab=boost"
    return CheckoutLink(url=urlunsplit(parts._replace(query=query)), expires_at=expires_at)


async def balance(services: SharedServices, user_id: int, source: WalletSource) -> WalletBalance:
    if source == "cloud":
        account = await asyncio.to_thread(lynxce_cloud.cloud_status, services, user_id)
        if not account.account_id:
            raise OctopError.localized(ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED)
        data = await lynxce_cloud.request_cloud(
            services, user_id, "GET", "/api/user/quota", expected_account_id=account.account_id
        )
        # effectiveCreditsRemaining may instead reflect an enterprise member's monthly limit.
        return WalletBalance(
            source=source,
            account_id=account.account_id,
            credits=_credits(data.get("creditsRemaining") if isinstance(data, dict) else None),
        )
    grant = await asyncio.to_thread(lynxce.connection_id, services, user_id)
    if not grant:
        raise auth_required()
    data = await personal_gateway(services, user_id, grant, "account")
    if grant != await asyncio.to_thread(lynxce.connection_id, services, user_id):
        raise auth_required()
    wallet = (
        data.get("balance") if isinstance(data, dict) and data.get("object") == "account" else None
    )
    return WalletBalance(
        source=source,
        connection_id=grant,
        credits=_credits(wallet.get("credits") if isinstance(wallet, dict) else None),
    )


# Each recharge has Lynxce sign a checkout ticket: at most this many per account per minute.
RECHARGE_LIMIT = 5
_RECHARGE_WINDOW = 60.0
_recharges: dict[int, deque[float]] = {}
_recharge_lock = threading.Lock()


def _limit_recharges(user_id: int) -> None:
    now = time.monotonic()
    with _recharge_lock:
        recent = _recharges.setdefault(user_id, deque())
        while recent and now - recent[0] >= _RECHARGE_WINDOW:
            recent.popleft()
        if len(recent) >= RECHARGE_LIMIT:
            raise OctopError.localized(ErrorCode.BOT_RECHARGE_RATE_LIMITED)
        recent.append(now)


async def recharge(
    services: SharedServices,
    user_id: int,
    source: WalletSource,
    expected_account_id: str | None,
    expected_connection_id: str | None,
    origin: str | None = None,
    intent: Literal["credits", "plan"] = "credits",
) -> CheckoutLink:
    if intent == "plan":
        raise OctopError.localized(ErrorCode.BOT_PLAN_UNAVAILABLE)
    _limit_recharges(user_id)
    if source == "cloud":
        if not expected_account_id or expected_connection_id is not None:
            raise OctopError.localized(ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED)
        data = await lynxce_cloud.request_cloud(
            services,
            user_id,
            "POST",
            lynxce_cloud.CHECKOUT_PATH,
            json=lynxce_cloud.checkout_body(origin),
            expected_account_id=expected_account_id,
        )
        return _checkout(data, source)
    if not expected_connection_id or expected_account_id is not None:
        raise auth_required()
    data = await personal_gateway(
        services, user_id, expected_connection_id, "account/recharge-link"
    )
    if expected_connection_id != await asyncio.to_thread(lynxce.connection_id, services, user_id):
        raise auth_required()
    if not isinstance(data, dict) or data.get("object") != "account.recharge_link":
        raise OctopError.localized(ErrorCode.NETWORK_ERROR)
    return _checkout(data, source)
