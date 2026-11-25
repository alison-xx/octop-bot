"""Ordinary owner-scoped pairing, consent, file transfer and disconnect flows."""

import asyncio

import pytest

from octop.infra.cloud.devices.hub import DeviceHub, LocalRequest, LocalResult
from octop.infra.cloud.devices.transfers import FileBytes, fetch_file, inbound_path


@pytest.mark.asyncio
async def test_reconnect_finishes_old_call_without_replaying_it() -> None:
    hub = DeviceHub()
    session = hub.connect(7, "office", "Desktop")
    assert hub.online(8) == {}
    request = LocalRequest(action="list", reason="List the selected project")
    result = asyncio.create_task(hub.request(7, "office", "Clerk", request))
    await session.outgoing.get()
    new = hub.connect(7, "office", "Desktop")
    assert session.closed.is_set()
    assert "disconnected" in (await result).message
    assert new.pending is None and new.outgoing.empty()
    hub.disconnect(session)
    assert hub.online(7) == {"office": "Desktop"}


@pytest.mark.asyncio
async def test_local_file_reaches_cloud_only_after_approval() -> None:
    hub = DeviceHub()
    session = hub.connect(8, "studio", "My computer")
    request = LocalRequest(action="send_to_cloud", reason="Send my sample file", path="说明.txt")
    task = asyncio.create_task(
        hub.request(8, "studio", "Editor", request, destination=inbound_path(request.path))
    )
    call = await session.outgoing.get()
    assert call.payload["destination"].endswith("/说明.txt")
    assert not call.dispatched
    call.dispatched = True
    content = b"test document"
    hub.answer(session, call.id, LocalResult("sent", FileBytes.encode(content)))
    result = await task
    assert result.transfer is not None and result.transfer.decode() == content


@pytest.mark.asyncio
async def test_fetch_requests_a_bounded_workspace_read() -> None:
    class Workspace:
        async def adownload_bytes_capped(self, path: str, max_bytes: int) -> bytes:
            assert path == "outbound/summary.csv"
            assert max_bytes == 1024 * 1024
            return b"item,total\na,5"

    transfer = await fetch_file(Workspace(), "outbound/summary.csv")
    assert transfer.decode() == b"item,total\na,5"


def test_native_ticket_is_bound_to_one_device_connection() -> None:
    hub = DeviceHub()
    token = hub.tickets.issue(4, "desktop", "Office")
    pair = hub.tickets.consume(token)
    assert pair and (pair.owner, pair.device_id) == (4, "desktop")
    assert hub.tickets.consume(token) is None
