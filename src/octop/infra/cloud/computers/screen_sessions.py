"""Clipboard capabilities for one screen relay. All mutations run on the server event loop."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Literal

Transport = Literal["header", "path"]
TICKET_SECONDS = 60
IDLE_SECONDS = 120
ABSOLUTE_SECONDS = 30 * 60


@dataclass
class ScreenSession:
    agent_id: str
    user_id: int
    transport: Transport
    idle_until: float
    expires_at: float
    connected: bool = False


class ScreenSessions:
    def __init__(self) -> None:
        self.tickets: dict[str, tuple[str, str, float]] = {}
        self.sessions: dict[str, ScreenSession] = {}

    def issue(self, agent: str, user: int, transport: Transport) -> tuple[str, str]:
        now = time.monotonic()
        for key, (_, _, until) in list(self.tickets.items()):
            if until <= now:
                del self.tickets[key]
        for key, item in list(self.sessions.items()):
            if min(item.idle_until, item.expires_at) <= now:
                del self.sessions[key]
        ticket, session = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.tickets[ticket] = (agent, session, now + TICKET_SECONDS)
        self.sessions[session] = ScreenSession(
            agent, user, transport, now + IDLE_SECONDS, now + ABSOLUTE_SECONDS
        )
        return ticket, session

    def connect(self, ticket: str, agent: str) -> tuple[str, int, float] | None:
        entry = self.tickets.pop(ticket, None)
        if not entry:
            return None
        expected, session, until = entry
        item = self.sessions.get(session)
        if not item or expected != agent or min(until, item.expires_at) <= time.monotonic():
            self.close(session)
            return None
        item.connected = True
        return session, item.user_id, item.expires_at

    def refresh(self, session: str) -> None:
        item = self.sessions.get(session)
        now = time.monotonic()
        if item and item.connected and min(item.idle_until, item.expires_at) > now:
            item.idle_until = min(item.expires_at, now + IDLE_SECONDS)

    def lookup(self, session: str, transport: Transport) -> tuple[str, int] | None:
        item = self.sessions.get(session)
        if not item or item.transport != transport:
            return None
        if min(item.expires_at, item.idle_until) <= time.monotonic():
            self.close(session)
            return None
        if transport == "header" and not item.connected:
            return None
        return item.agent_id, item.user_id

    def close(self, session: str) -> None:
        self.sessions.pop(session, None)
