"""Bot market: the public catalog and importing a template as my own Bot."""

from octop.infra.agents.bot_market.catalog import load_catalog

BASE = "/api/octop-bot"
SLUG = "store-daily-brief"


async def test_catalog_is_public_and_localized(env_admin_alice):
    client, _, _, _ = env_admin_alice
    zh = (await client.get(BASE + "/market", headers={"Accept-Language": "zh-CN"})).json()
    en = (await client.get(BASE + "/market", params={"locale": "en"})).json()
    assert [c["id"] for c in zh["categories"]] == [c.id for c in load_catalog().categories]
    card = next(t for t in zh["templates"] if t["slug"] == SLUG)
    assert card["name"] == "店铺经营日报"
    assert next(t for t in en["templates"] if t["slug"] == SLUG)["name"] == "Store Daily Brief"
    assert sum(c["count"] for c in zh["categories"]) == len(zh["templates"])

    detail = (await client.get(f"{BASE}/market/{SLUG}", params={"locale": "zh"})).json()
    assert detail["routines"][0]["when"] == "每天 8:30"
    assert {i["kind"] for i in detail["integrations"]} == {"tencent-docs", "wecom-cli"}
    assert detail["integrations"][0]["name"] == "腾讯文档"

    avatar = await client.get(card["avatar"])
    assert avatar.status_code == 200 and avatar.headers["content-type"] == "image/webp"
    assert (await client.get(f"{BASE}/market/nope")).status_code == 404
    assert (await client.get(BASE + "/market-imports")).status_code == 401


async def test_import_creates_a_ready_bot_with_chosen_routines(env_admin_alice):
    client, server, auth, _ = env_admin_alice
    headers = {**auth, "Accept-Language": "zh-CN"}
    response = await client.post(
        BASE + "/market-imports",
        json={"slug": SLUG, "routines": ["morning-brief"]},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    result = response.json()
    agent_id = result["agent_id"]
    assert result["name"] == "店铺经营日报"
    assert result["integrations"] == ["tencent-docs", "wecom-cli"]

    registry = server.app_runtime.agent_registry
    row = registry.get_row(agent_id)
    assert row.description.startswith("每天早上")
    assert "## 工作守则" in row.system_prompt and "skills/daily-brief/SKILL.md" in row.system_prompt
    assert row.icon_url.startswith(f"/api/agents/{agent_id}/avatar")

    workspace = registry.workspace_for_agent(agent_id)
    # BackendWorkspace keeps skills/ under the system directory.
    home = registry.resolve_workspace_dir(agent_id, persist_if_missing=False)
    skill = (home / ".octop" / "skills" / "daily-brief" / "SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: daily-brief\ndescription: ")
    memory = await workspace.aread_text("MEMORY.md")
    assert "转化率 = 支付买家数 ÷ 访客数" in memory

    jobs = server.app_runtime.cron_manager.list_by_agent(agent_id)
    assert [(j.cron_id, j.name, j.trigger) for j in jobs] == [
        (result["routines"][0], "早间经营日报", "cron:30 8 * * *")
    ]

    card = next(
        b
        for b in (await client.get(BASE + "/workspace", headers=auth)).json()["bots"]
        if b["agent_id"] == agent_id
    )
    assert card["avatar"] == {"shape": "orb", "color": "orange", "source": "photo"}

    again = await client.post(
        BASE + "/market-imports", json={"slug": SLUG, "routines": []}, headers=headers
    )
    second = again.json()
    assert second["name"] == "店铺经营日报 2" and second["routines"] == []
    mine = (await client.get(BASE + "/market-imports", headers=auth)).json()["imports"]
    assert sorted(mine[SLUG]) == sorted([agent_id, second["agent_id"]])

    missing = await client.post(BASE + "/market-imports", json={"slug": "nope"}, headers=auth)
    assert missing.status_code == 404
