"""Desktop → cloud move over the real HTTP routes.

One test server plays both sides: the desktop's own service (signed in to Lynxce) and the
Octop Bot cloud it moves to. Lynxce is faked; the tenant is provisioned without minting
model keys.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from octop.api.routers import auth_lynxce, bot_move_in
from octop.infra import desktop
from octop.infra.agents.bot_workspace import chief_key
from octop.infra.auth import lynxce_cloud
from octop.infra.bot_groups.service import create_group, list_messages
from octop.infra.cloud import move_out
from octop.infra.cloud.bot_cloud import accounts as cloud_accounts
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.history.projection import message_inputs


def _lynxce(request: httpx.Request) -> httpx.Response:
    def reply(data):
        return httpx.Response(200, json={"code": 0, "data": data})

    path = request.url.path
    if path == "/api/auth/password-login":
        return reply({"user": {"id": "lx-owner"}, "accessToken": "a1", "refreshToken": "r1"})
    if path == "/api/user/personal-api-keys":
        return reply({"id": "key-1", "secret": "sk-desktop-test"})
    if path == "/api/auth/refresh":
        assert json.loads(request.content) == {"refreshToken": "r1"}
        return reply({"accessToken": "a2", "refreshToken": "r2"})
    if path == "/api/user/profile":
        return reply({"id": "lx-owner", "nickname": "Alison"})
    return httpx.Response(404)


@pytest.fixture
async def both(env_admin_alice, monkeypatch):
    client, server, admin, alice = env_admin_alice
    monkeypatch.setenv("OCTOP_DESKTOP_SHELL", "1")
    monkeypatch.setenv("OCTOP_DESKTOP_PRODUCT", "bot")
    # Cloud routes on, but Bots keep local files: tests have no cloud object store.
    monkeypatch.setattr(auth_lynxce, "bot_cloud_enabled", lambda: True)
    monkeypatch.setattr(auth_lynxce, "bot_cloud_session_login_enabled", lambda: True)
    monkeypatch.setattr(bot_move_in, "bot_cloud_move_in_enabled", lambda: True)
    monkeypatch.setenv("OCTOP_BOT_CLOUD_ORIGIN", "http://cloud.test")
    monkeypatch.setattr(
        lynxce_cloud, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(_lynxce))
    )

    async def provision(services, users, session, locale=None):
        user = await users.resolve_or_create_sso_user(
            provider_id=cloud_accounts._provider_id(services),
            subject=session.account_id,
            claims={"name": "Alison"},
        )
        await lynxce_cloud.keep_session(services, user.id, session)
        return user

    monkeypatch.setattr(cloud_accounts, "provision", provision)
    app = client._transport.app  # noqa: SLF001
    monkeypatch.setattr(
        move_out,
        "httpx",
        SimpleNamespace(
            AsyncClient=lambda base_url, timeout: httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=base_url, timeout=timeout
            ),
            HTTPError=httpx.HTTPError,
        ),
    )
    move_out._runs.clear()
    yield client, server, admin


async def test_desktop_moves_its_team_to_the_cloud_over_http(both):
    client, server, admin = both
    services = server.services
    owner = server.user_manager.get("admin").id

    # The desktop signs in to Lynxce, then has a Bot with a chat and a group.
    r = await client.post(
        "/api/octop-bot/cloud/account",
        headers=admin,
        json={"account": "owner@example.com", "password": "only-for-test"},
    )
    r.raise_for_status()
    assert (await client.get("/api/octop-bot/workspace", headers=admin)).is_success
    chief = services.settings_repo.get(chief_key(owner))
    services.agent_repo.create(
        agent_id="arch01", user_id=owner, name="架构师", system_prompt="架构"
    )
    services.thread_repo.insert(
        thread_id="thr_local",
        agent_id="arch01",
        user_id=owner,
        channel_type="dashboard",
        session_key=ThreadRegistry.dashboard_key(agent_id="arch01", user_id=owner),
        title="选型",
        last_active=1700000000,
    )
    services.thread_message_repo.append_if_ready(
        "thr_local", message_inputs([HumanMessage("用什么库", id="h1"), AIMessage("PG", id="a1")])
    )
    group = create_group(services, owner, name="软件研发组", admin_id=chief, member_ids=["arch01"])
    services.repos.bot_group_repo.import_messages(
        group.group_id,
        [
            {
                "request_id": "r1",
                "slot": "user",
                "role": "user",
                "agent_id": None,
                "text": "开工",
                "created_at": 1700000100,
            },
            {
                "request_id": "r1",
                "slot": "reply:arch01",
                "role": "assistant",
                "agent_id": "arch01",
                "text": "好的",
                "created_at": 1700000200,
            },
        ],
    )

    started = await client.post("/api/octop-bot/cloud/move", headers=admin)
    started.raise_for_status()
    for _ in range(200):
        status = (await client.get("/api/octop-bot/cloud/move", headers=admin)).json()
        if status["state"] != "running":
            break
        await asyncio.sleep(0.05)
    assert status["state"] == "done", status
    token = status["access_token"]
    assert token
    # The desktop gave its Lynxce sign-in away.
    assert lynxce_cloud._load(services, owner) is None

    cloud = {"Authorization": f"Bearer {token}"}
    me = (await client.get("/api/auth/me", headers=cloud)).json()
    tenant = me.get("id") or me.get("user", {}).get("id")
    assert tenant and tenant != owner
    bots = {row.name: row for row in services.agent_repo.list_by_user(tenant)}
    assert "架构师" in bots
    arch = bots["架构师"]
    threads = (await client.get(f"/api/agents/{arch.agent_id}/threads", headers=cloud)).json()
    assert [t["title"] for t in threads] == ["选型"]
    history = (
        await client.get(
            f"/api/agents/{arch.agent_id}/threads/{threads[0]['thread_id']}/history",
            headers=cloud,
        )
    ).json()
    texts = [b.get("text") for m in history["messages"] for b in m["content"]]
    assert texts == ["用什么库", "PG"]
    [moved] = (await client.get("/api/octop-bot/groups", headers=cloud)).json()
    assert moved["name"] == "软件研发组"
    assert [m.text for m in list_messages(services, tenant, moved["group_id"])] == ["开工", "好的"]


async def test_cloud_only_routes_refuse_outside_cloud_mode(both, monkeypatch):
    client, _, admin = both
    monkeypatch.setattr(auth_lynxce, "bot_cloud_session_login_enabled", lambda: False)
    monkeypatch.setattr(bot_move_in, "bot_cloud_move_in_enabled", lambda: False)
    r = await client.post("/api/octop-bot/move-in/notes", headers=admin, json={"text": "x"})
    assert r.status_code == 403
    r = await client.post("/api/auth/lynxce/session-login", json={"refresh_token": "r1"})
    assert r.status_code == 403


def test_move_in_and_session_login_stay_off_in_cloud_mode_unless_switched_on(monkeypatch):
    monkeypatch.setenv("OCTOP_BOT_CLOUD", "1")
    monkeypatch.delenv("OCTOP_BOT_MOVE_IN", raising=False)
    monkeypatch.delenv("OCTOP_BOT_SESSION_LOGIN", raising=False)
    assert not desktop.bot_cloud_move_in_enabled()
    assert not desktop.bot_cloud_session_login_enabled()
    monkeypatch.setenv("OCTOP_BOT_MOVE_IN", "1")
    monkeypatch.setenv("OCTOP_BOT_SESSION_LOGIN", "1")
    assert desktop.bot_cloud_move_in_enabled()
    assert desktop.bot_cloud_session_login_enabled()
    monkeypatch.delenv("OCTOP_BOT_CLOUD")
    assert not desktop.bot_cloud_move_in_enabled()
    assert not desktop.bot_cloud_session_login_enabled()
