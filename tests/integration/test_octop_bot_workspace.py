"""Octop Bot uses the authenticated owner's existing agents, chats and tools."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from octop.infra.agents.bot_tools import chief_tools
from octop.infra.db.repos.thread_messages import ThreadMessageInput
from octop.infra.errors import OctopError


async def test_private_folder_survives_deletion_until_owner_releases_reservation(env_with_agent):
    from octop.infra.agents.bot_privacy import PrivateDirectoryGuard

    client, server, auth, bot = env_with_agent
    registry = server.app_runtime.agent_registry
    workspace = registry.resolve_workspace_dir(bot)
    asset = workspace / "existing-note.txt"
    asset.write_text("draft", encoding="utf-8")
    api = "/api/octop-bot"
    response = await client.put(f"{api}/bots/{bot}/privacy", headers=auth, json={"private": True})
    response.raise_for_status()
    deletion = await client.delete(f"/api/agents/{bot}", headers=auth)
    deletion.raise_for_status()
    assert asset.read_text(encoding="utf-8") == "draft"
    retained = (await client.get(f"{api}/retained-folders", headers=auth)).json()
    assert [(r["agent_id"], Path(r["path"])) for r in retained] == [(bot, workspace)]
    guard = PrivateDirectoryGuard(
        server.services.settings_repo, "another-bot", workspace.parent, None
    )
    call = {"name": "read_file", "args": {"file_path": str(asset)}}
    with pytest.raises(OctopError):
        guard.check(call)
    released = await client.delete(f"{api}/retained-folders/{bot}", headers=auth)
    released.raise_for_status()
    guard.check(call)
    assert asset.read_text(encoding="utf-8") == "draft"


async def test_chief_creates_group_and_workspace_is_user_scoped(env_admin_alice):
    client, server, admin, alice = env_admin_alice
    route = "/api/octop-bot/workspace"
    first, repeated = await asyncio.gather(*(client.get(route, headers=admin) for _ in range(2)))
    first.raise_for_status()
    repeated.raise_for_status()
    chief = first.json()["chief_id"]
    assert repeated.json()["chief_id"] == chief
    assert sum(bot["is_main"] for bot in first.json()["bots"]) == 1
    registry = server.app_runtime.agent_registry
    owner = registry.get_row(chief).user_id
    tools = {t.name: t for t in chief_tools(registry, server.services, chief, owner)}
    config = {"configurable": {"user": str(owner), "agent_id": chief, "octop_bot_browser": True}}
    copywriter = await tools["octop_bot_create"].ainvoke(
        {"name": "文案", "instructions": "撰写自媒体文案"}, config=config
    )
    group = await tools["octop_bot_create_group"].ainvoke(
        {"name": "自媒体群组", "admin_id": chief, "member_ids": [copywriter]}, config=config
    )
    workspace = (await client.get(route, headers=admin)).json()
    assert workspace["groups"] == [group]
    assert {chief, copywriter} <= {bot["agent_id"] for bot in workspace["bots"]}
    other = (await client.get(route, headers=alice)).json()
    assert other["chief_id"] != chief
    assert other["groups"] == []
    with pytest.raises(OctopError):
        await tools["octop_bot_roster"].ainvoke(
            {}, config={"configurable": {"agent_id": other["chief_id"], "user": str(owner)}}
        )


async def test_real_agent_graph_exposes_chief_tools_only_in_bot_chat(env_with_provider):
    from deepagents import create_deep_agent
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

    from octop.infra.agents.middleware.bot_workspace import BotWorkspaceTools

    client, server, auth = env_with_provider
    workspace = (await client.get("/api/octop-bot/workspace", headers=auth)).json()
    chief = workspace["chief_id"]
    manager = server.app_runtime.agent_registry
    row = manager.get_row(chief)
    cfg = manager._build_harness_config(row)
    middleware = next(m for m in cfg.middleware if isinstance(m, BotWorkspaceTools))
    advertised = []

    class Model(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            advertised.append({t.name if hasattr(t, "name") else t.get("name") for t in tools})
            return self

    msg = {"messages": [{"role": "user", "content": "帮我创建一个自媒体群组"}]}
    plain = create_deep_agent(
        model=Model(responses=[AIMessage(content="OK")]), middleware=[middleware]
    )
    await plain.ainvoke(msg, {"configurable": {"thread_id": "plain", "user": str(row.user_id)}})
    assert advertised and "octop_bot_create_group" not in advertised[-1]
    assert "octop_bot_sections" not in advertised[-1]
    call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "octop_bot_create_group",
                "id": "create-once",
                "args": {"name": "自媒体", "admin_id": chief, "member_ids": []},
            }
        ],
    )
    native = create_deep_agent(
        model=Model(responses=[call, AIMessage(content="完成")]), middleware=[middleware]
    )
    result = await native.ainvoke(
        msg,
        {
            "configurable": {
                "thread_id": "bot",
                "user": str(row.user_id),
                "agent_id": chief,
                "octop_bot_browser": True,
            }
        },
    )
    assert "octop_bot_create_group" in advertised[-1]
    assert result["messages"][-1].content == "完成"
    refreshed = (await client.get("/api/octop-bot/workspace", headers=auth)).json()
    assert [g["name"] for g in refreshed["groups"]] == ["自媒体"]
    group_id = refreshed["groups"][0]["group_id"]
    organize = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "octop_bot_sections",
                "id": "file-once",
                "args": {"action": "create", "section": "内容工作", "group_ids": [group_id]},
            }
        ],
    )
    native = create_deep_agent(
        model=Model(responses=[organize, AIMessage(content="已整理")]), middleware=[middleware]
    )
    result = await native.ainvoke(
        {"messages": [{"role": "user", "content": "把自媒体群放在内容工作分组"}]},
        {
            "configurable": {
                "thread_id": "sidebar",
                "user": str(row.user_id),
                "agent_id": chief,
                "octop_bot_browser": True,
            }
        },
    )
    assert "octop_bot_sections" in advertised[-1]
    receipt = json.loads(result["messages"][-2].content)
    assert receipt["changed"] and receipt["action"] == "create"
    workspace = (await client.get("/api/octop-bot/workspace", headers=auth)).json()
    assert workspace["sections"][0]["items"] == [f"group:{group_id}"]
    assert workspace["revision"] == receipt["revision"]


async def test_side_snapshot_does_not_append_and_private_chats_are_unreferenceable(
    env_with_agent, monkeypatch
):
    client, server, auth, agent = env_with_agent
    services = server.services
    registry = server.app_runtime.agent_registry
    owner = registry.get_row(agent).user_id
    thread = "bot-snapshot"
    services.thread_repo.insert(
        thread_id=thread,
        agent_id=agent,
        user_id=owner,
        channel_type="dashboard",
        session_key="bot-snapshot",
        title="选题草稿",
    )
    messages = [
        ThreadMessageInput("one", "human", json.dumps({"data": {"content": "科技选题"}}), 1),
        ThreadMessageInput("two", "ai", json.dumps({"data": {"content": "财经选题"}}), 2),
    ]
    repo = services.thread_message_repo
    repo.replace_all(thread, messages)
    base = "/api/octop-bot"
    matches = (
        await client.get(base + "/history/search", params={"q": "财经"}, headers=auth)
    ).json()
    assert [m["thread_id"] for m in matches] == [thread]

    answer = AsyncMock(return_value=AIMessage(content="科技"))
    monkeypatch.setattr(registry, "get_thread_model", lambda *_: "openai:gpt-4o")
    monkeypatch.setattr(
        registry.host_models,
        "get",
        lambda model: SimpleNamespace(chat_model=SimpleNamespace(ainvoke=answer), model_ref=model),
    )
    response = await client.post(
        f"{base}/bots/{agent}/side",
        headers=auth,
        json={"thread_id": thread, "question": "之前的主题？", "snapshot_seq": 1},
    )
    response.raise_for_status()
    assert response.json() == {"answer": "科技", "snapshot_seq": 1}
    prompt = json.loads(answer.await_args.args[0][1].content)
    assert [m["text"] for m in prompt["conversation"]] == ["科技选题"]
    assert repo.head(thread) == 2

    privacy = await client.put(f"{base}/bots/{agent}/privacy", headers=auth, json={"private": True})
    privacy.raise_for_status()
    assert privacy.json()["is_private"]
    assert (
        await client.get(base + "/history/search", params={"q": "财经"}, headers=auth)
    ).json() == []
    reference = await client.post(
        f"{base}/bots/{agent}/reference", headers=auth, json={"thread_id": thread}
    )
    assert reference.status_code == 403


async def test_legacy_personal_chat_quotes_keep_the_native_compaction_anchors(
    env_with_agent, monkeypatch
):
    from octop_gateway.models import ChannelSubject, InboundMessage, TextContent

    from octop.infra.agents import bot_side

    client, server, auth, agent = env_with_agent
    services = server.services
    registry = server.app_runtime.agent_registry
    uid = registry.get_row(agent).user_id
    tid = "old-personal-chat"
    services.thread_repo.insert(
        thread_id=tid,
        agent_id=agent,
        user_id=uid,
        channel_type="dashboard",
        session_key=tid,
    )
    first = "  早先的原话 <think>是用户输入</think>  "
    originals = [HumanMessage(content=first), AIMessage(content="也留下原话", id="two")]
    originals.extend(AIMessage(content=f"后来第 {i} 条", id=f"item-{i}") for i in range(100))
    harness = registry.get_agent(agent)
    harness.seed_thread_messages(tid, originals)
    repo = services.thread_message_repo
    repo.mark_projection(tid, "pending")
    root = "/api/octop-bot"
    query = {"q": "原话", "with_status": "true"}
    initial = await client.get(f"{root}/history/search", params=query, headers=auth)
    initial.raise_for_status()
    assert initial.json()["indexing"]
    async with asyncio.timeout(5):
        while repo.projection_status(tid) != "ready":
            await asyncio.sleep(0.01)

    # The harness emits this state update both when it compacts and when it replays a checkpoint.
    update = {
        "type": "state_update",
        "data": {"_summarization_event": {"cutoff_message_id": "two"}},
    }
    harness.chunks = [update, update, {"type": "token", "content": "已经接上"}]
    inbound = InboundMessage(
        channel_id="octop-ws",
        channel_type="dashboard",
        tenant_id=agent,
        channel_subject=ChannelSubject(subject_id=str(uid)),
        content=[TextContent(text="继续")],
        metadata={"thread_id": tid, "session_key": tid, "octop_bot_browser": True},
    )
    chunks = [
        chunk async for chunk in server.app_runtime.gateway.processor.iter_turn_chunks(inbound)
    ]
    assert any(chunk.get("content") == "已经接上" for chunk in chunks), chunks
    assert repo.head(tid) == len(originals) + 2
    found = (await client.get(f"{root}/history/search", params=query, headers=auth)).json()[
        "matches"
    ]
    assert [(r["message_id"], r["message_seq"], r["part"]) for r in found] == [
        ("two", 2, 2),
        (None, 1, 1),
    ]
    quote_url = f"{root}/bots/{agent}/reference"
    for anchor, expected in zip(found, ("也留下原话", first), strict=True):
        ref = await client.post(quote_url, headers=auth, json=anchor)
        ref.raise_for_status()
        assert ref.json()["text"] == expected
    stale = await client.post(
        quote_url, headers=auth, json={"thread_id": tid, "message_seq": 1, "message_id": "missing"}
    )
    assert stale.status_code == 404
    legacy = await client.post(quote_url, headers=auth, json={"thread_id": tid})
    assert "后来第 99 条" in legacy.json()["text"]

    config = {
        "configurable": {
            "user": str(uid),
            "agent_id": agent,
            "thread_id": tid,
            "octop_bot_browser": True,
        }
    }
    monkeypatch.setattr(bot_side, "get_config", lambda: config)
    tool = bot_side.own_chat_tool(services, agent, uid)
    assert tool.invoke({"query": "原话"})["messages"] == found
    assert tool.invoke({"message_seq": 1})["text"] == first
    config["configurable"]["user"] = str(uid + 1)
    with pytest.raises(OctopError):
        tool.invoke({"message_seq": 1})


async def test_group_attachment_stays_in_its_room_and_reaches_the_member(
    env_admin_alice, monkeypatch
):
    client, server, admin, alice = env_admin_alice
    root = "/api/octop-bot"
    chief = (await client.get(f"{root}/workspace", headers=admin)).json()["chief_id"]
    response = await client.post(
        f"{root}/groups", headers=admin, json={"name": "室内", "admin_id": chief}
    )
    response.raise_for_status()
    group = response.json()["group_id"]
    room = f"{root}/groups/{group}"
    name = "会议记录.txt"
    files = {"file": (name, b"first", "text/plain")}
    first, other = await asyncio.gather(
        client.post(room + "/files", files=files, headers=admin),
        client.post(
            room + "/files", files={"file": (name, b"second", "text/plain")}, headers=admin
        ),
    )
    assert first.status_code == other.status_code == 201
    path = first.json()["path"]
    assert path != other.json()["path"]
    downloaded = await client.get(room + "/file", params={"path": path}, headers=admin)
    assert (
        downloaded.content == b"first"
        and "filename*=UTF-8''" in downloaded.headers["content-disposition"]
    )
    assert (await client.post(room + "/files", files=files, headers=alice)).status_code == 404
    assert (
        await client.get(room + "/file", params={"path": path}, headers=alice)
    ).status_code == 404
    assert (
        await client.post(room + "/files", files={"file": ("../escape.txt", b"x")}, headers=admin)
    ).status_code == 400
    monkeypatch.setattr(type(server.services.config), "max_upload_bytes", property(lambda self: 3))
    assert (await client.post(room + "/files", files=files, headers=admin)).status_code == 413

    seen = []

    async def stream(msg):
        seen.append(msg.text)
        yield {"type": "token", "content": "OK"}

    monkeypatch.setattr(server.app_runtime.gateway.processor, "iter_turn_chunks", stream)
    request = {"request_id": "only-file", "attachment_paths": [path]}
    denied = await client.post(
        room + "/messages", json={**request, "attachment_paths": [".octop/config"]}, headers=admin
    )
    assert denied.status_code == 403
    result = await client.post(room + "/messages", json=request, headers=admin)
    result.raise_for_status()
    messages = result.json()
    assert [m["attachment_paths"] for m in messages] == [[path], []]
    assert messages[0]["text"] == "" and messages[1]["text"] == "OK"
    assert len(seen) == 1 and path in seen[0]
    replay = await client.post(room + "/messages", json=request, headers=admin)
    assert replay.json() == messages and len(seen) == 1
    assert (await client.get(room + "/messages", headers=admin)).json() == messages


async def test_bot_config_mounts_phone_tools_behind_the_phone(env_with_agent):
    from octop.api.routers.chat.models import UserTurnWsFrame
    from octop.infra.agents.bot_device import DeviceTools, device_tool_names

    _client, server, _auth, bot = env_with_agent
    manager = server.app_runtime.agent_registry
    cfg = manager._build_harness_config(manager.get_row(bot))
    gate = next(m for m in cfg.middleware if isinstance(m, DeviceTools))
    assert {t.name for t in gate.tools} == device_tool_names()
    # Not in interrupt_on: harness drops that before onboarding, and "approve all" would skip it.
    assert not device_tool_names() & set(cfg.interrupt_on or {})
    turn = UserTurnWsFrame(
        text="明天下午三点开会", thread_id="t1", device_tools=["device_calendar_create_event"]
    ).to_turn_body()
    assert turn.device_tools == ["device_calendar_create_event"]


async def test_bots_get_the_task_contract_on_bot_chat_turns(env_with_provider):
    from octop.infra.agents.middleware.bot_workspace import BotWorkspaceTools
    from octop.infra.bot_tasks.watchdog import BotTaskMiddleware

    client, server, auth = env_with_provider
    chief = (await client.get("/api/octop-bot/workspace", headers=auth)).json()["chief_id"]
    manager = server.app_runtime.agent_registry
    cfg = manager._build_harness_config(manager.get_row(chief))
    tools = next(m for m in cfg.middleware if isinstance(m, BotWorkspaceTools))
    # Shown on Octop Bot client turns (a desktop user's Bot), with the watchdog around them.
    assert {"task_plan", "task_check", "task_finish"} <= tools._names
    assert any(isinstance(m, BotTaskMiddleware) for m in cfg.middleware)
