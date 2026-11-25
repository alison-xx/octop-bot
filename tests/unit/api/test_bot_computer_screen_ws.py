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

    def screen_ssl(self, agent_id: str, user_id: int) -> None:
        return None

    def screen(self, agent_id: str, user_id: int) -> tuple[str, dict[str, str]]:
        if self.broken:
            raise RuntimeError("sandbox unreachable")
        return "wss://8080-ins.test/websockify", {}

    def taken_over(self, agent_id: str, user_id: int) -> bool:
        return self.takeover

    def set_takeover(self, agent_id: str, user_id: int, active: bool) -> None:
        self.takeover = active
        self.handed_back = not active

    def release_takeover_if_held(self, agent_id: str, user_id: int) -> None:
        if self.takeover:
            self.set_takeover(agent_id, user_id, False)

    def viewing(self, agent_id: str, user_id: int) -> None:
        return None


def _screen_server() -> SimpleNamespace:
    return SimpleNamespace(
        _started=True,
        services=SimpleNamespace(
            user_repo=SimpleNamespace(
                get=lambda _: SimpleNamespace(
                    disabled=False, session_version=0, password_version=0, mfa_version=0
                )
            ),
            agent_repo=SimpleNamespace(get=lambda _: SimpleNamespace(user_id=7)),
        ),
    )


@pytest.fixture
def relay(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Manager, Upstream]:
    import websockets

    manager, upstream = Manager(), Upstream()
    monkeypatch.setattr(bot_computers, "_screen_sessions", bot_computers.ScreenSessions())
    monkeypatch.setattr(bot_computers, "bot_cloud_enabled", lambda: True)
    monkeypatch.setattr(bot_computers, "computer_manager", lambda services: manager)
    monkeypatch.setattr(bot_computers, "TAKEOVER_CHECK_SECONDS", 0.0)
    monkeypatch.setattr(websockets, "connect", lambda *a, **k: upstream)
    app = FastAPI()
    app.include_router(bot_computers.router, prefix="/api/octop-bot")
    app.include_router(bot_computers.session_router, prefix="/api/octop-bot")
    app.state.octop_server = _screen_server()
    return TestClient(app), manager, upstream


def binding(agent_id: str = "bot-a") -> bot_computers.StreamSession:
    return bot_computers.StreamSession(7, 0, 0, 0, time.time() + 3600, agent_id)


def ticket(agent_id: str = "bot-a", *, ttl: float = 60) -> str:
    from dataclasses import replace

    registry = bot_computers._screen_sessions
    value, _ = registry.issue(agent_id, binding(agent_id), "path")
    registry.tickets[value] = replace(registry.tickets[value], expires=time.monotonic() + ttl)
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


@pytest.mark.asyncio
@pytest.mark.parametrize("direct", [False, True])
async def test_cancel_waits_for_handback_and_reaps_relay_tasks(
    monkeypatch: pytest.MonkeyPatch,
    direct: bool,
) -> None:
    import threading

    import anyio
    import websockets

    manager, upstream = Manager(), Upstream()
    manager.takeover = True
    entered, exited = asyncio.Event(), asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original = manager.set_takeover

    def blocked_handback(agent_id: str, user_id: int, active: bool) -> None:
        if not active:
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(10)
        original(agent_id, user_id, active)

    monkeypatch.setattr(manager, "set_takeover", blocked_handback)
    monkeypatch.setattr(bot_computers, "_screen_sessions", bot_computers.ScreenSessions())
    monkeypatch.setattr(bot_computers, "bot_cloud_enabled", lambda: True)
    monkeypatch.setattr(bot_computers, "computer_manager", lambda services: manager)
    monkeypatch.setattr(websockets, "connect", lambda *a, **k: upstream)

    class Socket:
        state = SimpleNamespace()
        app = SimpleNamespace(state=SimpleNamespace(octop_server=_screen_server()))

        async def accept(self, **kwargs: Any) -> None:
            pass

        async def receive(self) -> dict[str, str]:
            return {"type": "websocket.disconnect"}

        async def close(self, **kwargs: Any) -> None:
            pass

    async def run_relay() -> None:
        try:
            with anyio.CancelScope() as scope:
                scope_holder.append(scope)
                await bot_computers.screen_ws(Socket(), "bot-a", ticket())  # type: ignore[arg-type]
        finally:
            exited.set()

    scope_holder: list[anyio.CancelScope] = []
    task = asyncio.create_task(run_relay())
    try:
        with anyio.fail_after(5):
            await entered.wait()
            if direct:
                task.cancel()
            else:
                scope_holder[0].cancel()
            await anyio.wait_all_tasks_blocked()
            assert not exited.is_set(), "relay exited before handback completed"
            if direct:
                task.cancel()
                await anyio.wait_all_tasks_blocked()
                assert not exited.is_set()
    finally:
        release.set()
        with anyio.fail_after(5):
            if direct:
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                await task
    assert manager.handed_back
    assert not [
        t
        for t in asyncio.all_tasks()
        if not t.done() and t.get_coro().__qualname__.startswith("screen_ws.<locals>.")
    ]


@pytest.mark.asyncio
async def test_cancel_during_initial_read_hands_back(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    import anyio

    manager = Manager()
    manager.takeover = True
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def blocked_read(agent_id: str, user_id: int) -> bool:
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(10)
        return manager.takeover

    monkeypatch.setattr(manager, "taken_over", blocked_read)
    monkeypatch.setattr(bot_computers, "_screen_sessions", bot_computers.ScreenSessions())
    monkeypatch.setattr(bot_computers, "bot_cloud_enabled", lambda: True)
    monkeypatch.setattr(bot_computers, "computer_manager", lambda services: manager)

    class Socket:
        state = SimpleNamespace()
        app = SimpleNamespace(state=SimpleNamespace(octop_server=_screen_server()))

        async def accept(self, **kwargs: Any) -> None:
            pass

        async def close(self, **kwargs: Any) -> None:
            pass

    task = asyncio.create_task(bot_computers.screen_ws(Socket(), "bot-a", ticket()))  # type: ignore[arg-type]
    try:
        with anyio.fail_after(5):
            await entered.wait()
            task.cancel()
            await anyio.wait_all_tasks_blocked()
            assert not task.done()
    finally:
        release.set()
        with anyio.fail_after(5), pytest.raises(asyncio.CancelledError):
            await task
    assert manager.handed_back


def test_release_takeover_if_held_checks_raw_state(monkeypatch: pytest.MonkeyPatch) -> None:
    from octop.infra.cloud.computers.manager import ComputerManager, ComputerRecord

    manager = ComputerManager(
        SimpleNamespace(), SimpleNamespace(), billing=object(), clock=lambda: 1000
    )  # type: ignore[arg-type]
    record = ComputerRecord(agent_id="bot-a", user_id=7)
    saved: list[ComputerRecord] = []
    lock = manager._lock("bot-a")

    def read(*args: Any) -> ComputerRecord:
        assert lock._is_owned()  # RLock (manager._lock) has no .locked() on 3.12
        return record

    def save(value: ComputerRecord) -> None:
        assert lock._is_owned()  # RLock (manager._lock) has no .locked() on 3.12
        saved.append(value)

    monkeypatch.setattr(manager, "record", read)
    monkeypatch.setattr(manager, "_save", save)
    manager.release_takeover_if_held("bot-a", 7)
    assert saved == []
    record.takeover = True
    record.viewed_at = 0  # controlled() is already expired
    assert not record.controlled(1000)
    manager.release_takeover_if_held("bot-a", 7)
    assert not record.takeover
    assert saved == [record]


def test_desktop_pastes_and_reads_only_while_its_screen_is_open(
    relay: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, manager, _ = relay
    manager.takeover = True
    clipboard = []

    def paste(agent: str, user: int, text: str) -> None:
        assert (agent, user) == ("bot-a", 7) and manager.takeover
        clipboard.append(text)

    def read(agent: str, user: int) -> str:
        assert (agent, user) == ("bot-a", 7) and manager.takeover
        return clipboard[-1]

    monkeypatch.setattr(manager, "paste_text", paste, raising=False)
    monkeypatch.setattr(manager, "read_clipboard", read, raising=False)
    registry = bot_computers._screen_sessions
    single_use, session = registry.issue("bot-a", binding(), "header")
    headers = {"X-Octop-Screen-Session": session}
    assert registry.lookup(session, "header") is None
    with client.websocket_connect(path("bot-a", single_use)):
        assert (
            client.post(
                "/api/octop-bot/screen-sessions/type", headers=headers, json={"text": "联调样例"}
            ).status_code
            == 204
        )
        response = client.get("/api/octop-bot/screen-sessions/clipboard", headers=headers)
        assert response.headers["Cache-Control"] == "no-store"
        assert response.json() == {"text": "联调样例"}
        assert registry.lookup(session, "path") is None
    wait_for(lambda: registry.lookup(session, "header") is None)
    assert manager.handed_back


def test_screen_heartbeats_cannot_extend_absolute_lifetime(monkeypatch: pytest.MonkeyPatch) -> None:
    from octop.api.common import screen_sessions

    now = 100.0
    monkeypatch.setattr(screen_sessions.time, "monotonic", lambda: now)
    registry = screen_sessions.ScreenSessions()
    single_use, session = registry.issue("bot-a", binding(), "header")
    assert registry.consume(single_use, "bot-a") == (
        session,
        registry.sessions[session],
    )
    registry.sessions[session].connected = True
    assert registry.sessions[session].expires_at == now + screen_sessions.ABSOLUTE_SECONDS
    for _ in range(screen_sessions.ABSOLUTE_SECONDS // 30 - 1):
        now += 30
        registry.refresh(session)
        assert registry.lookup(session, "header") is registry.sessions[session]
    now += 30
    registry.refresh(session)
    assert registry.lookup(session, "header") is None


def test_open_screen_hands_back_when_issued_lifetime_ends(relay: Any) -> None:
    client, manager, _ = relay
    manager.takeover = True
    registry = bot_computers._screen_sessions
    ticket_id, session = registry.issue("bot-a", binding(), "header")
    # Bound the already-issued ticket's remaining lifetime for this ordinary open/close run.
    registry.sessions[session].expires_at = time.monotonic() + 1
    with client.websocket_connect(path("bot-a", ticket_id)) as ws:
        assert ws.receive()["type"] == "websocket.close"
    wait_for(lambda: manager.handed_back)
    assert session not in registry.sessions
