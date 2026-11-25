"""Cap the request body on a few public write paths.

FastAPI reads a whole body before any route or dependency runs (and turns errors while reading
it into a 400), so a limit there comes too late: this ASGI middleware refuses a too-large
``Content-Length`` up front, and otherwise reads the body itself, stopping as soon as it passes
the limit (chunked, or lying about its length), then hands the app the same body. Answers 413
``REQUEST_TOO_LARGE``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.locale import resolve_request_locale

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]

MB = 1024 * 1024
# Path prefix → largest body in bytes.
LIMITS: tuple[tuple[str, int], ...] = (
    # Desktop apps moving their Bots, chats and groups in: one item per request.
    ("/api/octop-bot/move-in/", 10 * MB),
)


def _response(scope: Scope, limit: int) -> JSONResponse:
    error = OctopError.localized(ErrorCode.REQUEST_TOO_LARGE, limit_mb=limit // MB)
    return JSONResponse(
        status_code=413, content=error.to_envelope(locale=resolve_request_locale(Request(scope)))
    )


class BodyLimit:
    def __init__(self, app: Any, limits: tuple[tuple[str, int], ...] = LIMITS) -> None:
        self.app = app
        self.limits = limits

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit = None
        if scope["type"] == "http":
            path = str(scope.get("path") or "")
            limit = next((size for prefix, size in self.limits if path.startswith(prefix)), None)
        if limit is None:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length", b"").decode("latin-1").strip()
        if declared.isdigit() and int(declared) > limit:
            await _response(scope, limit)(scope, receive, send)
            return
        # Read it here (it is small enough to hold), then hand the app the same body.
        buffered = bytearray()
        while True:
            message = await receive()
            if message.get("type") != "http.request":
                return  # The client disconnected before sending the entire body.
            chunk = message.get("body") or b""
            if len(buffered) + len(chunk) > limit:
                await _response(scope, limit)(scope, receive, send)
                return
            buffered.extend(chunk)
            if not message.get("more_body"):
                break
        body = bytes(buffered)
        del buffered
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def install(app: Any) -> None:
    app.add_middleware(BodyLimit)
