"""Unread activity drives Octop Bot sidebar badges, the app badge and notifications."""

ACTIVITY = "/api/octop-bot/activity"
WORKSPACE = "/api/octop-bot/workspace"


def _turn(repo, group_id: str, request_id: str, agent_id: str, text: str) -> None:
    assert repo.claim(group_id, request_id, "[]", "hi", f"lease-{request_id}") == "acquired"
    repo.reply(group_id, request_id, f"lease-{request_id}", "a", "assistant", agent_id, text, None)


async def test_group_unread_counts_replies_after_the_read_cursor(env_with_agent):
    client, server, auth, _ = env_with_agent
    chief = (await client.get(WORKSPACE, headers=auth)).json()["chief_id"]
    owner = server.app_runtime.agent_registry.get_row(chief).user_id
    repo = server.services.repos.bot_group_repo
    legacy = repo.create(owner, "老群", chief, [chief], "admin_first")
    server.services.settings_repo.delete(f"bot-room-read:{owner}:{legacy}")
    _turn(repo, legacy, "r0", chief, "before read tracking")
    room = (
        await client.post(
            "/api/octop-bot/groups",
            headers=auth,
            json={"name": "新群", "admin_id": chief, "member_ids": []},
        )
    ).json()["group_id"]
    _turn(repo, room, "r1", chief, "first")
    _turn(repo, room, "r2", chief, "second")

    activity = (await client.get(ACTIVITY, headers=auth)).json()
    groups = {g["group_id"]: g for g in activity["groups"]}
    assert groups[legacy]["unread_count"] == 0
    assert groups[room]["unread_count"] == 2
    latest = groups[room]["last_message"]
    assert latest["text"] == "second" and latest["agent_id"] == chief
    assert any(b["agent_id"] == chief for b in activity["bots"])

    read = await client.post(f"/api/octop-bot/groups/{room}/read", headers=auth)
    assert read.status_code == 204
    _turn(repo, room, "r3", chief, "third")
    groups = {g["group_id"]: g for g in (await client.get(ACTIVITY, headers=auth)).json()["groups"]}
    assert groups[room]["unread_count"] == 1

    assert (await client.delete(f"/api/octop-bot/groups/{room}", headers=auth)).status_code == 204
    assert server.services.settings_repo.get(f"bot-room-read:{owner}:{room}") is None
    missing = await client.post(f"/api/octop-bot/groups/{room}/read", headers=auth)
    assert missing.status_code == 404
