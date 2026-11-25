"""Credentials for a single screen and its clipboard, owned by the server event loop."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Literal

from octop.api.common.stream_auth import (
    ScreenTicketClaim,
    StreamSession,
    consume_screen_ticket,
    issue_screen_ticket,
)

Transport = Literal["header", "path"]
TICKET_SECONDS = 60
IDLE_SECONDS = 120
ABSOLUTE_SECONDS = 30 * 60


@dataclass
class ScreenSession:
    agent_id: str
    binding: StreamSession
    transport: Transport
    idle_until: float
    expires_at: float
    connected: bool = False


class ScreenSessions:
    def __init__(self) -> None:
        self.tickets: dict[str, ScreenTicketClaim] = {}
        self.sessions: dict[str, ScreenSession] = {}

    def issue(self, agent: str, binding: StreamSession, transport: Transport) -> tuple[str, str]:
        now = time.monotonic()
        for key, item in list(self.sessions.items()):
            if min(item.idle_until, item.expires_at) <= now:
                self.close(key)
        session = secrets.token_urlsafe(32)
        ticket = issue_screen_ticket(self.tickets, agent, binding, session)
        self.sessions[session] = ScreenSession(
            agent, binding, transport, now + IDLE_SECONDS, now + ABSOLUTE_SECONDS
        )
        return ticket, session

    def consume(self, ticket: str, agent: str) -> tuple[str, ScreenSession] | None:
        claim = consume_screen_ticket(self.tickets, ticket, agent)
        if claim is None:
            return None
        item = self.live(claim.screen_key)
        if item is None:
            return None
        return claim.screen_key, item

    def live(self, session: str) -> ScreenSession | None:
        item = self.sessions.get(session)
        if item and min(item.idle_until, item.expires_at) <= time.monotonic():
            self.close(session)
            return None
        return item

    def refresh(self, session: str) -> None:
        item = self.live(session)
        if item:
            item.idle_until = min(item.expires_at, time.monotonic() + IDLE_SECONDS)

    def lookup(self, session: str, transport: Transport) -> ScreenSession | None:
        item = self.live(session)
        if (
            not item
            or item.transport != transport
            or (transport == "header" and not item.connected)
        ):
            return None
        return item

    def close(self, session: str) -> None:
        self.sessions.pop(session, None)
