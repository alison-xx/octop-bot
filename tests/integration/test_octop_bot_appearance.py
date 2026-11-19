"""Assignments and explicit photos stay consistent across workspace refreshes."""

import json
from types import SimpleNamespace

from octop.infra.agents.bot_appearance import _default_character


def test_default_character_matches_ds_bot_public_id_vectors():
    for agent, shape, color in [
        ("example-bot", "kitty", "violet"),
        ("AGT001", "star", "yellow"),
        ("scribe", "acorn", "yellow"),
    ]:
        look = _default_character(SimpleNamespace(agent_id=agent, name="Assistant"), "chief")
        assert (look.shape, look.color) == (shape, color)


async def test_legacy_chief_default_updates_and_respects_explicit_choices(env_admin_alice):
    client, server, auth, _ = env_admin_alice
    base = "/api/octop-bot"

    async def chief_card():
        response = await client.get(base + "/workspace", headers=auth)
        response.raise_for_status()
        workspace = response.json()
        return next(bot for bot in workspace["bots"] if bot["agent_id"] == workspace["chief_id"])

    chief = (await chief_card())["agent_id"]
    owner = server.services.agent_repo.get(chief).user_id
    key = f"octop_bot:appearance:{owner}:{chief}"
    whale = {"shape": "whale", "color": "deepseek"}
    mascot = {"shape": "octop", "color": "rose"}
    settings = server.services.settings_repo
    settings.set(key, json.dumps({"original": whale}))
    assert (await chief_card())["avatar"] == {**mascot, "source": "character"}

    settings.set(key, json.dumps({"original": whale, "selected": whale, "source": "character"}))
    assert (await chief_card())["avatar"] == {**whale, "source": "character"}

    photo = "/experts/avatars/scene-design.svg"
    server.app_runtime.agent_registry.set_icon_url(chief, photo)
    settings.set(key, json.dumps({"original": whale, "source": "photo"}))
    card = await chief_card()
    assert card["icon_url"] == photo
    assert card["avatar"] == {**mascot, "source": "photo"}
    reset = await client.delete(f"{base}/bots/{chief}/appearance", headers=auth)
    assert reset.json() == {**mascot, "source": "character"}
    assert (await chief_card())["avatar"] == reset.json()


async def test_existing_team_gets_distinct_roles_and_owner_can_switch_appearance(env_admin_alice):
    client, server, auth, alice = env_admin_alice
    base = "/api/octop-bot"
    workspace = (await client.get(base + "/workspace", headers=auth)).json()
    chief = workspace["chief_id"]
    chief_card = next(b for b in workspace["bots"] if b["agent_id"] == chief)
    assert chief_card["avatar"] == {"shape": "octop", "color": "rose", "source": "character"}
    repo = server.services.agent_repo
    owner = repo.get(chief).user_id
    roles = [
        ("plan", "选题策划", "star", "yellow"),
        ("write", "文案写作", "moon", "violet"),
        ("art", "视觉设计", "gem", "magenta"),
        ("data", "数据运营", "hex", "cyan"),
    ]
    for agent, name, _, _ in roles:
        repo.create(agent_id=agent, name=name, user_id=owner)
    server.app_runtime.agent_registry.set_icon_url("art", "/experts/avatars/scene-design.svg")
    resource = f"{base}/bots/art/appearance"

    async def cards():
        response = await client.get(base + "/workspace", headers=auth)
        response.raise_for_status()
        return {row["agent_id"]: row for row in response.json()["bots"]}

    existing = await cards()
    for agent, _, shape, color in roles:
        assert (existing[agent]["avatar"]["shape"], existing[agent]["avatar"]["color"]) == (
            shape,
            color,
        )
    assert existing["art"]["avatar"]["source"] == "photo"
    assert existing["art"]["icon_url"] == "/experts/avatars/scene-design.svg"
    change = {"shape": "kitty", "color": "#a12bc4"}
    saved = await client.put(resource, json=change, headers=auth)
    assert saved.json() == {**change, "source": "character"}
    repo.update_config("art", name="Renamed")
    assert (await cards())["art"]["icon_url"] is None
    assert (await client.put(resource, json=change, headers=alice)).status_code == 404
    assert (
        await client.put(resource, json={"shape": "kitty", "color": "bad"}, headers=auth)
    ).status_code == 422
    reset = await client.delete(resource, headers=auth)
    assert reset.json() == {"shape": "gem", "color": "magenta", "source": "character"}
    assert repo.get("art").icon_url == "/experts/avatars/scene-design.svg"
