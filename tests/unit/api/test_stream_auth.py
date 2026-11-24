"""Streaming credentials and legacy token accounting."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from octop.api.common import stream_auth
from octop.infra.errors import OctopError
from octop.infra.metrics import METRICS


def test_ticket_single_use_purpose_expiry_and_revocation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stream_auth, "_tickets", {})
    monkeypatch.setattr(stream_auth, "_issued", {})
    user = SimpleNamespace(id=7)
    row = SimpleNamespace(session_version=0)
    server = SimpleNamespace(
        services=SimpleNamespace(user_repo=SimpleNamespace(get=lambda _: row)),
        user_manager=SimpleNamespace(get_by_id=lambda _: user),
    )
    deadline = int(time.time()) + 120
    ticket = stream_auth.issue_ticket(server, user, "chat_ws", deadline)
    assert stream_auth.consume_ticket(server, ticket, "chat_ws") is user
    with pytest.raises(OctopError):
        stream_auth.consume_ticket(server, ticket, "chat_ws")
    ticket = stream_auth.issue_ticket(server, user, "chat_ws", deadline)
    with pytest.raises(OctopError):
        stream_auth.consume_ticket(server, ticket, "voice")
    with pytest.raises(OctopError):
        stream_auth.consume_ticket(server, ticket, "chat_ws")
    ticket = stream_auth.issue_ticket(server, user, "chat_ws", deadline)
    row.session_version += 1
    with pytest.raises(OctopError):
        stream_auth.consume_ticket(server, ticket, "chat_ws")
    ticket = stream_auth.issue_ticket(server, user, "chat_ws", int(time.time()))
    with pytest.raises(OctopError):
        stream_auth.consume_ticket(server, ticket, "chat_ws")


def test_query_token_switch_and_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    socket = SimpleNamespace(query_params={})
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
