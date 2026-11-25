"""Streaming credentials and session lifecycle at the HTTP and WebSocket boundary."""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.responses import StreamingResponse
from starlette.websockets import WebSocketDisconnect

from octop.api.common import stream_auth
from octop.api.routers import agent_mcp
from octop.infra.auth.tokens import PURPOSE_ACCESS, decode_token, sign_token
from octop.infra.metrics import METRICS
from tests.support.auth import bearer, login
from tests.support.http import ws_connect, ws_token


async def _ticket(client: Any, auth: dict[str, str], purpose: str) -> str:
    response = await client.post("/api/auth/ws-ticket", headers=auth, json={"purpose": purpose})
    assert response.status_code == 200, response.text
    return response.json()["ticket"]


async def _refused(app: Any, path: str) -> None:
    with pytest.raises(WebSocketDisconnect) as exc:
        async with ws_connect(app, path):
            pass
    assert exc.value.code == 4001


async def test_ticket_issue_single_use_purpose_expiry_and_limit(
    env_with_main_agent: Any, monkeypatch: Any
) -> None:
    client, _server, auth, agent_id = env_with_main_agent
    monkeypatch.setattr(stream_auth, "_issued", {})
    monkeypatch.setattr(stream_auth, "_tickets", {})
    path = f"/api/agents/{agent_id}/chat/ws"
    app = client._octop_app
    assert (
        await client.post("/api/auth/ws-ticket", json={"purpose": "chat_ws"})
    ).status_code == 401
    ticket = await _ticket(client, auth, "chat_ws")
    async with ws_connect(app, f"{path}?ticket={ticket}") as ws:
        await ws.send_json({"type": "ping"})
        assert (await ws.receive_json())["type"] == "pong"
    await _refused(app, f"{path}?ticket={ticket}")
    other = await _ticket(client, auth, "voice")
    await _refused(app, f"{path}?ticket={other}")
    expired = await _ticket(client, auth, "chat_ws")
    clock = stream_auth.time.monotonic()
    with monkeypatch.context() as patch_clock:
        patch_clock.setattr(stream_auth, "time", SimpleNamespace(monotonic=lambda: clock + 61))
        await _refused(app, f"{path}?ticket={expired}")
    stream_auth._issued.clear()
    for _ in range(60):
        await _ticket(client, auth, "chat_ws")
    limited = await client.post("/api/auth/ws-ticket", headers=auth, json={"purpose": "chat_ws"})
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    stream_auth._issued.clear()


async def test_query_token_switch_and_metrics(env_with_main_agent: Any, monkeypatch: Any) -> None:
    client, _server, auth, agent_id = env_with_main_agent
    token = ws_token(auth)
    path = f"/api/agents/{agent_id}/chat/ws?token={token}"
    monkeypatch.setenv("OCTOP_WS_QUERY_TOKEN", "1")
    before = METRICS.snapshot()
    async with ws_connect(client._octop_app, path):
        pass
    assert (await client.get("/api/auth/me", params={"access_token": token})).status_code == 200
    assert (
        await client.get(
            "/api/mcp/agents",
            params={"access_token": token},
            headers={"Accept": "text/event-stream"},
        )
    ).status_code == 405
    after = METRICS.snapshot()
    assert after["query_token_ws_total"] == before["query_token_ws_total"] + 1
    assert after["query_token_http_total"] == before["query_token_http_total"] + 1
    assert after["query_token_sse_total"] == before["query_token_sse_total"] + 1
    monkeypatch.setenv("OCTOP_WS_QUERY_TOKEN", "0")
    await _refused(client._octop_app, path)
    assert (await client.get("/api/auth/me", params={"access_token": token})).status_code == 401


@pytest.mark.parametrize("endpoint", ["logout", "logout-all"])
async def test_logout_revokes_header_and_query(env: Any, endpoint: str, monkeypatch: Any) -> None:
    client, _server, auth = env
    monkeypatch.setenv("OCTOP_WS_QUERY_TOKEN", "1")
    token = ws_token(auth)
    assert (await client.post(f"/api/auth/{endpoint}", headers=auth)).status_code == 204
    assert (await client.get("/api/auth/me", headers=auth)).status_code == 401
    assert (await client.get("/api/auth/me", params={"access_token": token})).status_code == 401
    assert (
        await client.get("/api/auth/me", headers=bearer(await login(client)))
    ).status_code == 200


async def test_session_absolute_cap_and_renewal(env: Any) -> None:
    client, server, auth = env
    secret = server.services.secret_repo.get("jwt")
    original = decode_token(secret, ws_token(auth))
    now = int(time.time())

    def token(days: int) -> str:
        return sign_token(
            secret,
            sub=original["sub"],
            uname=original["uname"],
            role=original["role"],
            purpose=PURPOSE_ACCESS,
            ttl_seconds=10,
            session_version=original["sv"],
            auth_time=now - days * 86400,
        )

    old = await client.get("/api/auth/me", headers=bearer(token(31)))
    assert old.status_code == 401
    assert "x-octop-access-token" not in old.headers
    recent = await client.get("/api/auth/me", headers=bearer(token(29)))
    assert recent.status_code == 200
    renewed = decode_token(secret, recent.headers["x-octop-access-token"])
    assert renewed["auth_time"] == now - 29 * 86400


async def test_sse_ticket_is_consumed_by_middleware(env: Any, monkeypatch: Any) -> None:
    client, _server, auth = env
    stream_auth._issued.clear()
    ticket = await _ticket(client, auth, "sse")

    def finite_stream(iterator: Any, **kwargs: Any) -> StreamingResponse:
        async def first_frame() -> Any:
            async for frame in iterator:
                yield frame
                break

        return StreamingResponse(first_frame(), **kwargs)

    monkeypatch.setattr(agent_mcp, "StreamingResponse", finite_stream)
    response = await client.get(
        "/api/mcp/agents", params={"ticket": ticket}, headers={"mcp-session-id": "test-session"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: message" in response.text
    assert (await client.get("/api/mcp/agents", params={"ticket": ticket})).status_code == 401
