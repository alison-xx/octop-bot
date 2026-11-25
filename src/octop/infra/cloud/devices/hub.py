"""Owner-scoped desktop sessions and one-shot requests. A disconnected call is never replayed."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from octop.infra.cloud.devices.session import DeviceTickets
from octop.infra.cloud.devices.transfers import FileBytes

DeviceId = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{32}$")]


class LocalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["list", "read", "write", "run", "send_to_cloud", "fetch_from_cloud"]
    reason: str = Field(min_length=1, max_length=500)
    path: str = Field(default=".", min_length=1, max_length=1024)
    cloud_path: str = Field(default="", max_length=1024)
    command: str = Field(default="", max_length=4000)
    text: str = Field(default="", max_length=32_768)

    @model_validator(mode="after")
    def check_action(self) -> LocalRequest:
        if (self.action == "run") != bool(self.command.strip()):
            raise ValueError("run needs one complete command")
        if self.text and self.action != "write":
            raise ValueError("only write accepts text")
        if bool(self.cloud_path) != (self.action == "fetch_from_cloud"):
            raise ValueError("Only fetch_from_cloud takes a cloud_path.")
        return self


@dataclass
class LocalResult:
    message: str
    transfer: FileBytes | None = None


@dataclass
class Pending:
    id: str
    payload: dict[str, Any]
    result: asyncio.Future[LocalResult]
    download: FileBytes | None
    dispatched: bool = False


@dataclass
class DeviceSession:
    owner: int
    id: str
    label: str
    outgoing: asyncio.Queue[Pending] = field(default_factory=lambda: asyncio.Queue(maxsize=1))
    pending: Pending | None = None
    closed: asyncio.Event = field(default_factory=asyncio.Event)


class DeviceHub:
    """Owned by one AgentManager. All state changes run on the server's event loop."""

    def __init__(self) -> None:
        self.tickets = DeviceTickets()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._devices: dict[tuple[int, str], DeviceSession] = {}

    def connect(self, owner: int, device_id: str, label: str) -> DeviceSession:
        self._loop = asyncio.get_running_loop()
        key = (owner, device_id)
        old = self._devices.get(key)
        if old:
            self.disconnect(old)
        session = DeviceSession(owner, device_id, label)
        self._devices[key] = session
        return session

    def disconnect(self, session: DeviceSession) -> None:
        if self._devices.get((session.owner, session.id)) is session:
            self._devices.pop((session.owner, session.id))
        session.closed.set()
        if session.pending and not session.pending.result.done():
            session.pending.result.set_result(
                LocalResult("Device disconnected. Verify the result before retrying.")
            )

    def online(self, owner: int) -> dict[str, str]:
        return {s.id: s.label for s in self._devices.copy().values() if s.owner == owner}

    async def request(
        self,
        owner: int,
        device_id: str,
        bot_name: str,
        request: LocalRequest,
        *,
        download: FileBytes | None = None,
        destination: str = "",
    ) -> LocalResult:
        loop = self._loop
        if loop is not None and not loop.is_closed() and loop is not asyncio.get_running_loop():
            # A synchronous harness caller can run its tools on a worker event loop.
            task = asyncio.run_coroutine_threadsafe(
                self.request(
                    owner, device_id, bot_name, request, download=download, destination=destination
                ),
                loop,
            )
            return await asyncio.wrap_future(task)
        session = self._devices.get((owner, device_id))
        if session is None or (loop is not None and loop.is_closed()):
            return LocalResult("This device is offline. Ask the user to connect it.")
        if session.pending is not None or session.outgoing.full():
            return LocalResult("The device is waiting for another local decision.")
        call = Pending(
            secrets.token_urlsafe(18),
            {
                "bot": bot_name,
                **request.model_dump(),
                "size": download.size if download else None,
                "destination": destination,
            },
            asyncio.get_running_loop().create_future(),
            download,
        )
        session.pending = call
        session.outgoing.put_nowait(call)
        try:
            async with asyncio.timeout(120):
                return await call.result
        except TimeoutError:
            return LocalResult(
                "Timed out waiting for the desktop. Verify the result before retrying."
            )
        finally:
            session.pending = None
            if not session.outgoing.empty():
                session.outgoing.get_nowait()

    def answer(self, session: DeviceSession, request_id: str, result: LocalResult) -> None:
        call = session.pending
        if call and call.id == request_id and not call.result.done():
            if result.transfer is not None and (
                not call.dispatched or call.payload["action"] != "send_to_cloud"
            ):
                result = LocalResult("Unexpected file content.")
            call.result.set_result(result)
