"""Phone-run device tools: spec, visibility per thread, and the respond round trip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from octop.infra.agents.bot_device import (
    UNAVAILABLE,
    DeviceTools,
    device_interrupts,
    device_specs,
    device_tool_names,
    device_tools,
    remember_device_tools,
    thread_device_tools,
)

REPO = Path(__file__).resolve().parents[3]


def test_spec_names_capabilities_and_schemas():
    names = device_tool_names()
    assert names == {
        "device_health_summary",
        "device_calendar_events",
        "device_calendar_create_event",
        "device_calendar_update_event",
        "device_reminders",
        "device_reminder_create",
    }
    for spec in device_specs():
        assert spec["capability"] in {"health", "calendar", "reminders"}
        assert isinstance(spec["writes"], bool)
        assert spec["parameters"]["type"] == "object"
        assert set(spec["parameters"].get("required", [])) <= set(spec["parameters"]["properties"])


def test_mobile_copies_match_the_server_spec():
    server = (REPO / "src/octop/infra/agents/device_tools.json").read_text(encoding="utf-8")
    for copy in (
        "mobile/ios/OctopBot/Resources/device_tools.json",
        "mobile/android/app/src/main/assets/device_tools.json",
    ):
        assert json.loads((REPO / copy).read_text(encoding="utf-8")) == json.loads(server), copy


def test_tools_without_a_phone_say_so():
    tool = next(t for t in device_tools() if t.name == "device_reminder_create")
    assert tool.invoke({"title": "交报告"}) == UNAVAILABLE
    assert tool.tool_call_schema["required"] == ["title"]


def test_interrupts_never_allow_a_plain_approve():
    gates = device_interrupts()
    assert set(gates) == device_tool_names()
    assert all(g["allowed_decisions"] == ["respond", "reject"] for g in gates.values())


def test_remember_keeps_only_known_tools_and_clears():
    remember_device_tools("t-remember", ["device_reminders", "rm_rf"])
    assert thread_device_tools("t-remember") == {"device_reminders"}
    remember_device_tools("t-remember", None)
    assert thread_device_tools("t-remember") == frozenset()


ADVERTISED: list[set[str]] = []


class _Model(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        ADVERTISED.append({t.name if hasattr(t, "name") else t.get("name") for t in tools})
        return self


@pytest.mark.asyncio
async def test_phone_answers_in_place_of_the_tool():
    from deepagents import create_deep_agent

    ADVERTISED.clear()
    msg = {"messages": [{"role": "user", "content": "这周睡得怎么样"}]}

    hidden = create_deep_agent(
        model=_Model(responses=[AIMessage(content="OK")]), middleware=[DeviceTools()]
    )
    remember_device_tools("t-desktop", None)
    await hidden.ainvoke(msg, {"configurable": {"thread_id": "t-desktop"}})
    assert not device_tool_names() & ADVERTISED[-1]

    call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "device_health_summary",
                "id": "health-1",
                "args": {"metrics": ["sleep_hours"], "days": 7},
            }
        ],
    )
    agent = create_deep_agent(
        model=_Model(responses=[call, AIMessage(content="平均 7 小时")]),
        middleware=[DeviceTools()],
        checkpointer=InMemorySaver(),
    )
    remember_device_tools("t-phone", ["device_health_summary"])
    config = {"configurable": {"thread_id": "t-phone"}}
    paused = await agent.ainvoke(msg, config)
    assert ADVERTISED[-1] & device_tool_names() == {"device_health_summary"}
    request = paused["__interrupt__"][0].value
    assert request["action_requests"][0]["name"] == "device_health_summary"
    assert request["review_configs"][0]["allowed_decisions"] == ["respond", "reject"]

    result_json = json.dumps({"days": [{"date": "2026-11-24", "sleep_hours": 7.1}]})
    done = await agent.ainvoke(
        Command(resume={"decisions": [{"type": "respond", "message": result_json}]}), config
    )
    tool_message = next(m for m in done["messages"] if isinstance(m, ToolMessage))
    assert tool_message.content == result_json
    assert done["messages"][-1].content == "平均 7 小时"
    remember_device_tools("t-phone", None)
