"""New-user onboarding: Chief builds a team from one sentence, once per owner."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from octop.infra.agents.bot_tools import chief_tools
from octop.infra.agents.middleware.team_dispatch import CONFIG_KEY
from octop.infra.errors import OctopError
from tests.integration.test_octop_bot_cloud import _sign_in, upstream  # noqa: F401
from tests.support.app import octop_client

ROUTE = "/api/octop-bot/onboarding"
WORKSPACE = "/api/octop-bot/workspace"

TEAM = {
    "team_name": "外贸团队",
    "bots": [
        {"name": "阿贸", "role": "询盘回复与报价", "instructions": "回复询盘并报价"},
        {"name": "小选", "role": "选品与竞品分析", "instructions": "分析选品和竞品"},
        {"name": "Mia", "role": "海外社媒内容", "instructions": "写海外社媒内容"},
    ],
    "admin": "阿贸",
    "first_task": "  帮我回一封报价邮件。 ",
}


async def _bot_owner(client: Any, server: Any, auth: dict[str, str]) -> str:
    """Leave the owner with only Chief, like a fresh Octop Bot install (no setup ``main``)."""
    chief = (await client.get(WORKSPACE, headers=auth)).json()["chief_id"]
    registry = server.app_runtime.agent_registry
    owner = registry.get_row(chief).user_id
    for row in server.services.agent_repo.list_by_user(owner):
        if row.agent_id != chief and row.kind != "team":
            await registry.delete(row.agent_id)
    return str(chief)


def _chief(server: Any, chief: str) -> tuple[dict[str, Any], dict[str, Any]]:
    registry = server.app_runtime.agent_registry
    owner = registry.get_row(chief).user_id
    tools = {t.name: t for t in chief_tools(registry, server.services, chief, owner)}
    config = {"configurable": {"user": str(owner), "agent_id": chief, "octop_bot_browser": True}}
    return tools, config


async def test_new_owner_walks_from_welcome_to_done(env_admin_alice):
    client, server, admin, alice = env_admin_alice
    chief = await _bot_owner(client, server, admin)
    await _bot_owner(client, server, alice)
    first = (await client.get(ROUTE, headers=admin)).json()
    assert first == {
        "show": True,
        "status": "pending",
        "step": "welcome",
        "choice": None,
        "team": None,
        "reason": None,
    }
    # A step before starting changes nothing.
    put = await client.put(ROUTE, headers=admin, json={"action": "step", "step": "first_message"})
    assert put.json()["status"] == "pending"
    started = (await client.put(ROUTE, headers=admin, json={"action": "start"})).json()
    assert (started["status"], started["step"]) == ("active", "ask")

    tools, config = _chief(server, chief)
    result = await tools["octop_bot_create_team"].ainvoke(TEAM, config=config)
    assert result["name"] == "外贸团队" and result["section"] == "外贸团队"
    assert "section_error" not in result
    workspace = (await client.get(WORKSPACE, headers=admin)).json()
    names = {b["agent_id"]: b["name"] for b in workspace["bots"]}
    assert [names[i] for i in result["bot_ids"]] == ["阿贸", "小选", "Mia"]
    [group] = workspace["groups"]
    assert group["group_id"] == result["group_id"]
    assert names[group["admin_id"]] == "阿贸"
    assert {names[i] for i in group["member_ids"]} == {"阿贸", "小选", "Mia"}
    [section] = workspace["sections"]
    assert section["name"] == "外贸团队"
    assert set(section["items"]) == {f"group:{group['group_id']}"} | {
        f"bot:{i}" for i in result["bot_ids"]
    }

    ready = (await client.get(ROUTE, headers=admin)).json()
    assert ready["step"] == "team_ready"
    assert ready["team"] == {
        "group_id": group["group_id"],
        "bot_ids": result["bot_ids"],
        "section": "外贸团队",
        "first_task": "帮我回一封报价邮件。",
    }
    # Another device resumes at the same place; starting again keeps the team.
    again = (await client.put(ROUTE, headers=admin, json={"action": "start"})).json()
    assert again["step"] == "team_ready"
    moved = await client.put(ROUTE, headers=admin, json={"action": "step", "step": "first_message"})
    assert moved.json()["step"] == "first_message"
    done = (await client.put(ROUTE, headers=admin, json={"action": "complete"})).json()
    assert (done["show"], done["status"]) == (False, "done")
    assert (await client.get(ROUTE, headers=admin)).json()["status"] == "done"

    # The menu brings it back from the start; the old team stays.
    restarted = (await client.put(ROUTE, headers=admin, json={"action": "restart"})).json()
    assert restarted == {**first, "status": "active"}
    assert len((await client.get(WORKSPACE, headers=admin)).json()["groups"]) == 1

    # Alice has her own onboarding.
    assert (await client.get(ROUTE, headers=alice)).json()["status"] == "pending"


async def test_existing_owner_is_not_guided(env_with_agent):
    client, _server, auth, _bot = env_with_agent
    state = (await client.get(ROUTE, headers=auth)).json()
    assert state == {
        "show": False,
        "status": "done",
        "step": "welcome",
        "choice": None,
        "team": None,
        "reason": "existing",
    }
    assert (await client.put(ROUTE, headers=auth, json={"action": "start"})).json()["show"] is False


async def test_skip_is_final_until_restart(env):
    client, server, auth = env
    await _bot_owner(client, server, auth)
    skipped = await client.put(ROUTE, headers=auth, json={"action": "skip", "reason": "legacy"})
    assert skipped.json() == {
        "show": False,
        "status": "skipped",
        "step": "welcome",
        "choice": None,
        "team": None,
        "reason": "legacy",
    }
    for action in ("start", "complete", "skip"):
        assert (await client.put(ROUTE, headers=auth, json={"action": action})).json()[
            "status"
        ] == "skipped"
    bad = await client.put(ROUTE, headers=auth, json={"action": "jump"})
    assert bad.status_code == 422


async def test_chief_gets_the_onboarding_briefing_only_while_asking(env_with_provider):
    client, server, auth = env_with_provider
    chief = await _bot_owner(client, server, auth)
    manager = server.app_runtime.agent_registry
    owner = manager.get_row(chief).user_id
    request = {"user": str(owner), "configurable": {"octop_bot_browser": True}}

    def briefing(agent_id: str = chief, req: dict[str, Any] = request) -> str:
        return manager._prepare_stream_request(agent_id, req)["configurable"].get(CONFIG_KEY) or ""

    assert "octop_bot_create_team" not in briefing()  # pending: not started yet
    await client.put(ROUTE, headers=auth, json={"action": "start"})
    assert "octop_bot_create_team" in briefing()
    # Only Bot client turns on Chief.
    assert CONFIG_KEY not in manager._prepare_stream_request(chief, {"user": str(owner)}).get(
        "configurable", {}
    )
    tools, config = _chief(server, chief)
    helper = await tools["octop_bot_create"].ainvoke(
        {"name": "助手", "instructions": "帮忙"}, config=config
    )
    assert "octop_bot_create_team" not in briefing(helper)
    # A group made with the older tool also finishes the asking step.
    await tools["octop_bot_create_group"].ainvoke(
        {"name": "小组", "admin_id": helper, "member_ids": []}, config=config
    )
    state = (await client.get(ROUTE, headers=auth)).json()
    assert state["step"] == "team_ready"
    assert state["team"]["bot_ids"] == [helper] and state["team"]["first_task"] == ""
    assert "octop_bot_create_team" not in briefing()


async def test_create_team_validates_and_keeps_what_it_made(env_with_provider):
    client, server, auth = env_with_provider
    chief = await _bot_owner(client, server, auth)
    tools, config = _chief(server, chief)
    for bad in (
        {**TEAM, "admin": "不存在"},
        {**TEAM, "bots": []},
        {**TEAM, "team_name": " "},
        {**TEAM, "bots": [TEAM["bots"][0], TEAM["bots"][0]]},
        {**TEAM, "bots": [{**TEAM["bots"][0], "instructions": " "}]},
    ):
        with pytest.raises(OctopError):
            await tools["octop_bot_create_team"].ainvoke(bad, config=config)
    assert len((await client.get(WORKSPACE, headers=auth)).json()["bots"]) == 1

    taken = await tools["octop_bot_create"].ainvoke(
        {"name": "小选", "instructions": "已有"}, config=config
    )
    partial = await tools["octop_bot_create_team"].ainvoke(TEAM, config=config)
    assert len(partial["bot_ids"]) == 1 and partial["error"]
    workspace = (await client.get(WORKSPACE, headers=auth)).json()
    assert workspace["groups"] == []
    assert {b["name"] for b in workspace["bots"]} >= {"阿贸", "小选"}
    assert taken not in partial["bot_ids"]
    with pytest.raises(OctopError):
        await tools["octop_bot_create_team"].ainvoke(
            TEAM, config={"configurable": {**config["configurable"], "octop_bot_browser": False}}
        )


@pytest.fixture(autouse=True)
def _fresh_team_memory() -> None:
    from octop.infra.agents import bot_tools

    bot_tools._recent_teams.clear()


async def test_create_team_rejects_oversized_and_foreign_calls(env_with_provider):
    client, server, auth = env_with_provider
    chief = await _bot_owner(client, server, auth)
    tools, config = _chief(server, chief)
    bot = TEAM["bots"][0]
    extra = [{"name": f"B{i}", "role": "r", "instructions": "i"} for i in range(4)]
    for bad in (
        {**TEAM, "bots": extra, "admin": "B0"},  # more than 3 in one call
        {**TEAM, "team_name": "团" * 41},
        {**TEAM, "first_task": "x" * 501},
        {**TEAM, "bots": [{**bot, "name": "名" * 41}], "admin": "名" * 41},
        {**TEAM, "bots": [{**bot, "role": "r" * 201}], "admin": bot["name"]},
        {**TEAM, "bots": [{**bot, "instructions": "i" * 8001}], "admin": bot["name"]},
    ):
        with pytest.raises(OctopError) as exc:
            await tools["octop_bot_create_team"].ainvoke(bad, config=config)
        assert exc.value.code.value == "SLASH_BAD_ARGS"
    ctx = config["configurable"]
    for foreign in (
        {**ctx, "user": str(int(ctx["user"]) + 1)},  # someone else's turn
        {**ctx, "agent_id": "not-the-chief"},  # a turn of another bot
    ):
        with pytest.raises(OctopError) as exc:
            await tools["octop_bot_create_team"].ainvoke(TEAM, config={"configurable": foreign})
        assert exc.value.code.value == "FORBIDDEN"
    assert len((await client.get(WORKSPACE, headers=auth)).json()["bots"]) == 1


async def test_a_retried_team_call_in_one_thread_builds_one_team(env_with_provider):
    client, server, auth = env_with_provider
    chief = await _bot_owner(client, server, auth)
    tools, config = _chief(server, chief)
    config = {"configurable": {**config["configurable"], "thread_id": "turn-1"}}
    first, second = await asyncio.gather(
        tools["octop_bot_create_team"].ainvoke(TEAM, config=config),
        tools["octop_bot_create_team"].ainvoke(TEAM, config=config),
    )
    assert first["group_id"] == second["group_id"]
    assert {first.get("reused"), second.get("reused")} == {None, True}
    workspace = (await client.get(WORKSPACE, headers=auth)).json()
    assert len(workspace["bots"]) == 1 + len(TEAM["bots"])
    assert len(workspace["groups"]) == 1


async def test_account_totals_stop_new_bots_and_groups(env_with_provider, monkeypatch):
    from octop.infra.agents import bot_limits

    client, server, auth = env_with_provider
    chief = await _bot_owner(client, server, auth)
    tools, config = _chief(server, chief)
    monkeypatch.setattr(bot_limits, "cloud_tenant", lambda *_: True)
    monkeypatch.setattr(bot_limits, "MAX_BOTS", 2)  # Chief plus one
    partial = await tools["octop_bot_create_team"].ainvoke(TEAM, config=config)
    assert len(partial["bot_ids"]) == 1 and partial["error"] == "BOT_COUNT_LIMIT"
    with pytest.raises(OctopError) as exc:
        await tools["octop_bot_create"].ainvoke(
            {"name": "再来", "instructions": "x"}, config=config
        )
    assert exc.value.code.value == "BOT_COUNT_LIMIT"

    monkeypatch.setattr(bot_limits, "MAX_GROUPS", 0)
    with pytest.raises(OctopError) as exc:
        await tools["octop_bot_create_group"].ainvoke(
            {"name": "群", "admin_id": chief, "member_ids": partial["bot_ids"]}, config=config
        )
    assert exc.value.code.value == "BOT_GROUP_COUNT_LIMIT"
    assert (await client.get(WORKSPACE, headers=auth)).json()["groups"] == []


async def test_bots_on_this_computer_have_no_account_limit(env_with_provider, monkeypatch):
    from octop.infra.agents import bot_limits

    client, server, auth = env_with_provider
    chief = await _bot_owner(client, server, auth)
    tools, config = _chief(server, chief)
    monkeypatch.setattr(bot_limits, "MAX_BOTS", 1)
    monkeypatch.setattr(bot_limits, "MAX_GROUPS", 0)
    result = await tools["octop_bot_create_team"].ainvoke(TEAM, config=config)
    assert "group_id" in result and len(result["bot_ids"]) == len(TEAM["bots"])


async def test_cloud_team_does_not_start_computers(
    tmp_octop_home: Path,
    upstream,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from octop.infra.cloud.computers import manager as computers

    for name, value in {
        "OCTOP_AGS_SECRET_ID": "id",
        "OCTOP_AGS_SECRET_KEY": "key",
        "OCTOP_AGS_TOOL": "octop-bot-desktop",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(computers, "_manager", None)
    started: list[str] = []

    def ensure_running(self: Any, agent_id: str, user_id: int, seed: Any = None) -> str:
        started.append(agent_id)
        return "ins-1"

    monkeypatch.setattr(computers.ComputerManager, "ensure_running", ensure_running)
    async with octop_client(tmp_octop_home) as (client, srv):
        tenant = await _sign_in(client, "13800000021")
        auth = {"Authorization": f"Bearer {tenant['access_token']}"}
        assert (await client.get(ROUTE, headers=auth)).json()["show"] is True
        await client.put(ROUTE, headers=auth, json={"action": "start"})
        chief = (await client.get(WORKSPACE, headers=auth)).json()["chief_id"]
        tools, config = _chief(srv, chief)
        result = await tools["octop_bot_create_team"].ainvoke(TEAM, config=config)
        assert len(result["bot_ids"]) == 3
        # Creating a Bot finishes its harness bootstrap in the background; that is where a
        # workspace probe outside the object store used to boot the Bot's computer.
        await asyncio.gather(
            *(t for t in asyncio.all_tasks() if t.get_name().startswith("bootstrap-agent-"))
        )
        assert started == []


async def test_owner_picks_an_industry_or_a_job_and_chief_is_told(env_with_provider):
    from octop.infra.agents.bot_market.catalog import load_catalog

    client, server, auth = env_with_provider
    chief = await _bot_owner(client, server, auth)
    options = (await client.get(ROUTE + "/options", headers=auth)).json()
    industries, roles = options["industries"], options["roles"]
    categories = {c.id for c in load_catalog().categories}
    assert 8 <= len(industries) <= 12 and 8 <= len(roles) <= 12
    assert {i["id"] for i in industries} <= categories | {"trade", "store"}
    assert all(o["name"] and o["hint"] for o in industries + roles)
    ecommerce = next(i for i in industries if i["id"] == "ecommerce")
    assert ecommerce["hint"].count(",") >= 1  # names of its market templates
    trade = next(i for i in industries if i["id"] == "trade")

    # An unknown id is no choice at all; the guide still starts.
    unknown = await client.put(ROUTE, headers=auth, json={"action": "start", "option": "nope"})
    assert unknown.json()["choice"] is None
    await client.put(ROUTE, headers=auth, json={"action": "restart"})
    started = await client.put(
        ROUTE,
        headers=auth,
        json={"action": "start", "option": "trade", "note": " 主要做家居用品 "},
    )
    choice = started.json()["choice"]
    assert choice == {
        "kind": "industry",
        "id": "trade",
        "label": trade["name"],
        "note": "主要做家居用品",
    }
    manager = server.app_runtime.agent_registry
    owner = manager.get_row(chief).user_id
    request = {"user": str(owner), "configurable": {"octop_bot_browser": True}}

    def briefing() -> str:
        return manager._prepare_stream_request(chief, request)["configurable"][CONFIG_KEY]

    assert trade["name"] in briefing() and "主要做家居用品" in briefing()
    assert trade["hint"] in briefing() and "行业" in briefing()
    # Starting again from another device keeps the choice.
    again = (await client.put(ROUTE, headers=auth, json={"action": "start"})).json()
    assert again["choice"] == choice

    founder = roles[0]
    await client.put(ROUTE, headers=auth, json={"action": "restart"})
    picked = await client.put(
        ROUTE, headers=auth, json={"action": "start", "kind": "role", "option": founder["id"]}
    )
    assert picked.json()["choice"] == {
        "kind": "role",
        "id": founder["id"],
        "label": founder["name"],
        "note": "",
    }
    assert founder["name"] in briefing() and founder["hint"] in briefing()
    assert "岗位" in briefing() and "行业：" not in briefing()
    # An industry id is not a job.
    await client.put(ROUTE, headers=auth, json={"action": "restart"})
    wrong = await client.put(
        ROUTE, headers=auth, json={"action": "start", "kind": "role", "option": "trade"}
    )
    assert wrong.json()["choice"] is None

    await client.put(ROUTE, headers=auth, json={"action": "restart"})
    own = await client.put(
        ROUTE,
        headers=auth,
        json={"action": "start", "kind": "role", "custom": " 独立摄影师 "},
    )
    assert own.json()["choice"] == {
        "kind": "role",
        "id": None,
        "label": "独立摄影师",
        "note": "",
    }
    assert "独立摄影师" in briefing()
    too_long = await client.put(ROUTE, headers=auth, json={"action": "start", "custom": "x" * 61})
    assert too_long.status_code == 422
