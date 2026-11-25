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
