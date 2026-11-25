"""Verify the granted user, application, delivery mode and handoff at the tool boundary."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from octop.infra.control.desktop.bot_apps import AllowedApp
from octop.infra.errors import OctopError


@pytest.mark.asyncio
async def test_computer_authorization_handoff_and_window_lease(env_alice_bob_agent, monkeypatch):
    client, server, alice, bob, bot = env_alice_bob_agent
    runtime = server.app_runtime
    repos = server.services.repos
    owner = repos.agent_repo.get(bot).user_id
    computer = runtime.agent_registry.bot_computer
    await runtime.user_manager.set_permissions("alice", ["desktop"])
    await runtime.user_manager.set_permissions("bob", ["desktop"])
    monkeypatch.setattr(computer, "available", lambda: True)
    fake = AllowedApp(id="editor-id", name="Editor")

    async def apps():
        return {72: fake, 88: AllowedApp(id="another-app", name="Other")}

    async def windows(pid):
        return [{"pid": pid, "window_id": pid + 1, "title": "window"}]

    entered = asyncio.Event()
    release = asyncio.Event()
    writes = []

    async def read(session, pid, window_id):
        return [{"token": "current", "value": "old"}]

    async def act(action, args):
        writes.append((action, args))
        entered.set()
        await asyncio.wait_for(release.wait(), timeout=4)
        return {"ok": True}

    monkeypatch.setattr(computer.native, "apps", apps)
    monkeypatch.setattr(computer.native, "windows", windows)
    monkeypatch.setattr(computer.native, "read", read)
    monkeypatch.setattr(computer.native, "act", act)
    path = f"/api/octop-bot/bots/{bot}/computer"
    assert (await client.get(path, headers=bob)).status_code == 404
    assert (await client.get(path, headers=alice)).json()["level"] == "off"
    assert len((await client.get(path + "/apps", headers=alice)).json()) == 2

    async def grant(level):
        result = await client.put(path, headers=alice, json={"level": level, "app_ids": [fake.id]})
        result.raise_for_status()

    async def run(action, **kwargs):
        args = {
            "app_id": fake.id,
            "pid": 72,
            "window_id": 73,
            "token": "current",
            "value": "hello",
            "foreground": False,
        }
        return await computer.run(repos, owner, bot, action, **(args | kwargs))

    with pytest.raises(OctopError):
        await run("windows")
    await grant("view")
    assert [w["app_id"] for w in await run("windows")] == [fake.id]
    with pytest.raises(OctopError):
        await run("read", pid=88, window_id=89)
    with pytest.raises(OctopError):
        await run("read", window_id=100)
    assert (await run("read"))[0]["value"] == "old"
    with pytest.raises(OctopError):
        await run("set_value")
    await grant("background")
    await run("read")
    with pytest.raises(OctopError):
        await run("click", foreground=True)
    with pytest.raises(OctopError):
        await run("click", token="stale")
    running = asyncio.create_task(run("set_value"))
    await asyncio.wait_for(entered.wait(), timeout=4)
    assert (await client.get(path, headers=alice)).json()["active_app"] == "Editor"
    with pytest.raises(OctopError):
        await run("read")
    assert (await client.put(path + "/handoff", headers=alice, json={"paused": True})).json()[
        "paused"
    ]
    release.set()
    assert (await running)["ok"]
    assert len(writes) == 1 and writes[0][1]["delivery_mode"] == "background"
    with pytest.raises(OctopError):
        await run("read")
    assert (
        await client.put(path + "/handoff", headers=alice, json={"paused": False})
    ).status_code == 200
    with pytest.raises(OctopError):
        await run("click")
    await grant("foreground")
    await run("read")
    assert (await run("click", foreground=True))["ok"]
    # Returning control during a pending native read requires a fresh observation.
    reading = asyncio.Event()
    finished = asyncio.Event()

    async def delayed_read(session, pid, window_id):
        reading.set()
        await asyncio.wait_for(finished.wait(), timeout=4)
        return [{"token": "current", "value": "fictional document"}]

    monkeypatch.setattr(computer.native, "read", delayed_read)
    pending = asyncio.create_task(run("read"))
    await asyncio.wait_for(reading.wait(), timeout=4)
    for paused in (True, False):
        response = await client.put(path + "/handoff", headers=alice, json={"paused": paused})
        assert response.json()["paused"] is paused
    finished.set()
    with pytest.raises(OctopError):
        await pending
    assert (owner, bot) not in computer.observed
    assert (await run("read"))[0]["value"] == "fictional document"
    await runtime.user_manager.set_permissions("alice", [])
    assert (await client.get(path, headers=alice)).status_code == 403
    with pytest.raises(OctopError):
        await run("windows")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "discovery", "update"),
    [("read", "apps", "handoff"), ("windows", "windows", "configure")],
)
async def test_new_window_grant_cancels_pending_discovery(
    env_alice_bob_agent, monkeypatch, action, discovery, update
):
    _, server, _, _, bot = env_alice_bob_agent
    runtime = server.app_runtime
    repos = server.services.repos
    owner = repos.agent_repo.get(bot).user_id
    computer = runtime.agent_registry.bot_computer
    await runtime.user_manager.set_permissions("alice", ["desktop"])
    editor = AllowedApp(id="sample.editor", name="Editor")
    monkeypatch.setattr(computer, "available", lambda: True)
    monkeypatch.setattr(computer, "permissions_needed", lambda: [])
    started, finish = asyncio.Event(), asyncio.Event()

    async def apps():
        return {1: editor}

    async def windows(pid):
        return [{"window_id": 2}]

    monkeypatch.setattr(computer.native, "apps", apps)
    monkeypatch.setattr(computer.native, "windows", windows)
    read = AsyncMock(return_value=[])
    monkeypatch.setattr(computer.native, "read", read)
    await computer.configure(repos, owner, bot, "view", [editor.id])
    original = getattr(computer.native, discovery)

    async def delayed(*args):
        started.set()
        await asyncio.wait_for(finish.wait(), timeout=4)
        return await original(*args)

    monkeypatch.setattr(computer.native, discovery, delayed)
    pending = asyncio.create_task(
        computer.run(repos, owner, bot, action, editor.id, 1, 2, "", "", False)
    )
    await asyncio.wait_for(started.wait(), timeout=4)
    if update == "configure":
        await computer.configure(repos, owner, bot, "background", [editor.id])
    else:
        for paused in (True, False):
            await asyncio.to_thread(computer.pause, repos, owner, bot, paused)
    finish.set()
    with pytest.raises(OctopError) as stopped:
        await pending
    assert stopped.value.status == 403
    read.assert_not_awaited()
    assert (owner, bot) not in computer.observed
    listed = await computer.run(repos, owner, bot, "windows", "", 0, 0, "", "", False)
    assert [w["app_id"] for w in listed] == [editor.id]


@pytest.mark.asyncio
async def test_computer_state_reports_missing_macos_grants(env_alice_bob_agent, monkeypatch):
    client, server, alice, _bob, bot = env_alice_bob_agent
    computer = server.app_runtime.agent_registry.bot_computer
    await server.app_runtime.user_manager.set_permissions("alice", ["desktop"])
    path = f"/api/octop-bot/bots/{bot}/computer"
    monkeypatch.setattr(computer, "permissions_needed", lambda: ["screen_recording"])

    monkeypatch.setattr(computer, "available", lambda: False)
    assert (await client.get(path, headers=alice)).json()["permissions_needed"] == []

    monkeypatch.setattr(computer, "available", lambda: True)
    state = (await client.get(path, headers=alice)).json()
    assert state["permissions_needed"] == ["screen_recording"]
