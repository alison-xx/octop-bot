"""One-click import of a local Octop install over the real HTTP routes and agent runtime."""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

from octop.config import OctopConfig
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import build_shared_services
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.history.projection import message_inputs
from octop.infra.utils.paths import PathLayout


def _octop_install(user_home: Path) -> None:
    root = user_home / ".octop"
    root.mkdir(parents=True)
    pool = SqlitePool(root / "octop.db")
    run_migrations(pool)
    services = build_shared_services(db=pool, paths=PathLayout(root), config=OctopConfig())
    owner = services.user_repo.create(username="admin", role="admin")
    services.provider_repo.create(
        name="deepseek",
        kind="openai",
        base_url="https://api.deepseek.com/v1",
        api_key="sk-octop",
        models_json='[{"id": "deepseek-chat", "name": "deepseek-chat", "enabled": true}]',
    )
    workspace = root / "agents" / "OCTOPA1"
    workspace.mkdir(parents=True)
    (workspace / "SOUL.md").write_text("I write.", encoding="utf-8")
    services.agent_repo.create(
        agent_id="OCTOPA1",
        user_id=owner,
        name="Octop Writer",
        config_json=json.dumps({"workspace_dir": str(workspace)}),
    )
    threads = ThreadRegistry(session_repo=services.session_repo, thread_repo=services.thread_repo)
    thread_id = threads.create_thread(
        agent_id="OCTOPA1",
        user_id=owner,
        channel_type=ThreadRegistry.CHANNEL_DASHBOARD,
        session_key=ThreadRegistry.dashboard_key(agent_id="OCTOPA1", user_id=owner),
        title="Launch post",
        last_active=5,
    )
    services.thread_message_repo.append_if_ready(
        thread_id,
        message_inputs([HumanMessage("draft the launch post"), AIMessage("Here is a draft.")]),
    )
    pool.close()


async def test_imports_a_local_octop_and_loads_it(env_with_provider, tmp_path, monkeypatch):
    client, server, admin = env_with_provider
    monkeypatch.setenv("OCTOP_DESKTOP_SHELL", "1")
    monkeypatch.setenv("OCTOP_DESKTOP_PRODUCT", "bot")
    user_home = tmp_path / "user-home"
    _octop_install(user_home)
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.setenv("USERPROFILE", str(user_home))

    found = (await client.get("/api/octop-bot/octop-import", headers=admin)).json()
    assert found["available"] is True
    assert [(a["agent_id"], a["threads"], a["exists"]) for a in found["agents"]] == [
        ("OCTOPA1", 1, False)
    ]

    response = await client.post("/api/octop-bot/octop-import", headers=admin)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["providers"] == ["deepseek"]
    assert [(a["agent_id"], a["status"], a["threads"]) for a in report["agents"]] == [
        ("OCTOPA1", "imported", 1)
    ]

    # The assistant runs here, with its workspace and its chat.
    assert server.app_runtime.agent_registry.get_agent("OCTOPA1") is not None
    agents = (await client.get("/api/agents", headers=admin)).json()
    assert any(a.get("agent_id", a.get("id")) == "OCTOPA1" for a in agents)
    listed = (await client.get("/api/agents/OCTOPA1/threads", headers=admin)).json()
    threads = listed["items"] if isinstance(listed, dict) else listed
    [thread] = [t for t in threads if t["title"] == "Launch post"]
    history = await client.get(
        f"/api/agents/OCTOPA1/threads/{thread['thread_id']}/history", headers=admin
    )
    assert history.status_code == 200, history.text
    assert "Here is a draft." in history.text
    soul = server.paths.agent_workspace("OCTOPA1") / "SOUL.md"
    assert soul.read_text(encoding="utf-8") == "I write."

    again = (await client.post("/api/octop-bot/octop-import", headers=admin)).json()
    assert [(a["status"], a["reason"]) for a in again["agents"]] == [("skipped", "exists")]


async def test_octop_import_is_desktop_only(env_with_provider, monkeypatch):
    client, _, admin = env_with_provider
    monkeypatch.delenv("OCTOP_DESKTOP_SHELL", raising=False)
    response = await client.get("/api/octop-bot/octop-import", headers=admin)
    assert response.status_code == 403
