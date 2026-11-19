"""Chief and the manual sidebar share the same per-owner, optimistic layout."""

import asyncio
import json
from threading import Barrier, Event

import pytest

from octop.infra.agents.bot_tools import chief_tools
from octop.infra.errors import ErrorCode, OctopError

WORKSPACE = "/api/octop-bot/workspace"
LAYOUT = "/api/octop-bot/layout"


async def owner_tools(client, server, auth):
    workspace = (await client.get(WORKSPACE, headers=auth)).json()
    chief = workspace["chief_id"]
    registry = server.app_runtime.agent_registry
    owner = registry.get_row(chief).user_id
    tools = {t.name: t for t in chief_tools(registry, server.services, chief, owner)}
    config = {"configurable": {"user": str(owner), "agent_id": chief, "octop_bot_browser": True}}

    async def call(tool, **kwargs):
        return await tools["octop_bot_" + tool].ainvoke(kwargs, config=config)

    return owner, chief, call


async def test_legacy_layout_manual_save_and_chief_share_membership(env_with_agent):
    client, server, auth, existing = env_with_agent
    owner, chief, call = await owner_tools(client, server, auth)
    settings = server.services.settings_repo
    legacy = {
        "pinned": [f"bot:{existing}"],
        "sections": [
            {"name": "收件箱", "items": [f"bot:{existing}"], "collapsed": True, "color": "pink"}
        ],
    }
    settings.set(f"octop_bot:layout:{owner}", json.dumps(legacy))
    opened = (await client.get(WORKSPACE, headers=auth)).json()
    assert opened["sections"] == legacy["sections"] and opened["revision"] == 0
    bot = await call("create", name="研究员", instructions="整理项目素材", section="项目")
    room = await call(
        "create_group", name="研究群", admin_id=chief, member_ids=[bot], section="项目"
    )
    room_id = room["group_id"]
    entries = [f"bot:{bot}", f"group:{room_id}"]
    result = await call(
        "sections", action="create", section="项目", bot_ids=[bot], group_ids=[room_id]
    )
    assert not result["changed"] and result["revision"] == 2
    assert result["sections"][0] == legacy["sections"][0]
    assert result["sections"][1]["items"] == entries

    conflict = await client.put(LAYOUT, json={**legacy, "revision": 0}, headers=auth)
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "BOT_LAYOUT_CHANGED"
    updated = await client.put(
        LAYOUT,
        headers=auth,
        json={
            "sections": result["sections"][::-1],
            "pinned": [entries[1], *legacy["pinned"]],
            "revision": 2,
        },
    )
    updated.raise_for_status()
    assert updated.json()["revision"] == 3
    moved = await call(
        "sections", action="move", section="收件箱", bot_ids=[bot], group_ids=[room_id]
    )
    assert moved["sections"][1] == {**legacy["sections"][0], "items": [f"bot:{existing}", *entries]}
    await call("update", agent_id=bot, section="")
    await call("update_group", group_id=room_id, section="项目")
    roster = await call("roster")
    assert next(b for b in roster["bots"] if b["agent_id"] == bot)["section"] is None
    assert next(g for g in roster["groups"] if g["group_id"] == room_id)["section"] == "项目"
    await call("sections", action="dissolve", section="项目")
    again = await call("sections", action="dissolve", section="项目")
    assert not again["changed"]
    final = (await client.get(WORKSPACE, headers=auth)).json()
    assert final["sections"] == legacy["sections"]
    assert final["pinned"] == [entries[1], *legacy["pinned"]]
    assert final["revision"] == again["revision"]
    assert room == next(g for g in final["groups"] if g["group_id"] == room_id)
    assert bot in {b["agent_id"] for b in final["bots"]}
    messages = await client.get(f"/api/octop-bot/groups/{room_id}/messages", headers=auth)
    messages.raise_for_status()
    assert messages.json() == []


async def test_cannot_file_chief_private_bot_or_another_owners_items(env_admin_alice):
    client, server, admin, alice = env_admin_alice
    owner, chief, call = await owner_tools(client, server, admin)
    _, other, other_call = await owner_tools(client, server, alice)
    foreign = await other_call("create", name="个人助理", instructions="梳理待办")
    foreign_group = await other_call("create_group", name="个人群", admin_id=other, member_ids=[])
    private = await call("create", name="个人助理", instructions="仅处理个人记录")
    privacy = await client.put(
        f"/api/octop-bot/bots/{private}/privacy", json={"private": True}, headers=admin
    )
    privacy.raise_for_status()
    legacy = {
        "sections": [
            {"name": "收藏", "items": [f"bot:{private}", f"bot:{foreign}", f"bot:{chief}"]}
        ]
    }
    server.services.settings_repo.set(f"octop_bot:layout:{owner}", json.dumps(legacy))
    workspace = (await client.get(WORKSPACE, headers=admin)).json()
    assert workspace["sections"][0]["items"] == [f"bot:{private}"]
    assert (await call("sections", action="list"))["sections"][0]["items"] == []
    for field, resource in (
        ("bot_ids", chief),
        ("bot_ids", foreign),
        ("group_ids", foreign_group["group_id"]),
        ("bot_ids", private),
    ):
        with pytest.raises(OctopError) as err:
            await call("sections", action="create", section="项目", **{field: [resource]})
        assert err.value.code is ErrorCode.NOT_FOUND
    for entry in [f"bot:{chief}", f"bot:{foreign}", f"group:{foreign_group['group_id']}"]:
        forbidden = await client.put(
            LAYOUT,
            headers=admin,
            json={"sections": [{"name": "收藏", "items": [entry]}], "revision": 0},
        )
        assert forbidden.status_code == 404
    await call("sections", action="create", section="收藏")
    assert (await client.get(WORKSPACE, headers=alice)).json()["sections"] == []
    manual = await client.put(LAYOUT, headers=admin, json={"sections": workspace["sections"]})
    manual.raise_for_status()
    assert manual.json()["sections"][0]["items"] == [f"bot:{private}"]


async def test_concurrent_chief_edits_retry_without_overwriting_or_duplicating(
    env_with_agent, monkeypatch
):
    client, server, auth, bot = env_with_agent
    _, chief, call = await owner_tools(client, server, auth)
    room = await call("create_group", name="编务", admin_id=chief, member_ids=[])
    gate = Barrier(2, timeout=8)
    replace = server.services.settings_repo.replace_if_current

    def overlapping(key, raw, updated):
        if json.loads(raw).get("revision", 0) == 0:
            gate.wait()
        return replace(key, raw, updated)

    monkeypatch.setattr(server.services.settings_repo, "replace_if_current", overlapping)
    options = {"action": "create", "section": "编辑"}
    results = await asyncio.gather(
        call("sections", **options, bot_ids=[bot]),
        call("sections", **options, group_ids=[room["group_id"]]),
    )
    assert sorted(r["revision"] for r in results) == [1, 2]
    workspace = (await client.get(WORKSPACE, headers=auth)).json()
    assert [s["name"] for s in workspace["sections"]] == ["编辑"]
    assert set(workspace["sections"][0]["items"]) == {f"bot:{bot}", f"group:{room['group_id']}"}


async def test_unversioned_manual_request_racing_chief_cannot_replay_the_old_snapshot(
    env_with_agent, monkeypatch
):
    client, server, auth, bot = env_with_agent
    _, _, call = await owner_tools(client, server, auth)
    writing, release = Event(), Event()
    replace = server.services.settings_repo.replace_if_current

    def pause_manual(key, raw, updated):
        if json.loads(updated)["pinned"]:
            writing.set()
            assert release.wait(8)
        return replace(key, raw, updated)

    monkeypatch.setattr(server.services.settings_repo, "replace_if_current", pause_manual)
    manual = asyncio.create_task(client.put(LAYOUT, headers=auth, json={"pinned": [f"bot:{bot}"]}))
    try:
        assert await asyncio.to_thread(writing.wait, 8)
        await call("sections", action="create", section="并发", bot_ids=[bot])
    finally:
        release.set()
    assert (await manual).status_code == 409
    workspace = (await client.get(WORKSPACE, headers=auth)).json()
    assert workspace["sections"][0]["items"] == [f"bot:{bot}"]


async def test_created_contact_has_recoverable_id_if_sidebar_is_full(env_with_provider):
    client, server, auth = env_with_provider
    _, chief, call = await owner_tools(client, server, auth)
    full = await client.put(
        LAYOUT, headers=auth, json={"sections": [{"name": str(i)} for i in range(100)]}
    )
    full.raise_for_status()
    bot = await call("create", name="排期助手", instructions="安排日程", section="新项目")
    room = await call(
        "create_group",
        name="排期群",
        admin_id=chief,
        member_ids=[bot["agent_id"]],
        section="新项目",
    )
    assert room["section_error"] == bot["section_error"] == "SLASH_BAD_ARGS"
    workspace = (await client.get(WORKSPACE, headers=auth)).json()
    assert bot["agent_id"] in {b["agent_id"] for b in workspace["bots"]}
    assert [g["group_id"] for g in workspace["groups"]] == [room["group_id"]]
    assert workspace["sections"] == full.json()["sections"]
