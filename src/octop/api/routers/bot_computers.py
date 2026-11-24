"""Octop Bot cloud: each Bot's cloud computer, for the Bot profile's "Cloud computer" panel."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import time
from typing import Any, Literal

import anyio
from fastapi import APIRouter, Depends, Query, WebSocket
from pydantic import BaseModel, Field

from octop.api.deps import current_user, get_server
from octop.infra.cloud.computers.manager import computer_manager
from octop.infra.cloud.computers.rfb import RfbClientFilter
from octop.infra.desktop import bot_cloud_enabled
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/computers")
# Typing and the clipboard of an open screen: the session token in the path is the credential
# (the phone apps' screen page has no sign-in), so this prefix skips the JWT middleware.
session_router = APIRouter(prefix="/screen-sessions")

SCREEN_TICKET_SECONDS = 60
# An open screen keeps its computer awake for this long after it opened or after the user's
# last input, so a tab forgotten in the background cannot spend credits forever.
SCREEN_KEEP_AWAKE_SECONDS = 30 * 60
# How often the relay rechecks whether the user has taken over (and may send input).
TAKEOVER_CHECK_SECONDS = 1.0
# A screen session lives while its screen is open (the relay refreshes it) and a little after.
SCREEN_SESSION_IDLE_SECONDS = 120
MAX_PASTE_CHARS = 20_000
# One-time tickets for the screen WebSocket: ticket -> (agent_id, user_id, expires_at).
_tickets: dict[str, tuple[str, int, float]] = {}
# Screen sessions: session -> (agent_id, user_id, expires_at).
_sessions: dict[str, tuple[str, int, float]] = {}


class ComputerStatus(BaseModel):
    state: Literal["none", "running", "paused"] = Field(
        description="none: not started yet (it starts on the Bot's first tool use)."
    )
    spec: str = Field(description="Size of the computer, e.g. standard.")
    running_since: float | None = Field(default=None, description="Unix time it last started.")
    paid_until: float | None = Field(
        default=None, description="Unix time the running time already paid for runs out."
    )
    takeover: bool = Field(
        default=False, description="The user has the mouse and keyboard; the Bot waits."
    )
    busy: bool = Field(default=False, description="The Bot is working on the computer right now.")
    activity: str | None = Field(
        default=None,
        description="The Bot's latest action: screenshot, click, double_click, right_click, "
        "move, drag, scroll, type, key, wait, elements, zoom or command.",
    )
    activity_at: float | None = Field(default=None, description="Unix time of that action.")


class ComputerGlance(BaseModel):
    window: str | None = Field(default=None, description="Title of the front window, if any.")
    thumbnail: str | None = Field(
        default=None, description="The screen as a base64 JPEG, 320 px wide."
    )


def _owned(server: Any, user: User, agent_id: str) -> Any:
    if not bot_cloud_enabled():
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    manager = computer_manager(server.services)
    row = server.services.agent_repo.get(agent_id)
    if manager is None or row is None or row.user_id != user.id:
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    return manager


def _status(manager: Any, agent_id: str, user_id: int) -> ComputerStatus:
    record = manager.record(agent_id, user_id)
    if record.instance_id is None:
        return ComputerStatus(
            state="none", spec=record.spec, takeover=record.controlled(time.time())
        )
    last = manager.activity(agent_id)
    return ComputerStatus(
        state="running" if record.running else "paused",
        spec=record.spec,
        running_since=record.started_at or record.running_since,
        paid_until=record.paid_until if record.running else None,
        takeover=record.controlled(time.time()),
        busy=record.running and manager.busy(agent_id),
        activity=last[0] if last else None,
        activity_at=last[1] if last else None,
    )


@router.get("/{agent_id}", summary="Read a Bot's cloud computer", response_model=ComputerStatus)
async def computer_status(
    agent_id: str, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> ComputerStatus:
    manager = _owned(server, user, agent_id)
    return await asyncio.to_thread(_status, manager, agent_id, user.id)


@router.get(
    "/{agent_id}/glance",
    summary="Glance at a Bot's running cloud computer",
    description="Front window title and a small thumbnail, for the chat's floating screen. "
    "Never starts or resumes the computer: 404 while it is off.",
    response_model=ComputerGlance,
)
async def computer_glance(
    agent_id: str, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> ComputerGlance:
    manager = _owned(server, user, agent_id)
    glance = await asyncio.to_thread(manager.glance, agent_id, user.id)
    if glance is None:
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    return ComputerGlance(window=glance.window, thumbnail=glance.thumbnail)


@router.post(
    "/{agent_id}/pause",
    summary="Pause a Bot's cloud computer now",
    description="Stops billing for running time; the next tool use resumes it with its files.",
    response_model=ComputerStatus,
)
async def pause_computer(
    agent_id: str, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> ComputerStatus:
    manager = _owned(server, user, agent_id)
    await asyncio.to_thread(manager.pause, agent_id, user.id)
    return await asyncio.to_thread(_status, manager, agent_id, user.id)


class TakeoverRequest(BaseModel):
    active: bool = Field(description="true: the user takes the computer; false: hand it back.")


@router.post(
    "/{agent_id}/takeover",
    summary="Take over or hand back a Bot's cloud computer",
    description="While taken over, the Bot's commands on the computer are refused with a note "
    "to wait, and the computer is never paused for being idle.",
    response_model=ComputerStatus,
)
async def takeover(
    agent_id: str,
    body: TakeoverRequest,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> ComputerStatus:
    manager = _owned(server, user, agent_id)
    await asyncio.to_thread(manager.set_takeover, agent_id, user.id, body.active)
    return await asyncio.to_thread(_status, manager, agent_id, user.id)


class ScreenTicket(BaseModel):
    ws_path: str = Field(description="WebSocket path (VNC over WebSocket), ticket included.")
    expires_in: int = Field(description="Seconds the one-time ticket stays valid.")
    session: str = Field(
        description="Screen session for typing and the clipboard "
        "(/api/octop-bot/screen-sessions/{session}/…); valid while the screen is open."
    )


@router.post(
    "/{agent_id}/screen",
    summary="Open a Bot's cloud computer screen",
    description="Starts or resumes the computer and returns a one-time WebSocket path that "
    "carries its desktop (RFB over WebSocket, for noVNC). The ticket is the only credential.",
    response_model=ScreenTicket,
)
async def open_screen(
    agent_id: str, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> ScreenTicket:
    manager = _owned(server, user, agent_id)
    await asyncio.to_thread(manager.ensure_running, agent_id, user.id)
    now = time.time()
    for stale in [t for t, (_, _, until) in _tickets.items() if until < now]:
        _tickets.pop(stale, None)
    for stale in [s for s, (_, _, until) in _sessions.items() if until < now]:
        _sessions.pop(stale, None)
    ticket, session = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    _tickets[ticket] = (agent_id, user.id, now + SCREEN_TICKET_SECONDS)
    _sessions[session] = (agent_id, user.id, now + SCREEN_SESSION_IDLE_SECONDS)
    return ScreenTicket(
        ws_path=f"/api/octop-bot/computers/{agent_id}/screen/ws?ticket={ticket}",
        expires_in=SCREEN_TICKET_SECONDS,
        session=session,
    )


def _refresh_sessions(agent_id: str, user_id: int) -> None:
    until = time.time() + SCREEN_SESSION_IDLE_SECONDS
    for key, (agent, user, _) in list(_sessions.items()):
        if agent == agent_id and user == user_id:
            _sessions[key] = (agent, user, until)


def _session(session: str) -> tuple[str, int]:
    claim = _sessions.get(session)
    if claim is None or claim[2] < time.time():
        _sessions.pop(session, None)
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    _refresh_sessions(claim[0], claim[1])
    return claim[0], claim[1]


def _session_manager(server: Any) -> Any:
    manager = computer_manager(server.services) if bot_cloud_enabled() else None
    if manager is None:
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    return manager


class PasteRequest(BaseModel):
    text: str = Field(
        min_length=1, max_length=MAX_PASTE_CHARS, description="Text to type, in any language."
    )


@session_router.post(
    "/{session}/type",
    summary="Type text into a taken-over cloud computer",
    description="Puts the text on the desktop's clipboard and pastes it at the cursor, so "
    "Chinese and other IME input work (VNC keys cannot carry them). Needs takeover. The screen "
    "session in the path is the credential.",
    status_code=204,
)
async def type_text(session: str, body: PasteRequest, server: Any = Depends(get_server)) -> None:
    agent_id, user_id = _session(session)
    manager = _session_manager(server)
    await asyncio.to_thread(manager.paste_text, agent_id, user_id, body.text)


class Clipboard(BaseModel):
    text: str = Field(description="The desktop's clipboard text; empty when it holds no text.")


@session_router.get(
    "/{session}/clipboard",
    summary="Read a taken-over cloud computer's clipboard",
    description="Needs takeover. The screen session in the path is the credential.",
    response_model=Clipboard,
)
async def read_clipboard(session: str, server: Any = Depends(get_server)) -> Clipboard:
    agent_id, user_id = _session(session)
    manager = _session_manager(server)
    return Clipboard(text=await asyncio.to_thread(manager.read_clipboard, agent_id, user_id))


@router.websocket("/{agent_id}/screen/ws")
async def screen_ws(websocket: WebSocket, agent_id: str, ticket: str = Query(default="")) -> None:
    """Relay the browser's noVNC client to the desktop inside the sandbox."""
    claim = _tickets.pop(ticket, None)
    if claim is None or claim[0] != agent_id or claim[2] < time.time():
        await websocket.close(code=4001, reason="invalid ticket")
        return
    _, user_id, _ = claim
    server = websocket.app.state.octop_server
    manager = computer_manager(server.services) if bot_cloud_enabled() else None
    if manager is None:
        await websocket.close(code=4004, reason="no cloud computers")
        return
    await websocket.accept(subprotocol="binary")
    import websockets  # noqa: PLC0415
    from websockets.typing import Subprotocol  # noqa: PLC0415

    gate = RfbClientFilter()
    opened = last_input = time.monotonic()
    control = {"allowed": False, "checked": float("-inf")}
    # Only the screen that has the computer hands it back when it closes: one opened while
    # taken over, or one the user typed into. A view-only screen closing (the phone swaps its
    # view-only page for the control page right after taking over) must not undo the takeover.
    holds = {"control": False}
    initial = asyncio.create_task(asyncio.to_thread(manager.taken_over, agent_id, user_id))
    tasks: list[asyncio.Task[None]] = []

    async def input_allowed() -> bool:
        # View-only is a client setting; the relay itself holds input back until takeover.
        now = time.monotonic()
        if now - control["checked"] >= TAKEOVER_CHECK_SECONDS:
            control["allowed"] = await asyncio.to_thread(manager.taken_over, agent_id, user_id)
            control["checked"] = now
        return bool(control["allowed"])

    try:
        holds["control"] = await asyncio.shield(initial)
        url, headers = await asyncio.to_thread(manager.screen, agent_id, user_id)
        pinned = (
            await asyncio.to_thread(manager.screen_ssl, agent_id, user_id)
            if url.startswith("wss://")
            else None
        )
        async with websockets.connect(
            url,
            additional_headers=headers,
            subprotocols=[Subprotocol("binary")],
            max_size=None,
            **({"ssl": pinned} if pinned is not None else {}),
        ) as upstream:

            async def down() -> None:
                async for frame in upstream:
                    if isinstance(frame, bytes):
                        await websocket.send_bytes(frame)
                    else:
                        await websocket.send_text(frame)

            async def up() -> None:
                nonlocal last_input
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        return
                    data = message.get("bytes")
                    if data is None:
                        continue  # noVNC speaks binary only
                    allowed = await input_allowed()
                    forward, saw_input = gate.feed(data, allow_input=allowed)
                    if saw_input and allowed:
                        last_input = time.monotonic()
                        holds["control"] = True
                    if forward:
                        await upstream.send(forward)

            async def keep_alive() -> None:
                while True:
                    await asyncio.sleep(30)
                    awake_since = max(opened, last_input)
                    if time.monotonic() - awake_since >= SCREEN_KEEP_AWAKE_SECONDS:
                        continue  # still shown, but no longer keeps the computer running
                    _refresh_sessions(agent_id, user_id)
                    await asyncio.to_thread(manager.viewing, agent_id, user_id)

            tasks = [asyncio.create_task(job()) for job in (down, up, keep_alive)]
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except Exception:  # noqa: BLE001 - the viewer just closes
        logger.warning("screen relay for %s ended with an error", agent_id, exc_info=True)
    finally:

        async def cleanup() -> None:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            # The first read may still be running when the relay is cancelled.
            with contextlib.suppress(Exception):
                holds["control"] |= await initial
            if holds["control"]:
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(manager.release_takeover_if_held, agent_id, user_id)
            with contextlib.suppress(Exception):
                await websocket.close()

        # Scope shielding and repeated joins also withstand direct Task.cancel().
        cancelled: asyncio.CancelledError | None = None
        with anyio.CancelScope(shield=True):
            cleanup_task = asyncio.create_task(cleanup())
            while not cleanup_task.done():
                try:
                    await asyncio.shield(cleanup_task)
                except asyncio.CancelledError as exc:
                    cancelled = exc
            await cleanup_task
        if cancelled is not None:
            raise cancelled
