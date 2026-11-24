"""The native account routes authorize the current Octop user, including non-admins."""

from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import httpx
from aiohttp import web
from aiohttp.test_utils import TestServer

from octop.api.routers import bot_lynxce
from octop.infra.auth.lynxce import _provider
from tests.support.auth import auth_header, bootstrap_admin
from tests.support.http import chat_ws_path, ws_connect

API = "/api/octop-bot/lynxce"


async def test_connection_routes_belong_to_the_signed_in_desktop_user(env_admin_alice, monkeypatch):
    client, server, admin, alice = env_admin_alice
    monkeypatch.setenv("OCTOP_DESKTOP_SHELL", "1")
    monkeypatch.setenv("OCTOP_DESKTOP_PRODUCT", "bot")
    alice_id = server.user_manager.get("alice").id
    other_id = server.user_manager.get("admin").id
    disconnected = {"connected": False, "selected_model": None}
    assert (await client.get(f"{API}/status")).status_code == 401
    assert (await client.get(f"{API}/status", headers=alice)).json() == disconnected

    start = AsyncMock(return_value=("login-id", "https://api.lynxce.cn/api/oauth/mcp/authorize"))
    monkeypatch.setattr(bot_lynxce.account, "start_login", start)
    result = await client.post(f"{API}/login", headers=alice)
    result.raise_for_status()
    assert result.json() == {"attempt_id": "login-id", "authorization_url": start.return_value[1]}
    start.assert_awaited_once_with(server.services, alice_id)

    poll = AsyncMock(return_value=("failed", "access_denied"))
    monkeypatch.setattr(bot_lynxce.account, "poll_login", poll)
    response = await client.get(f"{API}/login/login-id", headers=alice)
    response.raise_for_status()
    assert response.json()["state"] == "failed"
    assert "拒绝" in response.json()["detail"]
    poll.assert_awaited_once_with(server.services, alice_id, "login-id")

    choose = AsyncMock(return_value="example-model")
    monkeypatch.setattr(bot_lynxce.models, "select_account_model", choose)
    selected = await client.put(f"{API}/model", json={"model_id": "example-model"}, headers=alice)
    selected.raise_for_status()
    assert selected.json() == {"connected": True, "selected_model": "example-model"}
    choose.assert_awaited_once_with(server.services, alice_id, "example-model")
    assert (await client.get(f"{API}/status", headers=admin)).json() == disconnected
    assert other_id != alice_id

    logout = AsyncMock()
    monkeypatch.setattr(bot_lynxce.account, "disconnect", logout)
    assert (await client.delete(f"{API}/session", headers=alice)).status_code == 204
    logout.assert_awaited_once_with(server.services, alice_id)


async def test_native_login_is_not_started_by_remote_dashboard(env, monkeypatch):
    client, _, auth = env
    monkeypatch.delenv("OCTOP_DESKTOP_SHELL", raising=False)
    assert (await client.post(f"{API}/login", headers=auth)).status_code == 403


async def test_first_model_connection_reaches_chief_through_the_personal_gateway(
    app_client, monkeypatch
):
    import json

    client, server, home = app_client
    monkeypatch.setenv("OCTOP_DESKTOP_SHELL", "1")
    monkeypatch.setenv("OCTOP_DESKTOP_PRODUCT", "bot")
    await bootstrap_admin(client, home)
    auth = await auth_header(client)
    workspace = await client.get("/api/octop-bot/workspace", headers=auth)
    workspace.raise_for_status()
    chief = workspace.json()["chief_id"]
    model_id = "tencent/personal-chat"
    calls = []

    async def register(request):
        assert (await request.json())["client_name"] == "Octop Bot"
        return web.json_response({"client_id": "desktop-test"}, status=201)

    async def token(request):
        form = await request.post()
        assert form["code"] == "test-code" and form["code_verifier"]
        return web.json_response(
            {
                "access_token": "fixture-access",
                "refresh_token": "fixture-refresh",
                "expires_in": 3600,
                "scope": "chat",
                "token_type": "Bearer",
            }
        )

    async def catalog(request):
        assert request.headers["Authorization"] == "Bearer fixture-access"
        return web.json_response(
            {"data": [{"id": "pictures", "modality": "image"}, {"id": model_id}]}
        )

    async def chat(request):
        body = await request.json()
        calls.append((request.headers.get("Authorization"), body["model"], body.get("tools")))
        common = {"id": "fixture-result", "created": 1, "model": model_id}
        answer = {"role": "assistant", "content": "personal gateway answered"}
        if not body.get("stream"):
            return web.json_response(
                {
                    **common,
                    "object": "chat.completion",
                    "choices": [{"index": 0, "message": answer, "finish_reason": "stop"}],
                }
            )
        chunks = [
            {"index": 0, "delta": answer, "finish_reason": None},
            {"index": 0, "delta": {}, "finish_reason": "stop"},
        ]
        data = "".join(
            "data: "
            + json.dumps({**common, "object": "chat.completion.chunk", "choices": [chunk]})
            + "\n\n"
            for chunk in chunks
        )
        return web.Response(text=data + "data: [DONE]\n\n", content_type="text/event-stream")

    gateway = web.Application()
    gateway.add_routes(
        [
            web.post("/register", register),
            web.post("/token", token),
            web.get("/models", catalog),
            web.post("/chat/completions", chat),
        ]
    )
    async with TestServer(gateway) as upstream:
        origin = str(upstream.make_url("/")).rstrip("/")
        monkeypatch.setattr(_provider, "ENDPOINT", origin)
        monkeypatch.setattr(bot_lynxce.models, "BASE_URL", origin)
        login = await client.post(f"{API}/login", headers=auth)
        login.raise_for_status()
        attempt = login.json()
        query = parse_qs(urlsplit(attempt["authorization_url"]).query)
        async with httpx.AsyncClient() as browser:
            callback = await browser.get(
                query["redirect_uri"][0], params={"state": query["state"][0], "code": "test-code"}
            )
            callback.raise_for_status()
        progress = await client.get(f"{API}/login/{attempt['attempt_id']}", headers=auth)
        assert progress.json()["state"] == "connected"
        assert (await client.get(f"{API}/models", headers=auth)).json()["models"] == [
            {"id": model_id, "name": model_id}
        ]
        chosen = await client.put(f"{API}/model", headers=auth, json={"model_id": model_id})
        chosen.raise_for_status()
        async with ws_connect(client._octop_app, chat_ws_path(chief, auth)) as ws:
            await ws.send_json({"type": "user_turn", "text": "hello", "bot_browser": True})
            frames = await ws.drain_turn(timeout=40)
        assert any("personal gateway answered" in str(f.get("content", "")) for f in frames), frames
        assert all(key == "Bearer fixture-access" and model == model_id for key, model, _ in calls)
        assert any(tools for _, _, tools in calls)
        calls.clear()
        job = await client.post(
            f"/api/agents/{chief}/cron",
            headers=auth,
            json={
                "name": "Morning briefing",
                "trigger": "interval:86400",
                "prompt": "Summarize the team's work",
                "task_type": "agent",
                "allow_all": False,
            },
        )
        job.raise_for_status()
        await server.app_runtime.cron_manager.run_now(job.json()["id"], wait=True)
        assert calls and all(
            (key, model) == ("Bearer fixture-access", model_id) for key, model, _ in calls
        )
        paused = await client.patch(
            f"/api/agents/{chief}/cron/{job.json()['id']}", headers=auth, json={"enabled": False}
        )
        assert paused.json()["enabled"] is False
        assert (await client.delete(f"{API}/session", headers=auth)).status_code == 204
        assert (await client.get(f"{API}/status", headers=auth)).json() == {
            "connected": False,
            "selected_model": None,
        }
