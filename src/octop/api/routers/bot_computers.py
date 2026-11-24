"""Octop Bot cloud: each Bot's cloud computer, for the Bot profile's "Cloud computer" panel."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import posixpath
import secrets
import shlex
import time
from collections.abc import Iterator
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, WebSocket
from pydantic import BaseModel, Field

from octop.api.deps import _decode, extract_raw_token, get_server
from octop.api.deps import desktop_remote_user as resolve_desktop_remote_user
from octop.infra.auth.tokens import PURPOSE_DESKTOP_REMOTE
from octop.infra.cloud.computers.backend import TAKEN_OVER
from octop.infra.cloud.computers.driver import WORKSPACE
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


async def desktop_remote_user(request: Request, server: Any = Depends(get_server)) -> User:
    user = await resolve_desktop_remote_user(request, server)
    raw = extract_raw_token(authorization=request.headers.get("authorization"))
    assert raw is not None
    if _decode(server, raw).get("purpose") == PURPOSE_DESKTOP_REMOTE:
        row = server.services.agent_repo.get(request.path_params["agent_id"])
        if row is None or row.user_id != user.id or row.kind != "shadow":
            raise OctopError.localized(ErrorCode.NOT_FOUND)
    return user


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
    agent_id: str, user: User = Depends(desktop_remote_user), server: Any = Depends(get_server)
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
    agent_id: str, user: User = Depends(desktop_remote_user), server: Any = Depends(get_server)
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
    agent_id: str, user: User = Depends(desktop_remote_user), server: Any = Depends(get_server)
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
    user: User = Depends(desktop_remote_user),
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


# -- Driving the computer from elsewhere (the desktop app's Bots, through their shadow Bot) ----
# Each of these counts as using the computer: it starts or resumes it if needed.

MAX_COMMAND_SECONDS = 30 * 60
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_OUTPUT_BYTES = 1024 * 1024
_transfer_counts: dict[int, int] = {}
_command_counts: dict[int, int] = {}


@contextlib.contextmanager
def _slot(counts: dict[int, int], user_id: int) -> Iterator[None]:
    if counts.get(user_id, 0) >= 2:
        raise OctopError.localized(ErrorCode.LOGIN_LOCKED)
    counts[user_id] = counts.get(user_id, 0) + 1
    try:
        yield
    finally:
        counts[user_id] -= 1
        if not counts[user_id]:
            del counts[user_id]


def _output(text: str) -> tuple[str, bool]:
    data = text.encode("utf-8")
    return data[:MAX_OUTPUT_BYTES].decode("utf-8", errors="ignore"), len(data) > MAX_OUTPUT_BYTES


def _audit(server: Any, user: User, agent_id: str, action: str, command: str, code: int) -> None:
    server.services.audit_repo.write(
        actor=user.username,
        action=action,
        target=agent_id,
        payload=json.dumps({"command": command[:200], "exit_code": code}),
    )


# Where files may be read and written: the user's home on the computer, and its temp folder.
_FILE_ROOTS = ("/home/user", "/tmp")


class RunCommand(BaseModel):
    command: str = Field(min_length=1, max_length=100_000, description="A shell command.")
    timeout: int = Field(
        default=120, ge=1, le=MAX_COMMAND_SECONDS, description="Seconds before it is stopped."
    )


class CommandResult(BaseModel):
    truncated: bool = False
    exit_code: int
    output: str = Field(description="Standard output and error, interleaved.")
    taken_over: bool = Field(
        default=False,
        description="The user has the computer (taken over): nothing ran; `output` says so.",
    )


class RunPython(BaseModel):
    code: str = Field(
        min_length=1,
        max_length=200_000,
        description="Python run on the computer's desktop (pyautogui and friends available); "
        "what it prints is returned.",
    )


class PythonResult(BaseModel):
    truncated: bool = False
    output: str
    taken_over: bool = Field(
        default=False,
        description="The user has the computer (taken over): nothing ran; `output` says so.",
    )


class Accessibility(BaseModel):
    xml: str = Field(description="The desktop's accessibility tree (AT-SPI) as XML.")


class FileWritten(BaseModel):
    path: str = Field(description="Where it was written on the computer.")
    size: int


def _computer_path(path: str) -> str:
    """A path on the computer: absolute under the user's home or /tmp, or relative to the
    Bot's workspace folder."""
    raw = path.strip().replace("\\", "/")
    full = posixpath.normpath(raw if raw.startswith("/") else f"{WORKSPACE}/{raw}")
    if not any(full == root or full.startswith(root + "/") for root in _FILE_ROOTS):
        raise OctopError.localized(ErrorCode.FORBIDDEN)
    return full


@router.post(
    "/{agent_id}/run",
    summary="Run a command on a Bot's cloud computer",
    description="Starts the computer if needed. While the user has taken it over nothing runs "
    "(`taken_over`). For a shadow Bot this is the desktop Bot's shell on its cloud computer.",
    response_model=CommandResult,
)
async def run_command(
    agent_id: str,
    body: RunCommand,
    user: User = Depends(desktop_remote_user),
    server: Any = Depends(get_server),
) -> CommandResult:
    manager = _owned(server, user, agent_id)
    with _slot(_command_counts, user.id):
        code = 1
        try:
            if await asyncio.to_thread(manager.taken_over, agent_id, user.id):
                return CommandResult(exit_code=code, output=TAKEN_OVER, taken_over=True)
            code, output = await asyncio.to_thread(
                manager.run, agent_id, user.id, body.command, body.timeout
            )
            output, truncated = _output(output)
            return CommandResult(exit_code=code, output=output, truncated=truncated)
        finally:
            _audit(server, user, agent_id, "computer.run", body.command, code)


@router.post(
    "/{agent_id}/python",
    summary="Run Python on a Bot's cloud computer desktop",
    description="Starts the computer if needed. The computer-use actions (click, type, wait, "
    "read elements) are made of these. While the user has taken it over nothing runs.",
    response_model=PythonResult,
)
async def run_python(
    agent_id: str,
    body: RunPython,
    user: User = Depends(desktop_remote_user),
    server: Any = Depends(get_server),
) -> PythonResult:
    manager = _owned(server, user, agent_id)
    with _slot(_command_counts, user.id):
        code = 1
        try:
            if await asyncio.to_thread(manager.taken_over, agent_id, user.id):
                return PythonResult(output=TAKEN_OVER, taken_over=True)
            result = await asyncio.to_thread(
                manager.use,
                agent_id,
                user.id,
                lambda driver, instance: driver.run_python(instance, body.code),
            )
            code = 0
            output, truncated = _output(str(result))
            return PythonResult(output=output, truncated=truncated)
        finally:
            _audit(server, user, agent_id, "computer.python", body.code, code)


@router.get(
    "/{agent_id}/screenshot",
    summary="Take a screenshot of a Bot's cloud computer",
    description="PNG of the whole screen. Starts the computer if needed.",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
async def screenshot(
    agent_id: str, user: User = Depends(desktop_remote_user), server: Any = Depends(get_server)
) -> Response:
    manager = _owned(server, user, agent_id)
    data = await asyncio.to_thread(
        manager.use, agent_id, user.id, lambda driver, instance: driver.screenshot(instance)
    )
    return Response(content=data, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get(
    "/{agent_id}/accessibility",
    summary="Read the accessibility tree of a Bot's cloud computer",
    description="The desktop's elements (names, roles, positions) as XML, e.g. to check a "
    "page before paying or another risky click. Starts the computer if needed.",
    response_model=Accessibility,
)
async def accessibility(
    agent_id: str, user: User = Depends(desktop_remote_user), server: Any = Depends(get_server)
) -> Accessibility:
    manager = _owned(server, user, agent_id)
    xml = await asyncio.to_thread(
        manager.use, agent_id, user.id, lambda driver, instance: driver.accessibility(instance)
    )
    return Accessibility(xml=str(xml))


@router.get(
    "/{agent_id}/files",
    summary="Read a file on a Bot's cloud computer",
    description="`path` is absolute under /home/user or /tmp, or relative to the Bot's "
    "workspace folder on the computer. Starts the computer if needed; 404 if there is no "
    "such file.",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def read_file(
    agent_id: str,
    path: str = Query(min_length=1, max_length=4096),
    user: User = Depends(desktop_remote_user),
    server: Any = Depends(get_server),
) -> Response:
    manager = _owned(server, user, agent_id)
    target = _computer_path(path)
    with _slot(_transfer_counts, user.id):
        code, size = await asyncio.to_thread(
            manager.run,
            agent_id,
            user.id,
            f"stat -Lc %s -- {shlex.quote(target)}",
            30,
        )
        if code != 0:
            raise OctopError.localized(ErrorCode.NOT_FOUND)
        if int(size.strip()) > MAX_FILE_BYTES:
            raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS, status=413)
        data = await asyncio.to_thread(
            manager.read, agent_id, user.id, target, max_bytes=MAX_FILE_BYTES + 1
        )
        if data is None:
            raise OctopError.localized(ErrorCode.NOT_FOUND)
        if len(data) > MAX_FILE_BYTES:
            raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS, status=413)
        return Response(content=data, media_type="application/octet-stream")


@router.put(
    "/{agent_id}/files",
    summary="Write a file on a Bot's cloud computer",
    description="The request body is the file's bytes (at most 50 MB); folders are made as "
    "needed. `path` as for reading. Starts the computer if needed.",
    response_model=FileWritten,
)
async def write_file(
    agent_id: str,
    request: Request,
    path: str = Query(min_length=1, max_length=4096),
    user: User = Depends(desktop_remote_user),
    server: Any = Depends(get_server),
) -> FileWritten:
    manager = _owned(server, user, agent_id)
    target = _computer_path(path)
    with _slot(_transfer_counts, user.id):
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_FILE_BYTES:
                raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS, status=413)
            data.extend(chunk)
        await asyncio.to_thread(manager.write, agent_id, user.id, target, bytes(data))
        return FileWritten(path=target, size=len(data))


@router.post(
    "/{agent_id}/screen",
    summary="Open a Bot's cloud computer screen",
    description="Starts or resumes the computer and returns a one-time WebSocket path that "
    "carries its desktop (RFB over WebSocket, for noVNC). The ticket is the only credential.",
    response_model=ScreenTicket,
)
async def open_screen(
    agent_id: str, user: User = Depends(desktop_remote_user), server: Any = Depends(get_server)
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
    holds = {"control": await asyncio.to_thread(manager.taken_over, agent_id, user_id)}

    async def input_allowed() -> bool:
        # View-only is a client setting; the relay itself holds input back until takeover.
        now = time.monotonic()
        if now - control["checked"] >= TAKEOVER_CHECK_SECONDS:
            control["allowed"] = await asyncio.to_thread(manager.taken_over, agent_id, user_id)
            control["checked"] = now
        return bool(control["allowed"])

    try:
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
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
    except Exception:  # noqa: BLE001 - the viewer just closes
        logger.warning("screen relay for %s ended with an error", agent_id, exc_info=True)
    finally:
        # Leaving the screen in control (closed tab, lost network, crash) hands the computer back.
        # Shielded: the relay task may be cancelled right as the viewer goes away, and a
        # hand-back skipped then would leave the computer taken over with nobody at the screen.
        if holds["control"]:

            def hand_back() -> None:
                if manager.taken_over(agent_id, user_id):
                    manager.set_takeover(agent_id, user_id, False)

            with contextlib.suppress(Exception, asyncio.CancelledError):
                await asyncio.shield(asyncio.to_thread(hand_back))
        with contextlib.suppress(Exception):
            await websocket.close()
