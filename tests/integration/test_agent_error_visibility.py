"""Agent payloads redact unclassified startup errors for cloud tenants."""

from octop.i18n.domains.agents import AGENT_START_TIMEOUT, agent_error_message
from tests.support.auth import resolve_user_id


async def test_agent_error_responses(env_admin_alice, monkeypatch) -> None:
    client, server, admin_auth, tenant_auth = env_admin_alice
    owner = await resolve_user_id(client, admin_auth, "alice")
    agent_id = server.services.agent_repo.create(
        agent_id="error-bot", user_id=owner, name="Error Bot"
    )
    raw = "test-secret upstream failure"
    server.services.agent_repo.set_state(agent_id, "failed", error=raw)
    monkeypatch.setenv("OCTOP_BOT_CLOUD", "1")

    listing = await client.get("/api/agents", headers=tenant_auth)
    assert listing.status_code == 200
    assert next(row for row in listing.json() if row["agent_id"] == agent_id)["last_error"] == (
        "Bot 启动失败，请稍后重试。"
    )
    # The status first: opening the agent's detail starts a failed agent again in the
    # background, which clears the error.
    for path in (f"/api/agents/{agent_id}/status", f"/api/agents/{agent_id}"):
        server.services.agent_repo.set_state(agent_id, "failed", error=raw)
        response = await client.get(path, headers=tenant_auth)
        assert response.status_code == 200, response.text
        assert response.json()["last_error"] == "Bot 启动失败，请稍后重试。"
    server.services.agent_repo.set_state(agent_id, "failed", error=raw)
    admin = await client.get(f"/api/agents/{agent_id}", headers=admin_auth)
    assert admin.status_code == 200
    assert admin.json()["last_error"] == raw
    monkeypatch.delenv("OCTOP_BOT_CLOUD")
    server.services.agent_repo.set_state(agent_id, "failed", error=raw)
    off_cloud = await client.get(f"/api/agents/{agent_id}", headers=tenant_auth)
    assert off_cloud.status_code == 200
    assert off_cloud.json()["last_error"] == raw

    monkeypatch.setenv("OCTOP_BOT_CLOUD", "1")
    server.services.agent_repo.set_state(agent_id, "failed", error=AGENT_START_TIMEOUT)
    classified = await client.get(f"/api/agents/{agent_id}/status", headers=tenant_auth)
    assert classified.status_code == 200
    assert classified.json()["last_error"] == agent_error_message(AGENT_START_TIMEOUT, "zh")

    # PATCH schedules a runtime reload, which can replace the stored startup error.
    server.services.agent_repo.set_state(agent_id, "failed", error=raw)
    patched = await client.patch(
        f"/api/agents/{agent_id}", headers=tenant_auth, json={"description": "updated"}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["last_error"] == "Bot 启动失败，请稍后重试。"


async def test_bot_cards_and_market_import_hide_raw_errors(env_admin_alice, monkeypatch) -> None:
    import dataclasses

    from octop.infra.agents import error_display
    from octop.infra.agents.bot_workspace import list_bot_cards

    client, server, admin_auth, alice_auth = env_admin_alice
    monkeypatch.setattr(error_display, "bot_cloud_enabled", lambda: True)
    raw = "test-secret upstream failure"
    headers = {**alice_auth, "Accept-Language": "zh-CN"}

    # Market import: the Bot just created reports its error through the generic text.
    real_get = server.services.agent_repo.get

    def failed_get(agent_id: str):  # type: ignore[no-untyped-def]
        row = real_get(agent_id)
        return dataclasses.replace(row, last_error=raw) if row is not None else None

    monkeypatch.setattr(server.services.agent_repo, "get", failed_get)
    imported = await client.post(
        "/api/octop-bot/market-imports", json={"slug": "store-daily-brief"}, headers=headers
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["last_error"] == "Bot 启动失败，请稍后重试。"
    monkeypatch.setattr(server.services.agent_repo, "get", real_get)

    # A separate failed Bot keeps the imported Bot's background startup from changing this row.
    alice_id = await resolve_user_id(client, admin_auth, "alice")
    agent_id = server.services.agent_repo.create(
        agent_id="failed-card", user_id=alice_id, name="Failed Bot"
    )
    server.services.agent_repo.set_state(agent_id, "failed", error=raw)
    cards = list_bot_cards(server.services, alice_id, "")
    card = next(c for c in cards if c["agent_id"] == agent_id)
    assert card["last_error"] == "Bot 启动失败，请稍后重试。"
    assert raw not in str(cards)
