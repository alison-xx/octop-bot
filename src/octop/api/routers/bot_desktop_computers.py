"""Desktop-only, same-origin adapter for an owned Bot's cloud computer."""

from __future__ import annotations

import asyncio
import contextlib
import re
import secrets
import tempfile
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from typing import Annotated, Any, BinaryIO, Literal

import websockets
from fastapi import APIRouter, Depends, Header, Request, Response, WebSocket
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from websockets.typing import Subprotocol

from octop.api.common.bot_desktop import Owner, Services, screen_login
from octop.api.deps import extract_raw_token, get_server, resolve_user_from_token
from octop.api.routers.bot_cloud_account import (
    CloudLogin,
    CodeLogin,
    CodeRequest,
    CodeSent,
    _AccountRoute,
)
from octop.api.routers.bot_computers import (
    Clipboard,
    ComputerGlance,
    ComputerStatus,
    PasteRequest,
    TakeoverRequest,
)
from octop.infra.cloud.computers.remote import (
    MAX_FILE_BYTES,
    STARTUP_TIMEOUT,
    RemoteComputerManager,
    Target,
    reverify,
    set_target,
    transfer_path,
)
from octop.infra.cloud.computers.rfb import RfbClientFilter
from octop.infra.desktop import bot_cloud_origin
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.server import OctopServer

router = APIRouter(route_class=_AccountRoute)


class ComputerTarget(BaseModel):
    target: Target


@router.put("/bots/{agent_id}/computer-target", summary="Choose the computer for my desktop Bot")
async def choose_target(
    agent_id: str,
    body: ComputerTarget,
    user: Owner,
    services: Services,
    server: Any = Depends(get_server),
) -> ComputerTarget:
    return ComputerTarget(
        target=await set_target(
            services, server.app_runtime.agent_registry, user.id, agent_id, body.target
        )
    )


async def _owned(agent_id: str, user: Owner, services: Services) -> RemoteComputerManager:
    return await asyncio.to_thread(RemoteComputerManager.owned, services, user.id, agent_id)


Remote = Annotated[RemoteComputerManager, Depends(_owned)]


@router.get("/computers/{agent_id}", summary="Read my desktop Bot's cloud computer status")
async def status(remote: Remote) -> ComputerStatus:
    result = ComputerStatus.model_validate((await remote.computer("GET")).json())
    last = remote.activity()
    if result.state == "running" and last and last[1] >= (result.activity_at or 0):
        from octop.infra.cloud.computers.manager import BUSY_AFTER_ACTION_SECONDS

        result.activity, result.activity_at = last
        result.busy = result.busy or time.time() - last[1] < BUSY_AFTER_ACTION_SECONDS
    return result


@router.get(
    "/computers/{agent_id}/glance", summary="Preview my desktop Bot's running cloud computer"
)
async def glance(remote: Remote) -> ComputerGlance:
    return ComputerGlance.model_validate((await remote.computer("GET", "/glance")).json())


@router.post("/computers/{agent_id}/pause", summary="Pause my desktop Bot's cloud computer")
async def pause(remote: Remote) -> ComputerStatus:
    return ComputerStatus.model_validate((await remote.computer("POST", "/pause")).json())


@router.post(
    "/computers/{agent_id}/takeover",
    summary="Take over or hand back my desktop Bot's cloud computer",
)
async def takeover(body: TakeoverRequest, remote: Remote) -> ComputerStatus:
    response = await remote.computer("POST", "/takeover", json=body.model_dump())
    return ComputerStatus.model_validate(response.json())


@router.post("/computer-account/code", summary="Send a code to verify my account with the cloud")
async def send_code(user: Owner, services: Services, body: CodeRequest) -> CodeSent:
    return CodeSent.model_validate(await reverify(services, user.id, "code", body.model_dump()))


@router.post(
    "/computer-account/login", summary="Verify my cloud account with a password", status_code=204
)
async def password_login(user: Owner, services: Services, body: CloudLogin) -> None:
    await reverify(
        services,
        user.id,
        "login",
        {"account": body.account, "password": body.password.get_secret_value()},
    )


@router.post(
    "/computer-account/code-login", summary="Verify my cloud account with a code", status_code=204
)
async def code_login(user: Owner, services: Services, body: CodeLogin) -> None:
    await reverify(
        services,
        user.id,
        "code-login",
        {
            "target": body.target,
            "code": body.code.get_secret_value(),
            "password": body.password.get_secret_value() if body.password else None,
        },
    )


class DesktopScreenTicket(BaseModel):
    ws_path: str
    expires_in: int
    session: str = Field(description="Local header credential valid only for its open screen.")
    session_transport: Literal["header"] | None = None
    session_expires_in: int | None = None


@dataclass
class _Screen:
    remote: RemoteComputerManager
    expires: float
    path: str = field(repr=False)
    local_session: str = field(repr=False)
    cloud_session: str = field(repr=False)
    session_until: float
    server: OctopServer = field(repr=False)
    login_token: str = field(repr=False)
    logout: asyncio.Event = field(repr=False)

    async def check_owner(self) -> None:
        remote = self.remote
        try:
            user = await asyncio.to_thread(resolve_user_from_token, self.server, self.login_token)
        except OctopError:
            raise OctopError.localized(ErrorCode.NOT_FOUND) from None
        if self.logout.is_set() or user.id != remote.user_id:
            raise OctopError.localized(ErrorCode.NOT_FOUND)
        current = await asyncio.to_thread(
            RemoteComputerManager.owned, remote.services, remote.user_id, remote.agent_id
        )
        if current.binding != remote.binding:
            raise OctopError.localized(ErrorCode.NOT_FOUND)


_tickets: dict[str, _Screen] = {}
_active_sessions: dict[str, _Screen] = {}


@router.post(
    "/computers/{agent_id}/screen", summary="Start or resume my desktop Bot's cloud screen"
)
async def open_screen(
    remote: Remote,
    request: Request,
    server: Annotated[OctopServer, Depends(get_server)],
    response: Response,
    transport: Annotated[str, Header(alias="X-Octop-Screen-Transport")] = "",
) -> DesktopScreenTicket:
    login_token = extract_raw_token(authorization=request.headers.get("Authorization"))
    if not login_token:
        raise OctopError.localized(ErrorCode.MISSING_CREDENTIALS)
    logout = screen_login(request, remote.user_id)
    shadow = await remote.shadow()
    path = f"/api/octop-bot/computers/{shadow}/screen"
    requested = transport == "header"
    headers = {"X-Octop-Screen-Transport": "header"} if requested else {}
    body = (
        await remote._request("POST", path, headers=headers, timeout=STARTUP_TIMEOUT + 60)
    ).json()
    upstream = body.get("ws_path")
    if not isinstance(upstream, str) or not re.fullmatch(
        re.escape(path) + r"/ws\?ticket=[a-zA-Z0-9_-]{1,256}", upstream
    ):
        raise OctopError.localized(ErrorCode.NETWORK_ERROR)
    now = time.monotonic()
    for key, value in list(_tickets.items()):
        if value.expires <= now:
            del _tickets[key]
    if type(body.get("expires_in")) is not int or body["expires_in"] <= 0:
        raise OctopError.localized(ErrorCode.NETWORK_ERROR)
    ttl = min(body["expires_in"], 60)
    secure = requested and body.get("session_transport") == "header"
    cloud_session = body.get("session") if secure else ""
    if secure and (
        body.get("session_expires_in") != 1800
        or not isinstance(cloud_session, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", cloud_session)
    ):
        raise OctopError.localized(ErrorCode.NETWORK_ERROR)
    local_session = secrets.token_urlsafe(32) if secure else ""
    response.headers["Cache-Control"] = "no-store"
    key = secrets.token_urlsafe(32)
    claim = _Screen(
        remote,
        now + ttl,
        upstream,
        local_session,
        cloud_session,
        now + 1800,
        server,
        login_token,
        logout,
    )
    await claim.check_owner()
    _tickets[key] = claim
    return DesktopScreenTicket(
        ws_path=f"/api/octop-bot/computers/{remote.agent_id}/screen/ws?ticket={key}",
        expires_in=ttl,
        session=local_session,
        session_transport="header" if secure else None,
        session_expires_in=1800 if secure else None,
    )


@router.websocket("/computers/{agent_id}/screen/ws")
async def screen_ws(websocket: WebSocket, agent_id: str, ticket: str = "") -> None:
    claim = _tickets.pop(ticket, None)
    if not claim or claim.remote.agent_id != agent_id or time.monotonic() >= claim.expires:
        await websocket.close(code=4001)
        return

    async def watch() -> None:
        while not claim.logout.is_set():
            try:
                await asyncio.wait_for(claim.logout.wait(), timeout=1)
            except TimeoutError:
                await claim.check_owner()

    try:
        await claim.check_owner()
        url = (
            bot_cloud_origin().replace("https://", "wss://", 1).replace("http://", "ws://", 1)
            + claim.path
        )
        async with websockets.connect(
            url, subprotocols=[Subprotocol("binary")], max_size=8 * 1024 * 1024
        ) as upstream:
            if claim.local_session:
                _active_sessions[claim.local_session] = claim
            await websocket.accept(subprotocol="binary")

            async def down() -> None:
                async for frame in upstream:
                    if isinstance(frame, bytes):
                        await websocket.send_bytes(frame)

            async def up() -> None:
                legacy = None if claim.local_session else RfbClientFilter()
                async for frame in websocket.iter_bytes():
                    if legacy is not None:
                        frame, _ = legacy.feed(frame, allow_input=False)
                    if frame:
                        await upstream.send(frame)

            tasks = [asyncio.create_task(call()) for call in (down, up, watch)]
            try:
                lifetime = claim.session_until - time.monotonic() if claim.local_session else 3600
                async with asyncio.timeout(lifetime):
                    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                _active_sessions.pop(claim.local_session, None)
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    except Exception:
        pass  # A close is the protocol error. Transport errors can contain the ticket.
    finally:
        _active_sessions.pop(claim.local_session, None)
        with contextlib.suppress(Exception):
            await websocket.close()


async def _active_screen(
    user: Owner,
    services: Services,
    session: Annotated[str, Header(alias="X-Octop-Screen-Session")] = "",
) -> _Screen:
    claim = _active_sessions.get(session)
    if (
        not claim
        or claim.remote.user_id != user.id
        or claim.remote.services is not services
        or time.monotonic() >= claim.session_until
    ):
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    await claim.check_owner()
    if _active_sessions.get(session) is not claim:
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    return claim


ActiveScreen = Annotated[_Screen, Depends(_active_screen)]


@router.post("/screen-sessions/type", summary="Paste into my open cloud screen", status_code=204)
async def paste_text(screen: ActiveScreen, body: PasteRequest) -> None:
    await screen.remote._request(
        "POST",
        "/api/octop-bot/screen-sessions/type",
        screen_session=screen.cloud_session,
        json={"text": body.text},
    )


@router.get("/screen-sessions/clipboard", summary="Read my open cloud screen's clipboard")
async def read_clipboard(screen: ActiveScreen, response: Response) -> Clipboard:
    result = await screen.remote._request(
        "GET",
        "/api/octop-bot/screen-sessions/clipboard",
        screen_session=screen.cloud_session,
    )
    response.headers["Cache-Control"] = "no-store"
    return Clipboard.model_validate(result.json())


class RunCommand(BaseModel):
    command: str = Field(min_length=1, max_length=100_000)
    timeout: int = Field(default=120, ge=1, le=300)


class RunPython(BaseModel):
    code: str = Field(min_length=1, max_length=200_000)


class PythonResult(BaseModel):
    output: str
    taken_over: bool
    truncated: bool = False


class CommandResult(PythonResult):
    exit_code: int


@router.post("/computers/{agent_id}/run", summary="Run a command on my Bot's cloud computer")
async def run_command(remote: Remote, body: RunCommand) -> CommandResult:
    result = await remote.computer(
        "POST", "/run", json=body.model_dump(), timeout=body.timeout + 10
    )
    return CommandResult.model_validate(result.json())


@router.post(
    "/computers/{agent_id}/python", summary="Run a desktop action on my Bot's cloud computer"
)
async def run_python(remote: Remote, body: RunPython) -> PythonResult:
    result = await remote.computer("POST", "/python", json=body.model_dump(), timeout=310)
    return PythonResult.model_validate(result.json())


@router.get(
    "/computers/{agent_id}/screenshot",
    summary="Read my Bot's cloud screen as PNG",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
async def screenshot(remote: Remote) -> Response:
    result = await remote.computer("GET", "/screenshot")
    return Response(result.content, media_type="image/png", headers={"Cache-Control": "no-store"})


class Accessibility(BaseModel):
    xml: str


@router.get("/computers/{agent_id}/accessibility", summary="Read my Bot's cloud accessibility tree")
async def accessibility(remote: Remote) -> Accessibility:
    return Accessibility.model_validate((await remote.computer("GET", "/accessibility")).json())


class FileWritten(BaseModel):
    path: str
    size: int


_transfer_counts: dict[int, int] = {}


async def _transfer_spool(remote: Remote) -> AsyncIterator[BinaryIO]:
    uid = remote.user_id
    active = _transfer_counts.get(uid, 0)
    if active >= 2:
        raise OctopError.localized(ErrorCode.BOT_COMPUTER_TRANSFERS_BUSY)
    _transfer_counts[uid] = active + 1
    try:
        with tempfile.TemporaryFile() as spool:
            yield spool
    finally:
        _transfer_counts[uid] -= 1
        if not _transfer_counts[uid]:
            del _transfer_counts[uid]


TransferSpool = Annotated[BinaryIO, Depends(_transfer_spool)]


@router.put("/computers/{agent_id}/files", summary="Write a file to my Bot's cloud workspace")
async def put_file(
    remote: Remote, request: Request, path: str, spool: TransferSpool
) -> FileWritten:
    path = transfer_path(path)
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_FILE_BYTES:
            raise OctopError.localized(
                ErrorCode.ATTACHMENT_TOO_LARGE, details={"max_mb": 50}, max_mb=50
            )
        await asyncio.to_thread(spool.write, chunk)
    result = await remote.computer("PUT", "/files", params={"path": path}, source=spool)
    return FileWritten.model_validate(result.json())


@router.get(
    "/computers/{agent_id}/files",
    summary="Read a file from my Bot's cloud workspace",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def get_file(remote: Remote, path: str, spool: TransferSpool) -> StreamingResponse:
    await remote.computer(
        "GET",
        "/files",
        params={"path": transfer_path(path)},
        destination=spool,
        limit=MAX_FILE_BYTES,
    )
    await asyncio.to_thread(spool.seek, 0)

    def chunks() -> Iterator[bytes]:
        while chunk := spool.read(64 * 1024):
            yield chunk

    return StreamingResponse(
        chunks(),
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": "attachment",
            "X-Content-Type-Options": "nosniff",
        },
    )
