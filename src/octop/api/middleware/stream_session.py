"""End authenticated WebSockets when the account or its session is no longer valid."""

from __future__ import annotations

import asyncio
from typing import Any

import anyio
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from octop.api.common.stream_auth import StreamSession


class StreamSessionMiddleware:
    def __init__(self, app: ASGIApp, server: Any) -> None:
        self.app = app
        self.server = server

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "websocket":
            await self.app(scope, receive, send)
            return

        state = scope.setdefault("state", {})
        revoked = False
        closed = False

        async def tracked_send(message: Message) -> None:
            nonlocal closed
            if message["type"] == "websocket.close":
                closed = True
            await send(message)

        async with anyio.create_task_group() as group:

            async def check() -> None:
                nonlocal revoked
                session: StreamSession | None = state.get("stream_session")
                if session is not None and not await asyncio.to_thread(session.active, self.server):
                    revoked = True
                    group.cancel_scope.cancel()
                    await anyio.lowlevel.checkpoint()

            async def watch() -> None:
                while True:
                    await anyio.sleep(2)
                    await check()

            async def checked_receive() -> Message:
                message = await receive()
                if message["type"] == "websocket.receive" and scope["path"].endswith("/chat/ws"):
                    await check()
                return message

            group.start_soon(watch)
            try:
                await self.app(scope, checked_receive, tracked_send)
            finally:
                group.cancel_scope.cancel()

        if revoked and not closed:
            await send({"type": "websocket.close", "code": 4001})
