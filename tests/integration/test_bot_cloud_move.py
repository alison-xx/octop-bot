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
from octop.infra.errors import OctopError
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


async def test_large_desktop_chat_resumes_at_the_acknowledged_offset(both, monkeypatch, request):
    from contextlib import contextmanager

    from langchain_core.messages import messages_to_dict
    from langgraph.graph import END, START, MessagesState, StateGraph
    from octop_memory import Memory

    from octop.infra.agents.memory import thread_cleanup
    from octop.infra.cloud import move_in

    client, server, admin = both
    owner = server.user_manager.get("admin").id
    agent_id = "large-chat"
    server.services.agent_repo.create(agent_id=agent_id, user_id=owner, name="Large chat")
    graph = StateGraph(MessagesState)
    graph.add_node("done", lambda state: {})
    graph.add_edge(START, "done")
    graph.add_edge("done", END)
    db = server.services.paths.agent_workspace(agent_id) / "memory.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    memory = Memory(namespace="move-test", backend="sqlite", backend_config={"db_path": str(db)})
    request.addfinalizer(memory.backend.close)
    graph = graph.compile(checkpointer=memory)
    monkeypatch.setattr(
        server.app_runtime.agent_registry, "get_agent", lambda _: SimpleNamespace(graph=graph)
    )
    messages = messages_to_dict([HumanMessage(f"{i}:" + "t" * 100_000) for i in range(110)])
    # A single multibyte message exceeds even the whole-request ceiling.
    messages[17]["data"]["content"] = "界🙂" * 1_510_000
    cleanup_tasks = []
    started = asyncio.Event()
    cleanup_calls = 0
    real_lock = thread_cleanup.FileLock
    loop = asyncio.get_running_loop()

    @contextmanager
    def observed_lock(path):
        nonlocal cleanup_calls
        if path == thread_cleanup.checkpoint_publication_lock(server.services.paths.root, agent_id):
            cleanup_calls += 1
            if cleanup_calls == 2:
                loop.call_soon_threadsafe(started.set)
        with real_lock(path):
            yield

    real_write = move_in.write_checkpoint_messages

    async def simultaneous_cleanup(harness, *, thread_id, messages):
        await real_write(harness, thread_id=thread_id, messages=messages)
        if cleanup_tasks:
            return
        monkeypatch.setattr(thread_cleanup, "FileLock", observed_lock)
        cleanup_tasks.extend(
            (
                asyncio.create_task(
                    asyncio.to_thread(
                        thread_cleanup.gc_orphan_checkpoints,
                        server.services,
                        agent_id=agent_id,
                        apply=True,
                    )
                ),
                asyncio.create_task(
                    asyncio.to_thread(
                        thread_cleanup.sweep_deleted_residuals, server.app_runtime.agent_registry
                    )
                ),
            )
        )
        await asyncio.wait_for(started.wait(), timeout=10)
        assert all(not task.done() for task in cleanup_tasks)

    monkeypatch.setattr(move_in, "write_checkpoint_messages", simultaneous_cleanup)
    header = {
        "source": "desktop:large",
        "bot_id": agent_id,
        "title": "Large history",
        "last_active": 1_800_000_000,
    }
    observed = []
    replies_to_lose = {"first", "final"}

    async def bridge(request):
        assert request.url.path == "/api/octop-bot/move-in/thread-parts"
        assert len(request.content) < 10 * 1024 * 1024
        body = json.loads(request.content)
        observed.append(body["offset"])
        response = await client.post(
            request.url.path,
            headers={**admin, "Content-Type": "application/json"},
            content=request.content,
        )
        assert response.is_success, response.text[:200]
        key = "final" if response.json()["id"] else "first"
        if key in replies_to_lose:
            replies_to_lose.remove(key)
            raise httpx.ReadError("simulated lost acknowledgement")
        return response

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(bridge), base_url="http://test"
    ) as http:
        cloud = move_out._Cloud(http, move_out._Run())
        with pytest.raises(OctopError):
            await move_out._send_thread(cloud, header, messages)
        assert (
            server.services.thread_repo.list_by_agent_user(agent_id=agent_id, user_id=owner) == []
        )
        with pytest.raises(OctopError):
            await move_out._send_thread(cloud, header, messages)
        await move_out._send_thread(cloud, header, messages)
    assert observed[0] == observed[1] == observed[-1] == 0
    assert len([v for v in observed if v > 0]) >= 2
    assert cleanup_tasks
    scan, sweep = await asyncio.gather(*cleanup_tasks)
    assert not scan.orphans and sweep["threads"] == 0
    [thread] = server.services.thread_repo.list_by_agent_user(agent_id=agent_id, user_id=owner)
    rows, more = server.services.thread_message_repo.page(thread.thread_id, limit=200)
    assert not more
    assert len(rows) == len(messages)
    checkpoint = await graph.aget_state({"configurable": {"thread_id": thread.thread_id}})
    for idx, row in enumerate(rows):
        assert json.loads(row.message_json)["data"]["content"] == messages[idx]["data"]["content"]
        assert checkpoint.values["messages"][idx].content == messages[idx]["data"]["content"]


async def test_missing_staged_chat_page_restarts_the_same_snapshot(both, monkeypatch):
    from langchain_core.messages import messages_to_dict
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, MessagesState, StateGraph

    from octop.infra.cloud import move_in, move_wire

    client, server, admin = both
    user = server.user_manager.get("admin")
    services = server.services
    aid = "retry-page"
    services.agent_repo.create(agent_id=aid, user_id=user.id, name="Restore page")
    graph = StateGraph(MessagesState)
    graph.add_node("turn", lambda _state: {})
    graph.add_edge(START, "turn")
    graph.add_edge("turn", END)
    compiled = graph.compile(checkpointer=InMemorySaver())
    registry = server.app_runtime.agent_registry
    monkeypatch.setattr(registry, "get_agent", lambda _: SimpleNamespace(graph=compiled))
    monkeypatch.setattr(move_wire, "PAGE_BYTES", 1024)

    async def discard(_aid, thread_id, *, reclaim=False):
        await compiled.checkpointer.adelete_thread(thread_id)

    monkeypatch.setattr(registry, "delete_thread_checkpoint", discard)
    header = {"source": "desktop:resume-missing", "bot_id": aid, "title": "Recover"}
    messages = messages_to_dict(
        [HumanMessage("Message " + str(i) + ("界" * 1000)) for i in range(3)]
    )
    prefix = move_in._key(user.id, "thread", header["source"]) + ":parts"
    lost, receipts = False, []

    async def bridge(req):
        nonlocal lost
        res = await client.post(
            req.url.path, headers={**admin, "content-type": "application/json"}, content=req.content
        )
        assert res.is_success
        receipts.append(res.json()["next_offset"])
        if not lost:
            lost = True
            services.settings_repo.delete(prefix + ":0")
        return res

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(bridge), base_url="http://test"
    ) as http:
        await move_out._send_thread(move_out._Cloud(http, move_out._Run()), header, messages)
    assert 0 in receipts
    assert services.settings_repo.with_prefix(prefix) == {}
    [thread] = services.thread_repo.list_by_agent_user(agent_id=aid, user_id=user.id)
    rows, more = services.thread_message_repo.page(thread.thread_id, limit=10)
    assert not more
    assert [json.loads(r.message_json)["data"]["content"] for r in rows] == [
        m["data"]["content"] for m in messages
    ]
