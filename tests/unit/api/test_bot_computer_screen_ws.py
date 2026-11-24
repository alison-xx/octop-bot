"""The cloud computer screen relay: one-time tickets, input held back until takeover."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from octop.api.routers import bot_computers

HANDSHAKE = b"RFB 003.008\n\x01\x01"
POINTER = b"\x05\x01\x00\x0a\x00\x14"
UPDATE = b"\x03\x01\x00\x00\x00\x00\x07\x80\x04\x38"


class Upstream:
    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self._closed = asyncio.Event()

    async def __aenter__(self) -> Upstream:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    def __aiter__(self) -> Upstream:
        return self

    async def __anext__(self) -> bytes:
        await self._closed.wait()
        raise StopAsyncIteration


class Manager:
    def __init__(self) -> None:
        self.takeover = False
        self.handed_back = False
        self.broken = False

    def screen(self, agent_id: str, user_id: int) -> tuple[str, dict[str, str]]:
        if self.broken:
            raise RuntimeError("sandbox unreachable")
        return "wss://8080-ins.test/websockify", {}

    def taken_over(self, agent_id: str, user_id: int) -> bool:
        return self.takeover

    def set_takeover(self, agent_id: str, user_id: int, active: bool) -> None:
        self.takeover = active
        self.handed_back = not active

    def viewing(self, agent_id: str, user_id: int) -> None:
        return None


@pytest.fixture
def relay(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Manager, Upstream]:
    import websockets

    manager, upstream = Manager(), Upstream()
    monkeypatch.setattr(bot_computers, "_tickets", {})
    monkeypatch.setattr(bot_computers, "bot_cloud_enabled", lambda: True)
    monkeypatch.setattr(bot_computers, "computer_manager", lambda services: manager)
    monkeypatch.setattr(bot_computers, "TAKEOVER_CHECK_SECONDS", 0.0)
    monkeypatch.setattr(websockets, "connect", lambda *a, **k: upstream)
    app = FastAPI()
    app.include_router(bot_computers.router, prefix="/api/octop-bot")
    app.state.octop_server = SimpleNamespace(services=None)
    return TestClient(app), manager, upstream


def ticket(agent_id: str = "bot-a", *, ttl: float = 60) -> str:
    value = f"t-{agent_id}-{ttl}"
    bot_computers._tickets[value] = (agent_id, 7, time.time() + ttl)
    return value


def path(agent_id: str, value: str) -> str:
    return f"/api/octop-bot/computers/{agent_id}/screen/ws?ticket={value}"


def refused(client: TestClient, url: str) -> int:
    with pytest.raises(WebSocketDisconnect) as closed, client.websocket_connect(url) as ws:
        ws.receive_bytes()
    return closed.value.code


def wait_for(check: Any) -> None:
    # Generous: the hand-back runs on the relay's own thread, which a loaded CI runner
    # (Windows especially) can delay for seconds. A passing check returns at once.
    deadline = time.monotonic() + 15
    while not check() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert check()


def test_a_ticket_opens_only_its_own_bot_and_only_in_time(relay: Any) -> None:
    client, manager, upstream = relay
    assert refused(client, path("bot-b", ticket("bot-a"))) == 4001
    assert refused(client, path("bot-a", ticket("bot-a", ttl=-1))) == 4001
    assert refused(client, path("bot-a", "forged")) == 4001


def test_a_ticket_is_single_use(relay: Any) -> None:
    client, manager, upstream = relay
    manager.broken = True
    once = ticket()
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(path("bot-a", once)) as ws:
        ws.receive_bytes()  # accepted, then closed: the sandbox is unreachable
    assert refused(client, path("bot-a", once)) == 4001


def test_input_waits_for_takeover_and_leaving_hands_the_computer_back(relay: Any) -> None:
    client, manager, upstream = relay
    with client.websocket_connect(path("bot-a", ticket())) as ws:
        ws.send_bytes(HANDSHAKE)
        ws.send_bytes(POINTER)  # view-only: held back even if the client sends it
        ws.send_bytes(UPDATE)  # in order behind it, so the pointer has been dealt with
        wait_for(lambda: upstream.sent == [HANDSHAKE, UPDATE])
        manager.takeover = True
        ws.send_bytes(POINTER)
        wait_for(lambda: upstream.sent == [HANDSHAKE, UPDATE, POINTER])
        ws.close()  # the tab goes away while the user still has control
        wait_for(lambda: manager.handed_back)


def test_a_view_only_screen_closing_keeps_a_takeover_made_elsewhere(relay: Any) -> None:
    client, manager, upstream = relay
    with client.websocket_connect(path("bot-a", ticket())) as ws:
        ws.send_bytes(HANDSHAKE)
        wait_for(lambda: upstream.sent == [HANDSHAKE])
        manager.takeover = True  # the phone takes over, then swaps this page for the control one
        ws.close()
    time.sleep(0.2)
    assert manager.takeover and not manager.handed_back


def test_a_screen_opened_in_control_hands_back_when_it_closes(relay: Any) -> None:
    client, manager, upstream = relay
    manager.takeover = True
    with client.websocket_connect(path("bot-a", ticket())) as ws:
        ws.send_bytes(HANDSHAKE)
        wait_for(lambda: upstream.sent == [HANDSHAKE])
        ws.close()
    wait_for(lambda: manager.handed_back)
