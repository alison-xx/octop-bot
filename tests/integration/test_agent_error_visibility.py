"""Agent payloads redact unclassified startup errors for cloud tenants."""

import asyncio

from octop.i18n.domains.agents import AGENT_START_TIMEOUT, agent_error_message
from tests.support.auth import create_user


async def test_agent_error_responses(env_with_provider, monkeypatch) -> None:
    client, server, admin_auth = env_with_provider
    tenant_auth = await create_user(client, admin_auth, username="error_tenant")
    created = await client.post(
        "/api/agents/from-expert/default", headers=tenant_auth, json={"name": "error-bot"}
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["agent_id"]
    # Creating the agent starts it in the background; let that finish before setting up
    # a failed state, or the start would overwrite it.
    for _ in range(200):
        row = server.services.agent_repo.get(agent_id)
        if row is not None and row.last_state not in (None, "created", "starting"):
            break
        await asyncio.sleep(0.05)
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
    patched = await client.patch(
        f"/api/agents/{agent_id}", headers=tenant_auth, json={"description": "updated"}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["last_error"] == "Bot 启动失败，请稍后重试。"

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
