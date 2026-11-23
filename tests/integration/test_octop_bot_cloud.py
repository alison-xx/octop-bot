"""Octop Bot cloud (OCTOP_BOT_CLOUD): every Lynxce account gets its own account and model key."""

import json
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import pytest

from octop.api.routers import auth_lynxce
from octop.infra.agents.providers.lynxce import GATEWAY_URL, CloudAccountModel, account_selection
from octop.infra.auth import lynxce_cloud as cloud
from octop.infra.cloud.bot_cloud import accounts
from octop.infra.cloud.bot_cloud import files as cloud_files
from tests.support.app import octop_client

CODE_LOGIN = "/api/auth/lynxce/code-login"
STATUS = "/api/auth/lynxce/status"
INFO = "/api/octop-bot/server-info"


class Upstream:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.keys: list[dict[str, Any]] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        assert req.url.host == "api.lynxce.cn" and req.url.scheme == "https"
        assert req.headers["X-Lynxce-Client"] == "web"
        path = req.url.path
        self.counts[path] += 1
        if path == "/api/auth/phone-login":
            payload = json.loads(req.content)
            if payload["code"] != "123456":
                return httpx.Response(401, json={"message": "bad code"})
            uid = payload["phone"]
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "accessToken": f"access-{uid}",
                        "refreshToken": f"refresh-{uid}",
                        "user": {"id": "lx-" + uid, "displayName": "User " + uid},
                    },
                },
            )
        if path == "/api/user/personal-api-keys":
            assert req.headers["Authorization"].startswith("Bearer access-")
            body = json.loads(req.content)
            self.keys.append(body)
            n = len(self.keys)
            return httpx.Response(
                200, json={"code": 0, "data": {"id": f"key-{n}", "secret": f"sk-test-{n}"}}
            )
        if path == "/api/auth/logout":
            return httpx.Response(200, json={"code": 0, "data": {}})
        if path == "/api/billing/app/recharge-packages":
            assert req.headers["X-Lynxce-Iap-App"] == "cn.lynxce.octopbot"
            return httpx.Response(
                200,
                json={"code": 0, "data": {"packages": [], "payment": {"apple": {"enabled": True}}}},
            )
        if path == "/api/billing/apple/purchase-intents":
            assert req.headers["X-Lynxce-Iap-App"] == "cn.lynxce.octopbot"
            assert json.loads(req.content) == {"packageId": "pack-1"}
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "productId": "cn.lynxce.octopbot.credits.1000",
                        "appAccountToken": "00000000-0000-0000-0000-000000000001",
                    },
                },
            )
        if path == "/api/user/account/deletion-request":
            assert json.loads(req.content) == {"confirm": "注销账号"}
            return httpx.Response(
                200, json={"code": 0, "data": {"status": "deactivated", "coolingDays": 7}}
            )
        return httpx.Response(404, json={})


@pytest.fixture
def upstream(monkeypatch: pytest.MonkeyPatch) -> Upstream:
    fake = Upstream()
    monkeypatch.setenv("OCTOP_BOT_CLOUD", "1")
    monkeypatch.setenv("OCTOP_FILE_STORE_BUCKET", "octop-bot-test")
    monkeypatch.setenv("OCTOP_FILE_STORE_ACCESS_KEY_ID", "AKID")
    monkeypatch.setenv("OCTOP_FILE_STORE_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("OCTOP_FILE_STORE_ENDPOINT", "http://127.0.0.1:9")
    monkeypatch.delenv("OCTOP_BOT_WEB", raising=False)
    monkeypatch.setattr(
        cloud, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake))
    )
    monkeypatch.setattr(auth_lynxce, "_failures", {})
    return fake


async def _sign_in(client: httpx.AsyncClient, phone: str) -> dict[str, Any]:
    res = await client.post(CODE_LOGIN, json={"target": phone, "code": "123456"})
    assert res.status_code == 200, res.text
    body: dict[str, Any] = res.json()
    return body


async def test_each_lynxce_account_gets_its_own_tenant(
    tmp_octop_home: Path, upstream: Upstream
) -> None:
    async with octop_client(tmp_octop_home) as (client, srv):
        assert (await client.get(STATUS)).json() == {
            "enabled": True,
            "claimed": False,
            "cloud": True,
        }
        info = (await client.get(INFO)).json()
        assert info["edition"] == "cloud"
        assert info["sign_in"] == ["lynxce"]
        assert info["setup_required"] is False
        assert info["capabilities"]["wallet"] is True
        assert info["capabilities"]["file_store"] == "object"

        alice = await _sign_in(client, "13800000001")
        bob = await _sign_in(client, "13800000002")
        assert alice["user"]["role"] == "user"
        assert alice["user"]["id"] != bob["user"]["id"]

        # Signing in again finds the same tenant and keeps its model key.
        again = await _sign_in(client, "13800000001")
        assert again["user"]["id"] == alice["user"]["id"]
        assert [k["name"] for k in upstream.keys] == [accounts.KEY_NAME, accounts.KEY_NAME]
        assert upstream.keys[0]["scopes"] == ["model:chat"]
        # The replaced session is closed upstream.
        assert upstream.counts["/api/auth/logout"] == 1

        uid = alice["user"]["id"]
        key = accounts.load_model_key(srv.services, uid)
        assert key is not None and key.secret == "sk-test-1"
        assert cloud.cloud_status(srv.services, uid).account_id == "lx-13800000001"

        # The tenant's chats use their own key on the Lynxce open gateway.
        selected = account_selection(srv.services, uid)
        assert isinstance(selected, CloudAccountModel)
        assert selected.model_id == accounts.DEFAULT_MODEL
        provider = selected.provider(srv.services)
        assert provider.base_url == GATEWAY_URL
        assert await provider.api_key() == "sk-test-1"  # type: ignore[operator]


async def test_tenants_cannot_reach_the_host(tmp_octop_home: Path, upstream: Upstream) -> None:
    async with octop_client(tmp_octop_home) as (client, _srv):
        token = (await _sign_in(client, "13800000003"))["access_token"]
        auth = {"Authorization": f"Bearer {token}"}
        fs = await client.get("/api/filesystem/roots", headers=auth)
        assert fs.status_code == 403
        mcp = await client.put("/api/connectors/custom-mcp", headers=auth, json={"servers": {}})
        assert mcp.status_code == 403


async def test_a_tenants_agent_is_pinned_to_its_object_store_prefix(
    tmp_octop_home: Path, upstream: Upstream
) -> None:
    from octop.infra.agents.manager import AgentCreateSpec

    async with octop_client(tmp_octop_home) as (client, srv):
        uid = (await _sign_in(client, "13800000004"))["user"]["id"]
        row = await srv.app_runtime.agent_registry.create(
            AgentCreateSpec(
                user_id=uid,
                name="Writer",
                config={"backend": {"type": "local_shell", "root_dir": "/"}},
            ),
            defer_bootstrap=True,
        )
        config = json.loads(row.config_json)
        assert config["backend"] == cloud_files.agent_backend(uid, row.agent_id)
        await srv.app_runtime.agent_registry.update_config_json(
            row.agent_id, json.dumps({**config, "backend": {"type": "local_shell"}})
        )
        stored = json.loads(srv.services.agent_repo.get(row.agent_id).config_json)
        assert stored["backend"] == cloud_files.agent_backend(uid, row.agent_id)


async def test_tenants_buy_credits_and_delete_their_account_through_the_server(
    tmp_octop_home: Path, upstream: Upstream
) -> None:
    async with octop_client(tmp_octop_home) as (client, srv):
        signed = await _sign_in(client, "13800000005")
        assert signed["cloud"] is True
        assert (await client.get("/api/setup/status")).json()["lynxce_login"] is True
        auth = {"Authorization": f"Bearer {signed['access_token']}"}
        packs = await client.get("/api/octop-bot/wallet/packs", headers=auth)
        assert packs.status_code == 200 and packs.json()["payment"]["apple"]["enabled"] is True
        intent = await client.post(
            "/api/octop-bot/wallet/apple/intent", headers=auth, json={"package_id": "pack-1"}
        )
        assert intent.json()["productId"] == "cn.lynxce.octopbot.credits.1000"

        uid = signed["user"]["id"]
        gone = await client.post("/api/octop-bot/account/delete", headers=auth)
        assert gone.status_code == 200 and gone.json() == {"cooling_days": 7}
        assert srv.services.user_repo.get(uid).disabled
        assert accounts.load_model_key(srv.services, uid) is None
        assert cloud.cloud_status(srv.services, uid).connected is False


async def test_review_fixes_locale_probe_policy_and_im_billing(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from octop.infra.users.resource_policy import backend_policy_types_in

    assert backend_policy_types_in(
        cloud_files.agent_backend(1, "abc"), named_kind=lambda _: None
    ) == {"s3"}
    async with octop_client(tmp_octop_home) as (client, srv):
        # A new tenant starts in the language of their first sign-in, then keeps it.
        first = await client.post(
            CODE_LOGIN, json={"target": "13800000010", "code": "123456", "locale": "en"}
        )
        assert first.json()["user"]["locale"] == "en"
        again = await client.post(
            CODE_LOGIN, json={"target": "13800000010", "code": "123456", "locale": "zh"}
        )
        assert srv.services.user_repo.get(again.json()["user"]["id"]).locale == "en"

        auth = {"Authorization": f"Bearer {first.json()['access_token']}"}
        probe = await client.post(
            "/api/connectors/custom-mcp/test",
            headers=auth,
            json={"server": {"transport": "stdio", "command": "touch", "args": ["/tmp/x"]}},
        )
        assert probe.status_code == 403

        # IM threads of a tenant's Bot bill the tenant too.
        uid = first.json()["user"]["id"]
        registry = srv.app_runtime.agent_registry
        from octop.infra.agents.manager import AgentCreateSpec

        row = await registry.create(AgentCreateSpec(user_id=uid, name="Desk"), defer_bootstrap=True)
        thread = SimpleNamespace(channel_type="telegram", user_id=uid, agent_id=row.agent_id)
        monkeypatch.setattr(registry._repos.thread_repo, "get", lambda _id: thread)
        selected = registry._account_for_bot_turn(row.agent_id, "t1", {"user": "tg:42"})
        assert selected is not None and selected.user_id == uid
