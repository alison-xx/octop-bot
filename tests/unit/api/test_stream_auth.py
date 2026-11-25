"""Streaming credentials and legacy token accounting."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi import WebSocket

from octop.api.common import stream_auth
from octop.infra.errors import OctopError
from octop.infra.metrics import METRICS


def test_ticket_single_use_purpose_expiry_and_revocation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stream_auth, "_tickets", {})
    monkeypatch.setattr(stream_auth, "_issued", {})
    user = SimpleNamespace(id=7)
    row = SimpleNamespace(session_version=0, mfa_version=0, password_version=0, disabled=False)
    server = SimpleNamespace(
        services=SimpleNamespace(user_repo=SimpleNamespace(get=lambda _: row)),
        user_manager=SimpleNamespace(get_by_id=lambda _: user),
    )
    deadline = int(time.time()) + 120
    ticket = stream_auth.issue_ticket(
        stream_auth.StreamSession(user.id, row.session_version, 0, 0, deadline), "chat_ws"
    )
    assert stream_auth.consume_ticket(server, ticket, "chat_ws") is user
    with pytest.raises(OctopError):
        stream_auth.consume_ticket(server, ticket, "chat_ws")
    ticket = stream_auth.issue_ticket(
        stream_auth.StreamSession(user.id, row.session_version, 0, 0, deadline), "chat_ws"
    )
    with pytest.raises(OctopError):
        stream_auth.consume_ticket(server, ticket, "voice")
    with pytest.raises(OctopError):
        stream_auth.consume_ticket(server, ticket, "chat_ws")
    ticket = stream_auth.issue_ticket(
        stream_auth.StreamSession(user.id, row.session_version, 0, 0, deadline), "chat_ws"
    )
    row.session_version += 1
    with pytest.raises(OctopError):
        stream_auth.consume_ticket(server, ticket, "chat_ws")
    ticket = stream_auth.issue_ticket(
        stream_auth.StreamSession(user.id, row.session_version, 0, 0, time.time()), "chat_ws"
    )
    with pytest.raises(OctopError):
        stream_auth.consume_ticket(server, ticket, "chat_ws")


def test_query_token_switch_and_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    socket = SimpleNamespace(query_params={}, state=SimpleNamespace())
    monkeypatch.setattr("octop.api.deps._decode", lambda *_: {"sub": "7", "iat": 0, "exp": 1})
    user = SimpleNamespace(id=7)
    resolver = lambda _server, _token: user  # noqa: E731
    before = METRICS.snapshot()["query_token_ws_total"]
    monkeypatch.setenv("OCTOP_WS_QUERY_TOKEN", "1")
    assert stream_auth.stream_user(None, socket, "chat_ws", "token", resolver=resolver) is user
    assert METRICS.snapshot()["query_token_ws_total"] == before + 1
    monkeypatch.setenv("OCTOP_WS_QUERY_TOKEN", "0")
    with pytest.raises(OctopError):
        stream_auth.stream_user(None, socket, "chat_ws", "token", resolver=resolver)
    assert METRICS.snapshot()["query_token_ws_total"] == before + 1


@pytest.mark.parametrize(
    "field", ["session_version", "password_version", "mfa_version", "disabled"]
)
def test_stream_session_tracks_account_state(field: str) -> None:
    row = SimpleNamespace(disabled=False, session_version=1, password_version=2, mfa_version=3)
    server = SimpleNamespace(services=SimpleNamespace(user_repo=SimpleNamespace(get=lambda _: row)))
    now = time.time()
    session = stream_auth.StreamSession.from_claims(
        {"sub": "7", "iat": now, "exp": now + 60, "sv": 1, "password_version": 2, "mfa_version": 3}
    )
    assert session.active(server)
    setattr(row, field, getattr(row, field) + 1)
    assert not session.active(server)


def test_chat_closes_at_credential_expiry() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from octop.api.middleware.stream_session import StreamSessionMiddleware

    row = SimpleNamespace(disabled=False, session_version=0, password_version=0, mfa_version=0)
    server = SimpleNamespace(services=SimpleNamespace(user_repo=SimpleNamespace(get=lambda _: row)))
    app = FastAPI()
    app.add_middleware(StreamSessionMiddleware, server=server)

    async def chat(websocket: WebSocket) -> None:
        websocket.state.stream_session = stream_auth.StreamSession(7, 0, 0, 0, time.time())
        await websocket.accept()
        await websocket.receive_text()
        pytest.fail("the handler received a frame after expiry")

    app.add_api_websocket_route("/chat/ws", chat)
    with TestClient(app).websocket_connect("/chat/ws") as socket:
        socket.send_text("hello")
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_text()
        assert closed.value.code == 4001


def test_open_screen_follows_renewal_of_its_sign_in() -> None:
    from dataclasses import replace

    now = int(time.time())
    current = stream_auth.StreamSession(7, 1, 2, 3, now + 60, "bot", now - 120)
    renewed = replace(current, deadline=now + 180)
    assert current.renew(renewed)
    assert current.deadline == now + 180
    assert not current.renew(replace(renewed, auth_time=now))
    assert not current.renew(replace(renewed, session_version=2))
    assert not current.renew(replace(renewed, agent_id="other"))
    assert not replace(current, deadline=now).renew(renewed)
