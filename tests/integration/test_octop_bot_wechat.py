"""Desktop WeChat flows isolate users, spend state once and hide upstream secrets."""

import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from octop.infra.auth import lynxce_cloud as cloud
from octop.infra.auth import lynxce_wechat as wechat
from octop.infra.server import OctopServer

API = "/api/octop-bot/account/wechat"
STATE = "test-state-" + "x" * 43
Env = tuple[httpx.AsyncClient, OctopServer, dict[str, str], dict[str, str]]


@pytest.fixture
def upstream(monkeypatch: pytest.MonkeyPatch) -> dict[str, bool]:
    new = {"bind": False}
    wechat._flows.clear()
    monkeypatch.setenv("OCTOP_DESKTOP_SHELL", "1")
    monkeypatch.setenv("OCTOP_DESKTOP_PRODUCT", "bot")

    def respond(req: httpx.Request) -> httpx.Response:
        assert req.headers["X-Lynxce-Client"] == "web"
        if req.url.path.startswith("/api/auth/wechat-web/"):
            assert "X-Lynxce-App" not in req.headers
            # New accounts made by login or bind record Octop Bot as their origin.
            signup = req.headers.get("X-Lynxce-Signup-Site")
            assert signup == (None if req.url.path.endswith("/config") else "octop-bot")
        if req.url.path.endswith("/config"):
            assert not req.url.query
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "enabled": True,
                        "appId": "test-app",
                        "redirectUri": "https://example.test/callback",
                        "state": STATE,
                    },
                },
            )
        if req.url.path.endswith("/login") and new["bind"]:
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "needBindPhone": True,
                        "bindToken": "test-bind-secret",
                        "profile": {"nickname": "Test"},
                    },
                },
            )
        if req.url.path.endswith("/bind-phone"):
            assert json.loads(req.content)["bindToken"] == "test-bind-secret"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "accessToken": "test-access-secret",
                    "refreshToken": "test-refresh-secret",
                    "user": {"id": "test-user", "nickname": "Test"},
                },
            },
        )

    monkeypatch.setattr(
        cloud, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond))
    )

    async def no_model(*args: object) -> bool:
        return False

    monkeypatch.setattr(
        "octop.api.routers.bot_cloud_account.account_models.adopt_cloud_account", no_model
    )
    return new


async def test_login_and_binding(env_admin_alice: Env, upstream: dict[str, bool]) -> None:
    client, server, _, alice = env_admin_alice
    start = (await client.post(API + "/start", headers=alice)).json()
    assert parse_qs(urlsplit(start["qr_url"]).query)["state"] == [STATE]
    body = {"flow_id": start["flow_id"], "code": "test-code-secret", "state": STATE}
    response = await client.post(API + "/finish", headers=alice, json=body)
    assert response.status_code == 200 and response.json()["connected"]
    assert "test-access-secret" not in response.text and "test-code-secret" not in response.text
    assert (await client.post(API + "/finish", headers=alice, json=body)).status_code >= 400
    upstream["bind"] = True
    start = (await client.post(API + "/start", headers=alice)).json()
    body["flow_id"] = start["flow_id"]
    response = await client.post(API + "/finish", headers=alice, json=body)
    assert response.json()["need_bind_phone"] and "test-bind-secret" not in response.text
    wechat._flows[start["flow_id"]].last_attempt -= 1
    response = await client.post(
        API + "/bind",
        headers=alice,
        json={"flow_id": start["flow_id"], "phone": "13800000000", "code": "123456"},
    )
    assert response.status_code == 200 and response.json()["connected"]
    assert server.services is not None
    assert cloud.cloud_status(server.services, server.user_manager.get("alice").id).connected


async def test_refusals(
    env_admin_alice: Env, upstream: dict[str, bool], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, admin, alice = env_admin_alice
    start = (await client.post(API + "/start", headers=alice)).json()
    flow = wechat._flows[start["flow_id"]]
    body = {"flow_id": start["flow_id"], "code": "test-code-secret", "state": "wrong"}
    assert (await client.post(API + "/finish", headers=admin, json=body)).status_code >= 400
    assert (await client.post(API + "/finish", headers=alice, json=body)).status_code >= 400
    assert (await client.post(API + "/finish", headers=alice, json=body)).status_code == 429
    for _ in range(4):
        flow.last_attempt -= 1
        assert (await client.post(API + "/finish", headers=alice, json=body)).status_code >= 400
    flow.last_attempt -= 1
    assert (await client.post(API + "/finish", headers=alice, json=body)).status_code == 429
    flow.expires = 0
    assert (await client.post(API + "/finish", headers=alice, json=body)).status_code >= 400
    ids = [(await client.post(API + "/start", headers=alice)).json()["flow_id"] for _ in range(4)]
    assert ids[0] not in wechat._flows
    monkeypatch.setenv("OCTOP_BOT_CLOUD", "1")
    for endpoint in ("/start", "/finish", "/bind"):
        assert (await client.post(API + endpoint, headers=alice, json=body)).status_code == 403
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=client._transport.app, client=("192.0.2.5", 1234)),
        base_url="http://test",
    ) as remote:
        monkeypatch.setenv("OCTOP_DESKTOP_SHELL", "1")
        monkeypatch.delenv("OCTOP_BOT_CLOUD")
        for endpoint in ("/start", "/finish", "/bind"):
            assert (await remote.post(API + endpoint, headers=alice, json=body)).status_code == 403
