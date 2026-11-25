"""Short-lived, single-use connection tickets bound to the current signed-in account."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceTicket:
    owner: int
    device_id: str
    label: str
    expires: float


class DeviceTickets:
    def __init__(self) -> None:
        self._tickets: dict[str, DeviceTicket] = {}

    def issue(self, owner: int, device_id: str, label: str) -> str:
        now = time.monotonic()
        self._tickets = {
            k: v
            for k, v in self._tickets.items()
            if v.expires > now and (v.owner, v.device_id) != (owner, device_id)
        }
        if sum(v.owner == owner for v in self._tickets.values()) >= 8:
            raise ValueError("Too many pending connections.")
        secret = secrets.token_urlsafe(32)
        self._tickets[secret] = DeviceTicket(owner, device_id, label, now + 30)
        return secret

    def consume(self, secret: str) -> DeviceTicket | None:
        ticket = self._tickets.pop(secret, None)
        return ticket if ticket and ticket.expires > time.monotonic() else None
