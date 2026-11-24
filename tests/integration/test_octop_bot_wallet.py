"""Balances and checkout tickets stay with the account the user is looking at."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from octop.infra.agents.providers import lynxce as models
from octop.infra.auth import lynxce_cloud, lynxce_wallet
from octop.infra.auth.lynxce import _grants
from octop.infra.db.services import SharedServices
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.server import OctopServer

API = "/api/octop-bot/wallet"
CLOUD = "/api/octop-bot/cloud/account"
PORTAL = "https://admin.lynxce.cn/recharge?token="
MODEL_TICKET = "mcrt1." + "b" * 170
Env = tuple[httpx.AsyncClient, OctopServer, dict[str, str], dict[str, str]]


def expires() -> str:
    return (datetime.now(UTC) + timedelta(minutes=15)).isoformat()


def token(label: str) -> str:
    return label + "." + "a" * 43


def connect_model(services: SharedServices, user_id: int, name: str, scope: str) -> str:
    grant = _grants.grant_from_tokens(
        {
            "scope": scope,
            "token_type": "bearer",
            "expires_in": 3600,
            "access_token": name,
            "refresh_token": name + "-refresh",
        },
        "test-octop-bot",
    )
    _grants.save(services, user_id, grant)
    return str(grant["connection_id"])


async def test_cloud_checkout_only_mints_for_displayed_wallet(
    env_admin_alice: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOP_DESKTOP_SHELL", "1")
    monkeypatch.setenv("OCTOP_DESKTOP_PRODUCT", "bot")
    client, _, admin, alice = env_admin_alice
    minted: list[str] = []

    def upstream(req: httpx.Request) -> httpx.Response:
        assert str(req.url).startswith("https://api.lynxce.cn/") and not req.url.query
        account = req.headers.get("Authorization", "").removeprefix("Bearer secret-")
        if req.url.path == "/api/auth/password-login":
            name = json.loads(req.content)["account"]
            data = {
                "accessToken": "secret-" + name,
                "refreshToken": "refresh-" + name,
                "user": {"id": name},
            }
        elif req.url.path == "/api/user/quota":
            data = {"creditsRemaining": -1.25, "effectiveCreditsRemaining": 0}
        elif req.url.path == "/api/user/personal-api-keys":  # desktop sign-in's chat key
            data = {"id": "key-" + account, "secret": "sk-" + account}
        else:
            assert req.url.path == "/api/billing/recharge/checkout-link" and req.method == "POST"
            assert not req.content
            minted.append(account)
            data = {"url": PORTAL + token(account), "token": token(account), "expiresAt": expires()}
        return httpx.Response(200, json={"code": 0, "data": data})

    monkeypatch.setattr(
        lynxce_cloud, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    )
    assert (await client.get(API, params={"source": "cloud"})).status_code == 401
    for owner, account in [(admin, "first"), (alice, "second")]:
        (
            await client.post(
                CLOUD, headers=owner, json={"account": account, "password": "test-only"}
            )
        ).raise_for_status()
    wallet = await client.get(API, params={"source": "cloud"}, headers=admin)
    assert wallet.json() == {
        "source": "cloud",
        "account_id": "first",
        "credits": -1.25,
        "status": "available",
        "connection_id": None,
        "recharge_mode": "ticket",
    }
    assert "no-store" in wallet.headers["cache-control"]
    body = {"source": "cloud", "expected_account_id": "first"}
    good = await client.post(API + "/recharge", headers=admin, json=body)
    assert "no-store" in good.headers["cache-control"]
    assert good.json()["url"] == PORTAL + token("first") and good.json()["expires_at"]
    assert (await client.post(API + "/recharge", headers=alice, json=body)).status_code == 403
    (
        await client.post(
            CLOUD, headers=admin, json={"account": "rebound", "password": "test-only"}
        )
    ).raise_for_status()
    assert (await client.post(API + "/recharge", headers=admin, json=body)).status_code == 403
    assert (
        await client.post(
            API + "/recharge",
            headers=admin,
            json={"source": "model", "expected_connection_id": "first"},
        )
    ).status_code == 403
    assert minted == ["first"]


async def test_model_wallet_checks_grant_scope_and_account_switches(
    env_admin_alice: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOP_DESKTOP_SHELL", "1")
    monkeypatch.setenv("OCTOP_DESKTOP_PRODUCT", "bot")
    client, server, admin, alice = env_admin_alice
    assert server.services
    services = server.services
    uid = server.user_manager.get("alice").id
    reads: list[str] = []
    minted: list[str] = []
    entered, release = asyncio.Event(), asyncio.Event()
    hold = deny = False

    async def account(req: web.Request) -> web.Response:
        reads.append(req.headers["Authorization"])
        return web.json_response({"object": "account", "balance": {"credits": 0}})

    async def checkout(req: web.Request) -> web.Response:
        assert not await req.read()
        bearer = req.headers["Authorization"]
        minted.append(bearer)
        if deny:
            return web.json_response({"error": {"code": "insufficient_scope"}}, status=403)
        if hold:
            entered.set()
            await release.wait()
        return web.json_response(
            {
                "object": "account.recharge_link",
                "url": PORTAL + MODEL_TICKET,
                "expires_at": expires(),
            }
        )

    provider = web.Application()
    provider.router.add_get("/v1/account", account)
    provider.router.add_post("/v1/account/recharge-link", checkout)
    async with TestServer(provider) as fake:
        monkeypatch.setattr(models, "BASE_URL", str(fake.make_url("/v1")))
        legacy = connect_model(services, uid, "key-old", "chat")
        wallet = await client.get(API, params={"source": "model"}, headers=alice)
        assert (
            wallet.json()["credits"] == 0
            and wallet.json()["connection_id"] == legacy
            and wallet.json()["account_id"] is None
        )
        body = {"source": "model", "expected_connection_id": legacy}
        old = await client.post(API + "/recharge", headers=alice, json=body)
        assert (
            old.status_code == 403
            and old.json()["error"]["code"] == "BOT_LYNXCE_RECHARGE_AUTH_REQUIRED"
        )
        assert minted == [] and reads == ["Bearer key-old"]
        grant = connect_model(services, uid, "key-new", "chat recharge")
        assert (await client.post(API + "/recharge", headers=alice, json=body)).status_code == 403
        body["expected_connection_id"] = grant
        assert (await client.post(API + "/recharge", headers=admin, json=body)).status_code == 403
        good = await client.post(API + "/recharge", headers=alice, json=body)
        assert good.json()["url"] == PORTAL + MODEL_TICKET
        deny = True
        denied = await client.post(API + "/recharge", headers=alice, json=body)
        assert denied.json()["error"]["code"] == "BOT_LYNXCE_RECHARGE_AUTH_REQUIRED"
        deny, hold = False, True
        pending = asyncio.create_task(client.post(API + "/recharge", headers=alice, json=body))
        try:
            await asyncio.wait_for(entered.wait(), 10)
            connect_model(services, uid, "different-account", "chat recharge")
        finally:
            release.set()
        stale = await pending
        assert stale.status_code == 403 and "url" not in stale.text
        assert minted == ["Bearer key-new"] * 3


@pytest.mark.parametrize(
    "url",
    [
        "https://elsewhere.invalid/recharge?token=" + token("test"),
        "https://admin.lynxce.cn@elsewhere.invalid/recharge?token=" + token("test"),
        PORTAL + token("test") + "&next=offsite",
        PORTAL + token("test") + "#fragment",
        PORTAL + "an-access-token",
        PORTAL + "header.payload.signature",
        PORTAL + "mcrt1." + "a" * 43,
        "https://admin.lynxce.cn/recharge",
    ],
)
def test_checkout_rejects_unexpected_destinations_and_credentials(url: str) -> None:
    with pytest.raises(OctopError) as caught:
        lynxce_wallet._checkout({"url": url, "expiresAt": expires()}, "cloud")
    assert caught.value.code == ErrorCode.NETWORK_ERROR and url not in str(caught.value)


def test_checkout_rejects_expired_and_long_lived_links() -> None:
    for minutes in (-1, 30):
        with pytest.raises(OctopError):
            lynxce_wallet._checkout(
                {
                    "url": PORTAL + token("test"),
                    "expiresAt": (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat(),
                },
                "cloud",
            )


def test_model_checkout_cannot_return_a_full_cloud_checkout_ticket() -> None:
    with pytest.raises(OctopError):
        lynxce_wallet._checkout({"url": PORTAL + token("cloud"), "expires_at": expires()}, "model")
