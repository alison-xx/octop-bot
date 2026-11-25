"""The desktop can move a large group timeline without changing its source or roster."""

import asyncio
import base64
import hashlib
import json

from octop.infra.agents.bot_workspace import chief_key
from octop.infra.bot_groups.service import create_group
from octop.infra.cloud import move_out
from octop.infra.errors import ErrorCode, OctopError
from tests.integration.test_bot_cloud_move import both as both


async def test_large_group_history_moves_over_actual_routes(both, monkeypatch):
    client, server, admin = both
    services = server.services
    owner = server.user_manager.get("admin").id
    bound = await client.post(
        "/api/octop-bot/cloud/account",
        headers=admin,
        json={"account": "owner@example.com", "password": "only-for-test"},
    )
    bound.raise_for_status()
    (await client.get("/api/octop-bot/workspace", headers=admin)).raise_for_status()
    chief = services.settings_repo.get(chief_key(owner))
    services.agent_repo.create(agent_id="large-helper", user_id=owner, name="Timeline helper")
    group = create_group(
        services, owner, name="Long timeline", admin_id=chief, member_ids=["large-helper"]
    )
    rows = [
        {
            "request_id": f"r{i // 2}",
            "slot": "user" if i % 2 == 0 else "helper",
            "role": "user" if i % 2 == 0 else "assistant",
            "agent_id": None if i % 2 == 0 else "large-helper",
            "text": f"{i}:" + "g" * 99_990,
            "created_at": 1_800_000_000 + i,
        }
        for i in range(112)
    ]
    rows[3]["text"] = "长🙂" * 1_510_000
    repo = services.repos.bot_group_repo
    repo.import_messages(group.group_id, rows)
    repo.set_memory(group.group_id, owner, "Remember the roster")
    repo.set_goal(
        group.group_id,
        owner,
        json.dumps(
            {"title": "Finish", "stages": [{"title": "Review", "assignee_id": "large-helper"}]}
        ),
        None,
    )
    original = move_out._Cloud.send
    lose = {"first", "final"}
    offsets = []

    async def interrupt(self, method, path, body, *, auth=True):
        response = await original(self, method, path, body, auth=auth)
        if path.endswith("/group-parts"):
            offsets.append(body["offset"])
            stage = "final" if response["id"] else "first"
            if stage in lose:
                lose.remove(stage)
                raise OctopError.localized(ErrorCode.NETWORK_ERROR)
        return response

    monkeypatch.setattr(move_out._Cloud, "send", interrupt)

    async def run():
        (await client.post("/api/octop-bot/cloud/move", headers=admin)).raise_for_status()
        for _ in range(400):
            stat = (await client.get("/api/octop-bot/cloud/move", headers=admin)).json()
            if stat["state"] != "running":
                return stat
            await asyncio.sleep(0.05)
        raise AssertionError("move did not finish")

    assert (await run())["state"] == "failed"
    cloud = {"Authorization": f"Bearer {move_out._runs[owner].token}"}
    assert (await client.get("/api/octop-bot/groups", headers=cloud)).json() == []
    assert (await run())["state"] == "failed"
    assert (await run())["state"] == "done"
    [imported] = (await client.get("/api/octop-bot/groups", headers=cloud)).json()
    assert imported["group_id"] != group.group_id
    assert imported["name"] == group.name
    assert offsets[0] == offsets[1] == offsets[-1] == 0
    assert sum(offset > 0 for offset in offsets) >= 2
    target = (await client.get("/api/auth/me", headers=cloud)).json()
    tenant = target.get("id") or target["user"]["id"]
    [helper] = [
        a.agent_id for a in services.agent_repo.list_by_user(tenant) if a.name == "Timeline helper"
    ]
    room = repo.get(imported["group_id"], tenant)
    assert set(json.loads(room["member_ids"])) == {room["admin_id"], helper}
    assert room["memory"] == "Remember the roster"
    assert json.loads(room["goal"])["stages"][0]["assignee_id"] == helper
    assert repo.activity(tenant)[0]["unread_count"] == 0
    assert not any(
        ":parts" in key
        for key in services.settings_repo.with_prefix(f"octop_bot:moved:{tenant}:group:")
    )
    assert len(repo.messages(group.group_id)) == len(rows)
    moved = repo.messages(imported["group_id"], internal=True)
    for expected, actual in zip(rows, moved, strict=True):
        for field in ("request_id", "slot", "role", "created_at", "text"):
            assert expected[field] == actual[field]
        assert actual["agent_id"] == (helper if expected["agent_id"] else None)
    assert repo.get(imported["group_id"], owner) is None


async def test_a_new_small_source_finishes_an_interrupted_group(both, monkeypatch):
    from octop.infra.cloud import move_wire
    from octop.infra.cloud.move_in import MovedGroup, MovedGroupPart, move_group, move_group_part

    _, server, _ = both
    services = server.services
    user = server.user_manager.get("admin")
    services.agent_repo.create(agent_id="snapshot-chief", user_id=user.id, name="Snapshot chief")
    services.settings_repo.set(chief_key(user.id), "snapshot-chief")
    header = {
        "source": "desktop:changed",
        "name": "Changed",
        "admin_id": "snapshot-chief",
        "member_ids": ["snapshot-chief"],
    }
    message = {
        "request_id": "request",
        "slot": "user",
        "role": "user",
        "text": "original",
        "created_at": 1,
    }
    monkeypatch.setattr(move_wire, "PAGE_BYTES", 64)
    wire = move_wire.message_wire(message) + b"\n"
    old = MovedGroupPart(
        **header,
        offset=0,
        total=len(wire),
        message_count=1,
        snapshot=hashlib.sha256(wire).hexdigest(),
        data=base64.b64encode(wire[:64]).decode(),
    )
    assert (await move_group_part(services, user, old)).id is None
    new = MovedGroup(**header, messages=[{**message, "text": "latest snapshot"}])
    final = move_group(services, user, new)
    repo = services.repos.bot_group_repo
    assert [m["text"] for m in repo.messages(final.id)] == ["latest snapshot"]
    assert not any(
        ":parts" in k
        for k in services.settings_repo.with_prefix(f"octop_bot:moved:{user.id}:group:")
    )
