import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from octop.config import OctopConfig
from octop.infra.bot_groups.service import (
    Goal,
    create_group,
    group_row,
    list_messages,
    set_goal,
)
from octop.infra.bot_groups.turns import _goal_edit, mentions, send_message
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import build_shared_services
from octop.infra.errors import OctopError
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.users.identity import User
from octop.infra.utils.paths import PathLayout


@pytest.fixture
def room(tmp_path):
    pool = SqlitePool(tmp_path / "octop.db")
    run_migrations(pool)
    services = build_shared_services(db=pool, paths=PathLayout(tmp_path), config=OctopConfig())
    uid = services.user_repo.create(username="owner", role="user")
    user = User(uid, "owner", "user", "Owner")
    for agent, name in [("a", "Editor"), ("b", "Coder"), ("c", "Chief")]:
        services.agent_repo.create(
            agent_id=agent, user_id=uid, name=name, kind="managed" if agent == "b" else "expert"
        )
    group = create_group(services, uid, name="Room", admin_id="c", member_ids=["a", "b"])
    yield services, user, group
    pool.close()


def gateway(services, processor):
    registry = ThreadRegistry(session_repo=services.session_repo, thread_repo=services.thread_repo)
    return SimpleNamespace(
        gateway=SimpleNamespace(
            thread_registry=registry, processor=SimpleNamespace(iter_turn_chunks=processor)
        )
    )


@pytest.mark.asyncio
async def test_room_reasoning_progress_precedes_text_and_is_not_archived(room):
    services, user, group = room
    repo = services.repos.bot_group_repo
    seen = []

    async def run(msg):
        yield {"type": "reasoning", "content": "internal reasoning"}
        seen.extend(repo.drafts(group.group_id, user.id))
        yield {"type": "token", "content": "**"}
        assert repo.drafts(group.group_id, user.id)[0]["text"] == _text("thinking", user)
        yield {"type": "token", "content": "Campaign idea**"}
        seen.extend(repo.drafts(group.group_id, user.id))

    result = await send_message(
        services,
        gateway(services, run),
        user,
        group.group_id,
        text="Plan an event",
        mention_ids=[],
        request_id="progress",
    )
    assert [r["text"] for r in seen] == [_text("thinking", user), "**Campaign idea**"]
    assert result[-1].text == "**Campaign idea**"


@pytest.mark.asyncio
async def test_proposed_goal_mentions_wait_for_activation(room):
    services, user, group = room
    goal = Goal(title="Launch", criteria="Publish the plan", stages=[])

    async def run(msg):
        assert msg.tenant_id == group.admin_id
        yield {
            "type": "token",
            "content": "After approval @Editor prepares copy.\n```octop-goal\n"
            + goal.model_dump_json()
            + "\n```",
        }

    rows = await send_message(
        services,
        gateway(services, run),
        user,
        group.group_id,
        text="Plan an event",
        mention_ids=[],
        request_id="proposal",
    )
    assert [(row.role, row.agent_id) for row in rows] == [
        ("user", None),
        ("assistant", group.admin_id),
    ]


@pytest.mark.asyncio
async def test_mentions_start_in_parallel_and_replay_without_repeat(room):
    services, user, group = room
    arrived = set()
    release = asyncio.Event()
    calls = []

    async def run(msg):
        calls.append((msg.tenant_id, msg.metadata["thread_id"]))
        arrived.add(msg.tenant_id)
        if arrived == {"a", "b"}:
            release.set()
        await asyncio.wait_for(release.wait(), timeout=3)
        yield {"type": "token", "content": msg.tenant_id + " done"}

    runtime = gateway(services, run)
    params = {"text": "请 @Editor 和 @Coder 分工", "mention_ids": [], "request_id": "first"}
    result = await send_message(services, runtime, user, group.group_id, **params)
    assert [m.role for m in result] == ["user", "assistant", "assistant"]
    assert {m.agent_id for m in result[1:]} == {"a", "b"}
    assert len({t for _, t in calls}) == 2
    assert await send_message(services, runtime, user, group.group_id, **params) == result
    assert len(calls) == 2
    assert (
        list_messages(services, user.id, group.group_id, after_id=result[0].message_id)
        == result[1:]
    )
    with pytest.raises(OctopError):
        await send_message(
            services, runtime, user, group.group_id, **{**params, "text": "different"}
        )


@pytest.mark.asyncio
async def test_admin_handoff_once_then_wrap_and_member_state_is_scoped(room):
    services, user, group = room
    calls = []

    async def run(msg):
        calls.append((msg.tenant_id, msg.metadata["thread_id"], msg.text))
        if len(calls) == 1:
            yield {"type": "token", "content": "@Editor please edit"}
        else:
            yield {"type": "token", "content": "finished"}

    runtime = gateway(services, run)
    services.repos.bot_group_repo.set_memory(group.group_id, user.id, "room-only note")
    await send_message(
        services, runtime, user, group.group_id, text="Draft", mention_ids=[], request_id="one"
    )
    assert [agent for agent, _, _ in calls] == ["c", "a", "c"]
    history = list_messages(services, user.id, group.group_id)
    assert [(m.agent_id, m.is_wrap_up) for m in history if m.role == "assistant"] == [
        ("c", False),
        ("a", False),
        ("c", True),
    ]
    assert calls[0][1] == calls[-1][1]
    assert "room-only note" in calls[1][2]
    second = create_group(services, user.id, name="Another", admin_id="a", member_ids=["c"])
    await send_message(
        services, runtime, user, second.group_id, text="Hello", mention_ids=[], request_id="one"
    )
    assert calls[1][1] != calls[-1][1]
    assert "room-only note" not in calls[-1][2]


def test_member_ownership_and_goal_confirmation(room):
    services, user, group = room
    peer = services.user_repo.create(username="other", role="user")
    services.agent_repo.create(agent_id="x", user_id=peer, name="Other")
    services.agent_repo.create(
        agent_id="private",
        user_id=user.id,
        name="Private",
        config_json='{"octop_bot":{"private":true}}',
    )
    for invalid in ("x", "private"):
        with pytest.raises(OctopError):
            create_group(services, user.id, name="Bad", admin_id="c", member_ids=[invalid])
    with pytest.raises(OctopError):
        list_messages(services, peer, group.group_id)
    with pytest.raises(ValidationError):
        Goal.model_validate({"title": "Finish", "status": "done", "stages": []})
    goal = Goal.model_validate(
        {
            "title": "Finish",
            "criteria": "document delivered",
            "status": "active",
            "stages": [{"title": "draft", "assignee_id": "a", "status": "active"}],
        }
    )
    block = "\n```octop-goal\n" + goal.model_dump_json() + "\n```"
    assert _goal_edit(block, group_row(services, user.id, group.group_id), group, [])[1] is None
    set_goal(services, user.id, group.group_id, goal)
    goal.stages[0].status = "done"
    goal.stages[0].evidence = "m42"
    goal.status = "done"
    block = "Done\n```octop-goal\n" + goal.model_dump_json() + "\n```"
    row = group_row(services, user.id, group.group_id)
    assert _goal_edit(block, row, group, [])[1] is None
    assert _goal_edit(
        block, row, group, [{"role": "assistant", "agent_id": "a", "message_id": "m42"}]
    ) == ("Done", goal)


def test_mentions_skip_email_match_long_name_and_skip_ambiguous_display_name():
    names = {"a": "A", "ab": "A B", "a2": "A", "cn": "编辑"}
    assert mentions("mail@a.com @A B @A @a2 @编辑。", names) == ["ab", "a2", "cn"]


@pytest.mark.asyncio
async def test_boot_recovers_only_undispatched_work_after_interruption(room):
    import json

    from octop.infra.bot_groups.turns import recover_room_turns

    services, user, group = room
    repo = services.repos.bot_group_repo
    text = "Please act"
    mentions_list = ["c", "a", "b"]
    args = json.dumps([text, mentions_list, False], ensure_ascii=False)
    assert repo.claim(group.group_id, "crash", args, text, "old-worker") == "acquired"
    repo.reply(
        group.group_id, "crash", "old-worker", "reply:c", "assistant", "c", "already done", None
    )
    assert repo.begin_reply(group.group_id, "crash", "old-worker", "reply:a", "a")
    repo.lease(group.group_id, "crash", "old-worker", close=True)
    executed = []

    async def run(msg):
        executed.append(msg.tenant_id)
        yield {"type": "token", "content": "fresh"}

    runtime = gateway(services, run)
    runtime.user_manager = SimpleNamespace(get_by_id=lambda uid: user if uid == user.id else None)
    await recover_room_turns(services, runtime)
    assert executed == ["b"]
    rows = list_messages(services, user.id, group.group_id)
    assert {m.agent_id: m.role for m in rows if m.agent_id} == {
        "c": "assistant",
        "a": "error",
        "b": "assistant",
    }
    assert not repo.unfinished()


@pytest.mark.asyncio
async def test_chief_private_and_group_turns_use_the_real_gateway_request_builder(room):
    from unittest.mock import AsyncMock, MagicMock

    from octop_gateway.models import ChannelSubject, InboundMessage, TextContent

    from octop.infra.agents.bot_workspace import chief_key
    from octop.infra.gateway.hitl.coordinator import HitlChannelCoordinator
    from octop.infra.gateway.process.processor import GlobalProcessor
    from octop.infra.gateway.slash.dispatcher import SlashDispatcher

    services, user, group = room
    services.settings_repo.set(chief_key(user.id), "c")
    registry = ThreadRegistry(session_repo=services.session_repo, thread_repo=services.thread_repo)
    manager = MagicMock()
    manager.get_row = services.agent_repo.get
    manager.merge_turn_mcp_servers.return_value = None
    manager.prepare_chat_mcp = AsyncMock(return_value=[])
    seen = []

    async def stream(agent_id, request):
        seen.append((agent_id, request["source"], request["thread_id"]))
        yield {"type": "token", "content": "hello"}

    manager.stream = stream
    processor = GlobalProcessor(
        agent_manager=manager,
        thread_registry=registry,
        audit_repo=services.audit_repo,
        agent_repo=services.agent_repo,
        user_repo=services.user_repo,
        connector_repo=services.connector_repo,
        dispatcher=SlashDispatcher(),
        usage_repo=None,
        gateway=None,
        hitl=HitlChannelCoordinator(),
    )
    key = registry.dashboard_key(agent_id="c", user_id=user.id)
    thread = await registry.get_or_create_by_key(
        session_key=key, agent_id="c", user_id=user.id, channel_type="dashboard"
    )
    inbound = InboundMessage(
        channel_id="octop-ws",
        channel_type="dashboard",
        tenant_id="c",
        channel_subject=ChannelSubject(subject_id=str(user.id)),
        content=[TextContent(text="你好 Chief")],
        metadata={"thread_id": thread, "session_key": key},
    )
    chunks = [c async for c in processor.iter_turn_chunks(inbound)]
    assert any(c.get("type") == "token" and c["content"] == "hello" for c in chunks), chunks
    runtime = SimpleNamespace(
        gateway=SimpleNamespace(thread_registry=registry, processor=processor)
    )
    replies = await send_message(
        services,
        runtime,
        user,
        group.group_id,
        text="@Editor 请答复",
        mention_ids=["a"],
        request_id="through-gateway",
    )
    assert [(m.role, m.text) for m in replies] == [
        ("user", "@Editor 请答复"),
        ("assistant", "hello"),
    ]
    assert seen == [
        ("c", "dashboard/octop-ws", thread),
        ("a", "octop_bot_group/octop-bot", replies[1].thread_id),
    ]
    assert services.thread_repo.list_visible(agent_id="a", user_id=user.id) == []


def test_room_artifacts_stay_in_authorized_room_and_member_memory_is_off(room):
    from octop.infra.agents.manager import AgentManager
    from octop.infra.bot_groups.workspace import (
        download_artifact,
        list_artifacts,
        room_files,
        room_root,
    )

    services, user, group = room
    manager = AgentManager(repos=services.repos, paths=services.paths)
    another = create_group(services, user.id, name="Second", admin_id="a", member_ids=[])
    root = room_root(services, user.id, group.group_id)
    second = room_root(services, user.id, another.group_id)
    row = services.agent_repo.get("a")
    cfg = manager._build_harness_config(row, room_workspace=root)
    other_cfg = manager._build_harness_config(row, room_workspace=second)
    assert cfg.workspace_dir != other_cfg.workspace_dir
    assert cfg.system_files_path == ".octop/members/a"
    assert cfg.memory_enabled is False
    assert cfg.memory_capture_enabled is False
    assert cfg.memory_recall_inject_enabled is False
    assert cfg.backend["virtual_mode"] is True
    assert str(cfg.backend["root_dir"]) == str(root)
    assert services.agent_repo.get("a").config_json == row.config_json
    room_files(root).upload_many([("work/report.txt", b"done"), (".octop/secret", b"secret")])
    assert list_artifacts(services, user.id, group.group_id, ".") == [
        {"name": "work", "path": "work", "is_dir": True}
    ]
    assert download_artifact(services, user.id, group.group_id, "work/report.txt") == (
        "report.txt",
        b"done",
    )
    for location in [".octop/secret", "../report.txt", str(root / "work" / "report.txt")]:
        with pytest.raises(OctopError):
            download_artifact(services, user.id, group.group_id, location)
    with pytest.raises(OctopError):
        download_artifact(services, user.id, another.group_id, "work/report.txt")
    with pytest.raises(OctopError):
        list_artifacts(services, user.id + 1, group.group_id, ".")


@pytest.mark.asyncio
@pytest.mark.parametrize("from_chat", [True, False])
async def test_confirmed_goal_advances_only_after_admin_accepts_member_evidence(room, from_chat):
    from octop.infra.bot_groups.service import get_goal
    from octop.infra.bot_groups.turns import run_confirmed_goal

    services, user, group = room
    goal = Goal.model_validate(
        {
            "title": "Deliver",
            "criteria": "two results",
            "stages": [
                {"title": "First", "assignee_id": "a"},
                {"title": "Second", "assignee_id": "b"},
            ],
            "status": "draft" if from_chat else "active",
        }
    )
    set_goal(services, user.id, group.group_id, goal)
    calls = []

    async def processor(msg):
        calls.append(msg.tenant_id)
        if msg.tenant_id != "c":
            yield {"type": "token", "content": f"Delivered {msg.tenant_id}"}
            return
        latest = get_goal(services, user.id, group.group_id)
        stage = next(s for s in latest.stages if s.status != "done")
        reply = next(
            m
            for m in reversed(list_messages(services, user.id, group.group_id))
            if m.agent_id == stage.assignee_id
        )
        stage.status = "done"
        stage.evidence = f"verified {reply.message_id}"
        if all(s.status == "done" for s in latest.stages):
            latest.status = "done"
        yield {
            "type": "token",
            "content": f"Accepted\n```octop-goal\n{latest.model_dump_json()}\n```",
        }

    runtime = gateway(services, processor)

    async def activate():
        if from_chat:
            return await send_message(
                services,
                runtime,
                user,
                group.group_id,
                text="激活",
                mention_ids=[],
                request_id="owner-activation",
                owner_commands=True,
            )
        return await run_confirmed_goal(services, runtime, user, group.group_id, goal)

    await activate()
    assert calls == ["a", "c", "b", "c"]
    history = list_messages(services, user.id, group.group_id)
    assert [(m.stage_number, m.is_wrap_up) for m in history if m.role == "assistant"] == [
        (1, False),
        (1, True),
        (2, False),
        (2, True),
    ]
    assert get_goal(services, user.id, group.group_id).status == "done"
    assert not services.repos.bot_group_repo.drafts(group.group_id, user.id)
    await activate()
    assert len(calls) == 4


@pytest.mark.asyncio
async def test_continue_partial_goal_reviews_only_the_outstanding_stage(room):
    from octop.infra.bot_groups.service import get_goal

    services, user, group = room
    goal = Goal.model_validate(
        {
            "title": "Ship",
            "criteria": "Evidence",
            "status": "active",
            "stages": [
                {"title": "First", "assignee_id": "a", "status": "done", "evidence": "prior"},
                {"title": "Second", "assignee_id": "b"},
            ],
        }
    )
    set_goal(services, user.id, group.group_id, goal)
    calls = []

    async def processor(msg):
        calls.append(msg.tenant_id)
        if msg.tenant_id == "c":
            delivery = list_messages(services, user.id, group.group_id)[-1]
            text = f"Verified.\n[ACCEPT {delivery.message_id}]"
        else:
            with pytest.raises(OctopError):
                await resume("duplicate")
            text = "Delivered."
        yield {"type": "token", "content": text}

    async def resume(request_id):
        await send_message(
            services,
            gateway(services, processor),
            user,
            group.group_id,
            text="继续执行目标",
            mention_ids=[],
            request_id=request_id,
            owner_commands=True,
        )

    await resume("resume")
    await resume("resume")
    saved = get_goal(services, user.id, group.group_id)
    assert calls == ["b", "c"]
    assert saved.status == "done"
    assert saved.stages[0].evidence == "prior"
    assert (
        saved.stages[1].evidence == list_messages(services, user.id, group.group_id)[1].message_id
    )


@pytest.mark.asyncio
async def test_scoped_hitl_keeps_agent_until_approved_and_routes_cancellation(room, monkeypatch):
    from octop.infra.agents import manager as manager_module
    from octop.infra.agents.manager import AgentManager
    from octop.infra.bot_groups.workspace import room_root

    services, user, group = room
    manager = AgentManager(repos=services.repos, paths=services.paths)
    root = room_root(services, user.id, group.group_id)
    manager._harness_manager = SimpleNamespace(shared_factory=None)
    instances = []

    class Agent:
        def __init__(self, config, **kwargs):
            self.config = config
            self.config.managed_runner = "test"
            self.closed = False
            self.cancelled = None
            instances.append(self)

        async def stream(self, request):
            self.paused_user = request["user"]
            yield {"type": "hitl_required", "request": {}}

        async def resume_hitl(self, thread_id, decisions):
            yield {"type": "token", "content": self.paused_user}

        def cancel(self, thread_id):
            self.cancelled = thread_id

        async def aclose(self):
            self.closed = True

    monkeypatch.setattr(manager_module, "HarnessAgent", Agent)
    req = {"thread_id": "T", "user": str(user.id)}
    assert [x["type"] async for x in manager._run_in_bot_room("a", root, req)] == ["hitl_required"]
    assert not instances[0].closed
    manager.cancel_stream("a", "T")
    assert instances[0].cancelled == "T"
    assert [
        x["content"] async for x in manager._run_in_bot_room("a", root, req, [{"type": "approve"}])
    ] == [str(user.id)]
    assert len(instances) == 1 and instances[0].closed
    with pytest.raises(OctopError):
        _ = [x async for x in manager._run_in_bot_room("a", root, req, [{"type": "approve"}])]


@pytest.mark.asyncio
async def test_member_group_thread_is_named_listed_on_request_and_shows_the_room_request(room):
    from octop.infra.bot_groups.turns import room_request, show_room_history

    services, user, group = room
    prompts = []

    async def run(msg):
        prompts.append(msg.text)
        yield {"type": "token", "content": "done"}

    runtime = gateway(services, run)
    replies = await send_message(
        services,
        runtime,
        user,
        group.group_id,
        text="@Editor 写提纲",
        mention_ids=[],
        request_id="r",
    )
    thread_id = replies[1].thread_id
    row = services.thread_repo.get(thread_id)
    assert row.title == "群聊 · Room"
    repo = services.thread_repo
    assert repo.list_visible(agent_id="a", user_id=user.id) == []
    listed = repo.list_visible(agent_id="a", user_id=user.id, include_bot_groups=True)
    assert [r.thread_id for r in listed] == [thread_id]
    other = services.user_repo.create(username="other", role="user")
    repo.set_contributed(thread_id, True)
    assert repo.list_visible(agent_id="a", user_id=other, include_bot_groups=True) == []

    assert room_request(prompts[0]) == "@Editor 写提纲"
    assert room_request("plain text") is None
    messages = [
        {"role": "user", "content": [{"type": "text", "text": prompts[0]}]},
        {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
    ]
    show_room_history(messages, services.repos.bot_group_repo, thread_id)
    assert messages[0]["content"] == [{"type": "text", "text": "@Editor 写提纲"}]
    assert messages[1]["content"] == [{"type": "text", "text": "done"}]

    goal_block = '\n```octop-goal\n{"title":"test","criteria":"","stages":[]}\n```'
    for raw, expected in [
        ("done" + goal_block, "done"),
        ("unpublished" + goal_block, "unpublished" + goal_block),
    ]:
        messages = [{"role": "assistant", "content": [{"type": "text", "text": raw}]}]
        show_room_history(messages, services.repos.bot_group_repo, thread_id)
        assert messages[0]["content"] == [{"type": "text", "text": expected}]


def _turns(calls):
    return [(agent, text) for agent, _, text in calls]


def _text(key, user):
    from octop.i18n import tr

    return tr(f"bot_rooms.{key}", user.locale)


@pytest.mark.asyncio
async def test_admin_that_passes_is_asked_again_and_answers(room):
    services, user, group = room
    calls = []

    async def run(msg):
        calls.append((msg.tenant_id, msg.metadata["thread_id"], msg.text))
        yield {"type": "token", "content": "[PASS]" if len(calls) == 1 else "I am Chief."}

    await send_message(
        services,
        gateway(services, run),
        user,
        group.group_id,
        text="Introduce yourself",
        mention_ids=[],
        request_id="r1",
    )
    first, retry = _turns(calls)
    assert first[0] == retry[0] == "c"
    assert _text("must_answer", user) in first[1]
    assert _text("may_pass", user) not in first[1]
    assert retry[1] == _text("pass_retry", user)
    # Same member thread, so the model sees its own [PASS] before the retry.
    assert calls[0][1] == calls[1][1]
    visible = [m for m in list_messages(services, user.id, group.group_id) if m.role != "user"]
    assert [(m.agent_id, m.role, m.text) for m in visible] == [("c", "assistant", "I am Chief.")]


@pytest.mark.asyncio
async def test_mentioned_member_that_keeps_passing_leaves_a_visible_notice(room):
    services, user, group = room
    calls = []

    async def run(msg):
        calls.append((msg.tenant_id, msg.metadata["thread_id"], msg.text))
        yield {"type": "token", "content": "[PASS]"}

    await send_message(
        services,
        gateway(services, run),
        user,
        group.group_id,
        text="@Editor what do you think?",
        mention_ids=[],
        request_id="r2",
    )
    assert [agent for agent, _ in _turns(calls)] == ["a", "a"]
    visible = [m for m in list_messages(services, user.id, group.group_id) if m.role != "user"]
    assert [(m.agent_id, m.role) for m in visible] == [("a", "error")]
    assert visible[0].text == _text("pass_fallback", user)


@pytest.mark.asyncio
async def test_single_bot_room_always_answers(room):
    services, user, _group = room
    solo = create_group(
        services, user.id, name="Solo", admin_id="a", member_ids=[], reply_mode="all_members"
    )
    calls = []

    async def run(msg):
        calls.append((msg.tenant_id, msg.metadata["thread_id"], msg.text))
        yield {"type": "token", "content": "Hello from Editor."}

    await send_message(
        services,
        gateway(services, run),
        user,
        solo.group_id,
        text="Hi",
        mention_ids=[],
        request_id="r3",
    )
    assert len(calls) == 1
    assert _text("must_answer", user) in calls[0][2]
    assert _text("may_pass", user) not in calls[0][2]


@pytest.mark.asyncio
async def test_all_members_round_lets_other_members_pass_quietly(room):
    services, user, _group = room
    everyone = create_group(
        services, user.id, name="All", admin_id="c", member_ids=["a", "b"], reply_mode="all_members"
    )
    calls = []

    async def run(msg):
        calls.append((msg.tenant_id, msg.metadata["thread_id"], msg.text))
        yield {"type": "token", "content": "Chief answer." if msg.tenant_id == "c" else "[PASS]"}

    await send_message(
        services,
        gateway(services, run),
        user,
        everyone.group_id,
        text="Status?",
        mention_ids=[],
        request_id="r4",
    )
    prompts = dict(_turns(calls))
    assert len(calls) == 3  # no retry for members that may pass
    assert _text("must_answer", user) in prompts["c"]
    assert _text("may_pass", user) in prompts["a"]
    visible = [m for m in list_messages(services, user.id, everyone.group_id) if m.role != "user"]
    assert [(m.agent_id, m.text) for m in visible] == [("c", "Chief answer.")]
