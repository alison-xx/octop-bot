"""Browser grants are exchanged for a normal cloud tenant's Bot session."""

import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from octop.infra.auth import lynxce_cloud
from octop.infra.cloud.bot_cloud import accounts

BASE = "/api/auth/lynxce/web-login"
SITE = "octop-bot-cloud"


@pytest.mark.parametrize("provider", ["wechat", "workbuddy"])
async def test_cloud_browser_sign_in(env_admin_alice, monkeypatch, provider):
    client, server, _, _ = env_admin_alice
    monkeypatch.setenv("OCTOP_BOT_CLOUD", "1")
    expected = (
        "/api/auth/wechat-web/cloud-login"
        if provider == "wechat"
        else "/api/oauth/workbuddy/cloud-session"
    )
    spent = False

    def upstream(req):
        nonlocal spent
        assert req.headers["X-Lynxce-App"] == "octopbot"
        if req.url.path.endswith("/config"):
            assert req.url.params["site"] == SITE
            data = {
                "enabled": True,
                "site": SITE,
                "callbackUrl": "https://bot.lynxce.cn/login",
                "state": "wechat-test-state",
                "browserState": "tab-only-proof",
                "appId": "test",
                "redirectUri": "https://api.lynxce.cn/api/auth/wechat-web/cloud-relay",
            }
        elif req.url.path == expected:
            body = json.loads(req.content)
            assert body["site"] == SITE and body["code"] == "test-code"
            assert body["state" if provider == "wechat" else "clientState"] == state
            if spent:
                return httpx.Response(401)
            spent = True
            data = (
                {"needBindPhone": True, "bindToken": "test-bind"} if provider == "wechat" else grant
            )
        else:
            assert req.url.path == "/api/auth/wechat-web/cloud-bind-phone"
            assert json.loads(req.content) == {
                "phone": "13800000000",
                "code": "123456",
                "bindToken": "test-bind",
                "site": SITE,
            }
            data = grant
        return httpx.Response(200, json={"code": 0, "data": data})

    grant = {
        "accessToken": "test-lynxce-access",
        "refreshToken": "test-lynxce-refresh",
        "user": {"id": "cloud-subject", "nickname": "Cloud tester"},
    }
    monkeypatch.setattr(
        lynxce_cloud, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    )

    async def noop(*args, **kwargs):
        pass

    monkeypatch.setattr(accounts, "ensure_model_key", noop)
    monkeypatch.setattr(accounts, "ensure_media_scopes", noop)
    start = await client.get(BASE + "/config", params={"provider": provider})
    assert start.status_code == 200 and start.headers["cache-control"] == "no-store"
    config = start.json()
    assert config["enabled"]
    state = config["state"]
    params = parse_qs(urlsplit(config["url"]).query)
    if provider == "wechat":
        assert params["state"] == ["wechat-test-state"]
        assert state == "tab-only-proof"
        assert state not in config["url"]
    else:
        assert params["clientState"] == [state]
    body = {"provider": provider, "code": "test-code", "state": state, "locale": "en"}
    result = await client.post(BASE + "/exchange", json=body)
    assert result.status_code == 200, result.text
    if provider == "wechat":
        assert result.json() == {"bind_token": "test-bind"}
        result = await client.post(
            BASE + "/bind",
            json={
                "bind_token": "test-bind",
                "phone": "13800000000",
                "code": "123456",
                "locale": "en",
            },
        )
    assert result.status_code == 200, result.text
    assert "test-lynxce" not in result.text
    assert set(result.json()) == {"access_token"}
    me = await client.get(
        "/api/auth/me", headers={"Authorization": "Bearer " + result.json()["access_token"]}
    )
    assert me.status_code == 200 and me.json()["role"] != "admin"
    assert lynxce_cloud.cloud_status(server.services, me.json()["id"]).account_id == "cloud-subject"
    assert (await client.post(BASE + "/exchange", json=body)).status_code >= 400


async def test_availability(env_admin_alice, monkeypatch):
    client, _, _, _ = env_admin_alice
    r = await client.get(BASE + "/config", params={"provider": "wechat"})
    assert r.status_code == 403
    monkeypatch.setenv("OCTOP_BOT_CLOUD", "1")

    async def old_config(*args, **kwargs):
        return {"enabled": True}

    monkeypatch.setattr(lynxce_cloud, "_send", old_config)
    for provider in ["wechat", "workbuddy"]:
        result = await client.get(BASE + "/config", params={"provider": provider})
        assert result.json() == {"enabled": False, "state": "", "url": ""}
