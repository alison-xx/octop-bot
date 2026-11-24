"""Short-lived, single-use credentials for streaming connections."""

from __future__ import annotations

import os
import secrets
import time
from typing import Any

from octop.infra.errors import ErrorCode, OctopError

_tickets: dict[str, tuple[int, str, int, float]] = {}
_issued: dict[int, list[float]] = {}


def query_tokens_enabled() -> bool:
    return os.environ.get("OCTOP_WS_QUERY_TOKEN", "1").strip().lower() in {"1", "true", "yes", "on"}


def issue_ticket(server: Any, user: Any, purpose: str, deadline: int) -> str:
    now = time.monotonic()
    for key, claim in list(_tickets.items()):
        if claim[3] <= now:
            _tickets.pop(key, None)
    recent = [stamp for stamp in _issued.get(user.id, []) if now - stamp < 60]
    if len(recent) >= 60:
        raise OctopError(ErrorCode.RATE_LIMITED, "too many ticket requests")
    recent.append(now)
    _issued[user.id] = recent
    row = server.services.user_repo.get(user.id)
    ticket = secrets.token_urlsafe(32)
    _tickets[ticket] = (
        user.id,
        purpose,
        row.session_version,
        now + min(60, max(0, deadline - time.time())),
    )
    return ticket


def consume_ticket(server: Any, ticket: str, purpose: str) -> Any:
    claim = _tickets.pop(ticket, None)
    if claim is None or claim[1] != purpose or claim[3] <= time.monotonic():
        raise OctopError(ErrorCode.AUTH_FAILED, "invalid ticket")
    row = server.services.user_repo.get(claim[0])
    user = server.user_manager.get_by_id(claim[0])
    if row is None or user is None or row.session_version != claim[2]:
        raise OctopError(ErrorCode.AUTH_FAILED, "invalid ticket")
    return user


def stream_user(
    server: Any, websocket: Any, purpose: str, token: str | None = None, *, resolver: Any = None
) -> Any:
    if resolver is None:
        from octop.api.deps import resolve_user_from_token

        resolver = resolve_user_from_token

    ticket = websocket.query_params.get("ticket")
    if ticket:
        return consume_ticket(server, ticket, purpose)
    if token and query_tokens_enabled():
        user = resolver(server, token)
        from octop.infra.metrics import METRICS

        METRICS.inc("query_token_ws_total")
        return user
    raise OctopError(ErrorCode.AUTH_FAILED, "missing credentials")


def issue_screen_ticket(
    tickets: dict[str, tuple[str, int, float]], agent_id: str, user_id: int
) -> str:
    now = time.time()
    for token, claim in list(tickets.items()):
        if claim[2] <= now:
            tickets.pop(token, None)
    ticket = secrets.token_urlsafe(32)
    tickets[ticket] = (agent_id, user_id, now + 60)
    return ticket


def consume_screen_ticket(
    tickets: dict[str, tuple[str, int, float]], ticket: str, agent_id: str
) -> int | None:
    claim = tickets.pop(ticket, None)
    if claim is None or claim[0] != agent_id or claim[2] <= time.time():
        return None
    return claim[1]
