"""The grant used by the cloud to bill a desktop computer while the desktop is offline."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from octop.infra.auth import lynxce_cloud, lynxce_compute
from octop.infra.errors import ErrorCode, OctopError
from tests.integration.test_octop_bot_cloud import (
    Upstream,
    _lynxce_jwt,
    _sign_in,
    upstream,  # noqa: F401
)
from tests.support.app import octop_client

LOGIN = "/api/auth/lynxce/token-login"
RESERVE = "/api/billing/octop-bot/compute/reserve"
ACCOUNT = "lx-13800000050"


class ServerExchange:
    def __init__(self, general_api: Upstream) -> None:
        self.upstream = general_api
        self.account = ACCOUNT
        self.reject_refresh = False
        self.refreshes = 0
        self.used_codes: set[str] = set()
        self.billing_tokens: list[str] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path not in {"/api/auth/login-codes/redeem", "/api/auth/login-codes/refresh", RESERVE}:
            return self.upstream(req)
        assert req.headers["X-Octop-Service-Key"] == "test-service"
        if path == RESERVE:
            self.billing_tokens.append(req.headers["Authorization"])
            return httpx.Response(200, json={"code": 0, "data": {"ok": True}})
        body = json.loads(req.content)
        if path.endswith("redeem"):
            assert body["scope"] == "server"
            if body["code"] in self.used_codes:
                return httpx.Response(400)
            self.used_codes.add(body["code"])
        else:
            assert body == {"refreshToken": f"rotation-{self.refreshes}"}
            if self.reject_refresh:
                return httpx.Response(401)
            self.refreshes += 1
        now = datetime.now(UTC)
        data = {
            "userId": self.account,
            "deviceId": "device",
            "accessToken": f"compute-{self.refreshes}",
            "refreshToken": f"rotation-{self.refreshes}",
            "expiresAt": (now + timedelta(hours=1)).isoformat(),
            "authorizationExpiresAt": (now + timedelta(days=30)).isoformat(),
        }
        return httpx.Response(200, json={"code": 0, "data": data})


@pytest.fixture
def exchange(upstream: Upstream, monkeypatch: pytest.MonkeyPatch) -> ServerExchange:  # noqa: F811
    from octop.api.routers import auth_lynxce

    monkeypatch.setattr(auth_lynxce, "_token_login_ips", {})
    monkeypatch.setattr(auth_lynxce, "_token_login_accounts", {})
    service = ServerExchange(upstream)
    monkeypatch.setenv("OCTOP_BOT_COMPUTE_SERVICE_KEY", "test-service")
    monkeypatch.setattr(
        lynxce_cloud, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(service))
    )
    return service


async def test_server_code_authorizes_only_this_users_computer_billing(
    tmp_octop_home: Path, exchange: ServerExchange
) -> None:
    async with octop_client(tmp_octop_home) as (client, srv):
        body = {"access_token": _lynxce_jwt(), "server_code": "single-use"}
        exchange.account = "different-account"
        assert (await client.post(LOGIN, json=body)).status_code == 403
        assert srv.user_manager.count() == 0
        exchange.account = ACCOUNT
        body["server_code"] = "fresh-code"
        result = await client.post(LOGIN, json=body)
        assert result.status_code == 200, result.text
        assert "compute-0" not in result.text and "rotation-0" not in result.text
        uid = result.json()["user"]["id"]
        assert (await client.post(LOGIN, json=body)).status_code == 409
        assert (await client.post(LOGIN, json={"access_token": _lynxce_jwt()})).status_code == 200
        services = srv.services
        assert not lynxce_cloud.cloud_status(services, uid).connected
        assert exchange.upstream.keys == []
        with pytest.raises(OctopError) as general:
            await lynxce_cloud.tenant_call(services, uid, "GET", "/api/user/personal-api-keys")
        assert general.value.code == ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED
        await lynxce_cloud.tenant_call(services, uid, "POST", RESERVE, {})
        assert exchange.billing_tokens == ["Bearer compute-0"]

        grant = lynxce_compute.load(services, uid)
        assert grant is not None
        lynxce_compute.save(services, uid, replace(grant, expires_at=0))
        await asyncio.gather(
            *(lynxce_cloud.tenant_call(services, uid, "POST", RESERVE, {}) for _ in range(2))
        )
        updated = lynxce_compute.load(services, uid)
        assert updated is not None and updated.authorized_until == grant.authorized_until
        assert updated.refresh_token == "rotation-1" and exchange.refreshes == 1
        assert exchange.billing_tokens[-2:] == ["Bearer compute-1"] * 2
        services.user_repo.delete(uid)
        assert lynxce_compute.load(services, uid) is None
        assert services.secret_repo.get(f"lynxce.compute.user.{uid}.fernet") is None


async def test_revoked_or_expired_compute_grant_cannot_fall_back_to_web_billing(
    tmp_octop_home: Path, exchange: ServerExchange
) -> None:
    async with octop_client(tmp_octop_home) as (client, srv):
        signed = await _sign_in(client, "13800000050")
        uid = signed["user"]["id"]
        res = await client.post(LOGIN, json={"access_token": _lynxce_jwt(), "server_code": "code"})
        assert res.status_code == 200
        grant = lynxce_compute.load(srv.services, uid)
        assert grant is not None
        assert lynxce_cloud.cloud_status(srv.services, uid).connected
        exchange.reject_refresh = True
        lynxce_compute.save(srv.services, uid, replace(grant, expires_at=0))
        with pytest.raises(OctopError) as revoked:
            await lynxce_cloud.tenant_call(srv.services, uid, "POST", RESERVE, {})
        assert revoked.value.code == ErrorCode.BOT_CLOUD_SESSION_REQUIRED
        assert (await client.post(LOGIN, json={"access_token": _lynxce_jwt()})).status_code == 409

        lynxce_compute.save(srv.services, uid, replace(grant, authorized_until=0))
        with pytest.raises(OctopError) as expired:
            await lynxce_cloud.tenant_call(srv.services, uid, "POST", RESERVE, {})
        assert expired.value.code == ErrorCode.BOT_CLOUD_SESSION_REQUIRED
        assert (await client.post(LOGIN, json={"access_token": _lynxce_jwt()})).status_code == 409
        assert exchange.billing_tokens == []


async def test_cooling_off_reauthorization_survives_restart(
    tmp_octop_home: Path, exchange: ServerExchange
) -> None:
    phone = ACCOUNT.removeprefix("lx-")
    body = {"access_token": _lynxce_jwt(), "server_code": "original"}
    async with octop_client(tmp_octop_home) as (client, server):
        signed = await _sign_in(client, phone)
        uid = signed["user"]["id"]
        storage = f"lynxce.compute.user.{uid}"
        response = await client.post(LOGIN, json=body)
        assert response.status_code == 200 and response.json()["user"]["id"] == uid
        first_key = server.services.secret_repo.get(storage + ".fernet")
        assert first_key
        auth = {"Authorization": f"Bearer {signed['access_token']}"}
        assert (await client.post("/api/octop-bot/account/delete", headers=auth)).status_code == 200
        assert server.services.user_repo.get(uid).disabled
        assert server.services.secret_repo.get(storage) is None
        assert server.services.secret_repo.get(storage + ".fernet") is None

        assert (await _sign_in(client, phone))["user"]["id"] == uid
        body["server_code"] = "new-device-consent"
        assert (await client.post(LOGIN, json=body)).status_code == 200
        new_key = server.services.secret_repo.get(storage + ".fernet")
        assert new_key and new_key != first_key

    async with octop_client(tmp_octop_home) as (client, restarted):
        assert (await client.post(LOGIN, json={"access_token": _lynxce_jwt()})).status_code == 200
        grant = lynxce_compute.load(restarted.services, uid)
        assert grant is not None
        lynxce_compute.save(restarted.services, uid, replace(grant, expires_at=0))
        await lynxce_cloud.tenant_call(restarted.services, uid, "POST", RESERVE, {})
        assert exchange.refreshes == 1 and exchange.billing_tokens == ["Bearer compute-1"]
        restarted.services.user_repo.delete(uid)
        assert restarted.services.secret_repo.get(storage) is None
        assert restarted.services.secret_repo.get(storage + ".fernet") is None


async def test_withdrawal_waits_for_a_refresh_and_late_rebind_cannot_restore_disabled_user(
    tmp_octop_home: Path, exchange: ServerExchange, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with octop_client(tmp_octop_home) as (client, srv):
        response = await client.post(
            LOGIN, json={"access_token": _lynxce_jwt(), "server_code": "a"}
        )
        assert response.status_code == 200, response.text
        uid = response.json()["user"]["id"]
        services = srv.services
        grant = lynxce_compute.load(services, uid)
        assert grant is not None
        lynxce_compute.save(services, uid, replace(grant, expires_at=0))
        started, finish = asyncio.Event(), asyncio.Event()
        original = lynxce_cloud._server_exchange

        async def delayed(path, body):
            started.set()
            await finish.wait()
            return await original(path, body)

        monkeypatch.setattr(lynxce_cloud, "_server_exchange", delayed)
        refresh = asyncio.create_task(
            lynxce_cloud.computer_billing_connected(services, uid, ACCOUNT)
        )
        await asyncio.wait_for(started.wait(), 2)
        await srv.user_manager.disable(services.user_repo.get(uid).username)
        withdrawal = asyncio.create_task(lynxce_cloud.forget_account_grants(services, uid))
        await asyncio.sleep(0)
        assert not withdrawal.done()
        finish.set()
        with pytest.raises(OctopError):
            await refresh
        await withdrawal
        with pytest.raises(OctopError):
            await lynxce_cloud.keep_compute_grant(services, uid, grant)
        assert lynxce_compute.load(services, uid) is None
        assert services.secret_repo.get(f"lynxce.compute.user.{uid}.fernet") is None


@pytest.mark.parametrize(
    "failure",
    [
        "refresh",
        "disk-generic",
        "disk-unrelated",
        "disk-missing-code",
        "disk-confirmed",
        "after-refresh",
    ],
)
async def test_scoped_disk_receipt_is_distinct_from_a_payment_status_during_refresh(
    tmp_octop_home: Path, exchange: ServerExchange, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from octop.infra.cloud.computers import DiskBalanceInsufficient

    disk = "/api/billing/octop-bot/compute/disk/charge"
    balance = {"code": 40204, "error": {"code": "insufficient_balance"}}
    async with octop_client(tmp_octop_home) as (client, srv):
        result = await client.post(
            LOGIN, json={"access_token": _lynxce_jwt(), "server_code": "consent"}
        )
        assert result.status_code == 200
        uid = result.json()["user"]["id"]
        calls = []

        def handler(req: httpx.Request) -> httpx.Response:
            path = req.url.path
            calls.append(path)
            if path == disk:
                if failure == "disk-missing-code":
                    return httpx.Response(402, json={"error": {"code": "insufficient_balance"}})
                if calls.count(disk) == 1 and failure in {"refresh", "after-refresh"}:
                    return httpx.Response(401)
                body = (
                    balance
                    if failure in {"disk-confirmed", "after-refresh"}
                    else (
                        {} if failure == "disk-generic" else {"error": {"code": "grant_required"}}
                    )
                )
                return httpx.Response(402, json=body)
            if path == "/api/auth/login-codes/refresh" and failure == "refresh":
                return httpx.Response(402, json=balance)
            return exchange(req)

        monkeypatch.setattr(
            lynxce_cloud,
            "_client",
            lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        with pytest.raises(OctopError) as error:
            await lynxce_cloud.tenant_call(
                srv.services,
                uid,
                "POST",
                disk,
                {"computerId": "own", "day": "2026-11-25", "sizeGb": 3},
            )
        confirmed = failure in {"disk-confirmed", "after-refresh"}
        assert isinstance(error.value, DiskBalanceInsufficient) == confirmed
        assert (error.value.code == ErrorCode.BOT_CLOUD_CREDITS_REQUIRED) == confirmed
        assert calls.count(disk) == (2 if failure == "after-refresh" else 1)
        assert ("/api/auth/login-codes/refresh" in calls) == (
            failure in {"refresh", "after-refresh"}
        )
