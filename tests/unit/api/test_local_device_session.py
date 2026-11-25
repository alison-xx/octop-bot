"""A signed-in desktop pairs, confirms one named operation, and signs out."""

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from octop.api.deps import current_user, get_server
from octop.api.routers import bot_devices
from octop.infra.cloud.devices.hub import DeviceHub, LocalRequest


def test_pair_and_confirm_a_single_local_operation(monkeypatch: Any) -> None:
    hub = DeviceHub()
    registry = SimpleNamespace(local_devices=hub)
    server = SimpleNamespace(app_runtime=SimpleNamespace(agent_registry=registry))
    account = SimpleNamespace(id=7, is_admin=False)
    monkeypatch.setattr(bot_devices, "bot_cloud_enabled", lambda: True)
    app = FastAPI()
    app.include_router(bot_devices.router, prefix="/api/octop-bot")
    app.state.octop_server = server
    app.dependency_overrides[get_server] = lambda: server
    app.dependency_overrides[current_user] = lambda: account
    device_id = "1" * 32
    with TestClient(app) as client:
        ticket = client.post(
            "/api/octop-bot/local-devices/ticket", json={"device_id": device_id, "label": "Office"}
        )
        assert ticket.status_code == 200 and ticket.json()["owner"] == 7
        with client.websocket_connect("/api/octop-bot/local-devices/ws") as ws:
            ws.send_text(ticket.json()["ticket"])
            assert ws.receive_json() == {"kind": "connected"}

            async def wait_for_connection() -> None:
                async with asyncio.timeout(3):
                    while not hub.online(7):
                        await asyncio.sleep(0.01)

            assert client.portal
            client.portal.call(wait_for_connection)
            request = LocalRequest(action="list", reason="List the selected sample folder")
            future = client.portal.start_task_soon(hub.request, 7, device_id, "Editor", request)
            card = ws.receive_json()
            assert card["kind"] == "request" and card["action"] == "list"
            ws.send_json({"kind": "ready", "id": card["id"]})
            assert ws.receive_json() == {"kind": "execute", "id": card["id"], "transfer": None}
            ws.send_json({"kind": "result", "id": card["id"], "result": "sample.txt"})
            assert future.result(3).message == "sample.txt"
        assert hub.online(7) == {}


def test_tool_available_only_to_own_private_dashboard_chat(monkeypatch: Any) -> None:
    from octop.infra.cloud.devices.tools import LocalDesktopTools

    row = SimpleNamespace(user_id=7, agent_id="editor", channel_type="dashboard")
    middleware = LocalDesktopTools(
        DeviceHub(),
        7,
        "Editor",
        "editor",
        Mock(get=lambda _: row),
        lambda: None,
        Mock(),
    )
    assert middleware._allowed("chat-a")
    row.channel_type = "bot_group"
    assert not middleware._allowed("chat-a")
    row.channel_type, row.user_id = "dashboard", 8
    assert not middleware._allowed("chat-a")


def test_local_tool_roster_names_the_id_even_when_labels_match() -> None:
    from langchain.agents.middleware import ModelRequest
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from octop.infra.cloud.devices.tools import LocalDesktopTools

    hub = Mock(spec=DeviceHub)
    hub.online.return_value = {"a" * 32: "Office", "b" * 32: "Office"}
    middleware = LocalDesktopTools(hub, 7, "Editor", "editor", Mock(), lambda: None, Mock())
    schema = middleware.tools[0].get_input_schema().model_json_schema()
    assert schema["properties"]["device_id"]["pattern"] == "^[a-f0-9]{32}$"
    request = ModelRequest(model=FakeListChatModel(responses=["ok"]), messages=[], tools=[])
    scope = middleware._scope(request, "local")
    assert scope.system_message
    content = scope.system_message.content_blocks[-1]["text"]
    roster = json.loads(content[content.index("{") :])
    assert roster["devices"] == [
        {"device_id": "a" * 32, "display_name": "Office"},
        {"device_id": "b" * 32, "display_name": "Office"},
    ]


def test_offline_card_rechecks_presence_and_never_dispatches_an_operation() -> None:
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.func import entrypoint
    from langgraph.types import Command

    from octop.infra.cloud.devices.tools import device_wait_tool

    hub = Mock(spec=DeviceHub)
    user_repo = Mock(get=lambda _: SimpleNamespace(locale="zh"))
    tool = device_wait_tool(hub, 7, lambda thread: thread == "owner-thread", user_repo)

    @entrypoint(checkpointer=InMemorySaver())
    def graph(_: str) -> str:
        return tool.invoke({})

    config = {"configurable": {"thread_id": "owner-thread"}}
    for selected, connected, expected in [
        ("已连接，继续", False, "still offline"),
        ("结束这一步", True, "stopped"),
        ("已连接，继续", True, "resumed"),
    ]:
        hub.online.return_value = {}
        pending = graph.invoke("wait", config)["__interrupt__"][0]
        assert pending.value["action_requests"][0]["args"]["local_device_wait"]
        if connected:
            hub.online.return_value = {"sample": "Test desktop"}
        result = graph.invoke(
            Command(resume={"decisions": [{"type": "respond", "message": selected}]}), config
        )
        assert expected in result
    hub.request.assert_not_called()
