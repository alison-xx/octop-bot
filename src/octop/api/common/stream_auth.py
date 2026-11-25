"""Short-lived, single-use credentials for streaming connections."""

from __future__ import annotations

import os
import secrets
import time
from dataclasses import dataclass, replace
from typing import Any

from octop.infra.auth.tokens import token_mfa_version, token_password_version
from octop.infra.errors import ErrorCode, OctopError


@dataclass
class StreamSession:
    user_id: int
    session_version: int
    password_version: int
    mfa_version: int
    deadline: float
    agent_id: str | None = None
    auth_time: int = 0
    purpose: str = "access"

    @classmethod
    def from_claims(cls, claims: dict[str, Any], *, agent_id: str | None = None) -> StreamSession:
        auth_time = int(claims.get("auth_time", claims["iat"]))
        return cls(
            int(claims["sub"]),
            int(claims.get("sv", 0)),
            token_password_version(claims),
            token_mfa_version(claims),
            min(float(claims["exp"]), auth_time + 30 * 86400),
            agent_id,
            auth_time,
            str(claims.get("purpose", "access")),
        )

    def renew(self, signed: StreamSession) -> bool:
        """Extend this live view only for a renewed credential of the same sign-in."""
        if time.time() >= self.deadline or self != replace(signed, deadline=self.deadline):
            return False
        self.deadline = max(self.deadline, signed.deadline)
        return True

    def active(self, server: Any) -> bool:
        if self.agent_id is not None:
            agent = server.services.agent_repo.get(self.agent_id)
            if agent is None or agent.user_id != self.user_id:
                return False
        row = server.services.user_repo.get(self.user_id)
        return bool(
            row is not None
            and not row.disabled
            and row.session_version == self.session_version
            and row.password_version == self.password_version
            and row.mfa_version == self.mfa_version
            and time.time() < self.deadline
        )


@dataclass(frozen=True)
class Ticket:
    purpose: str
    session: StreamSession
    expires: float


_tickets: dict[str, Ticket] = {}
_issued: dict[int, list[float]] = {}


def query_tokens_enabled() -> bool:
    return os.environ.get("OCTOP_WS_QUERY_TOKEN", "1").strip().lower() in {"1", "true", "yes", "on"}


def issue_ticket(session: StreamSession, purpose: str) -> str:
    now = time.monotonic()
    for key, claim in list(_tickets.items()):
        if claim.expires <= now:
            _tickets.pop(key, None)
    recent = [stamp for stamp in _issued.get(session.user_id, []) if now - stamp < 60]
    if len(recent) >= 60:
        raise OctopError(ErrorCode.RATE_LIMITED, "too many ticket requests")
    recent.append(now)
    _issued[session.user_id] = recent
    ticket = secrets.token_urlsafe(32)
    _tickets[ticket] = Ticket(purpose, session, now + 60)
    return ticket


def _take_ticket(server: Any, ticket: str, purpose: str) -> Ticket:
    claim = _tickets.pop(ticket, None)
    if (
        claim is None
        or claim.purpose != purpose
        or claim.expires <= time.monotonic()
        or not claim.session.active(server)
    ):
        raise OctopError(ErrorCode.AUTH_FAILED, "invalid ticket")
    return claim


def consume_ticket(server: Any, ticket: str, purpose: str) -> Any:
    claim = _take_ticket(server, ticket, purpose)
    user = server.user_manager.get_by_id(claim.session.user_id)
    if user is None:
        raise OctopError(ErrorCode.AUTH_FAILED, "invalid ticket")
    return user


def bind_ws_user(server: Any, websocket: Any, token: str, *, resolver: Any = None) -> Any:
    from octop.api.deps import _decode, resolve_user_from_token

    user = (resolver or resolve_user_from_token)(server, token)
    websocket.state.stream_session = StreamSession.from_claims(_decode(server, token))
    return user


def stream_user(
    server: Any, websocket: Any, purpose: str, token: str | None = None, *, resolver: Any = None
) -> Any:
    ticket = websocket.query_params.get("ticket")
    if ticket:
        session = _take_ticket(server, ticket, purpose).session
        user = server.user_manager.get_by_id(session.user_id)
        if user is None:
            raise OctopError(ErrorCode.AUTH_FAILED, "invalid ticket")
        websocket.state.stream_session = session
        return user
    if token and query_tokens_enabled():
        user = bind_ws_user(server, websocket, token, resolver=resolver)
        from octop.infra.metrics import METRICS

        METRICS.inc("query_token_ws_total")
        return user
    raise OctopError(ErrorCode.AUTH_FAILED, "missing credentials")


@dataclass(frozen=True)
class ScreenTicketClaim(Ticket):
    screen_key: str


def issue_screen_ticket(
    tickets: dict[str, ScreenTicketClaim], agent_id: str, session: StreamSession, screen_key: str
) -> str:
    now = time.monotonic()
    for token, claim in list(tickets.items()):
        if claim.expires <= now:
            tickets.pop(token, None)
    ticket = secrets.token_urlsafe(32)
    tickets[ticket] = ScreenTicketClaim(agent_id, session, now + 60, screen_key)
    return ticket


def consume_screen_ticket(
    tickets: dict[str, ScreenTicketClaim], ticket: str, agent_id: str
) -> ScreenTicketClaim | None:
    claim = tickets.pop(ticket, None)
    if claim is None or claim.purpose != agent_id or claim.expires <= time.monotonic():
        return None
    return claim
