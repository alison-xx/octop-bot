"""Desktop contract tests. All cloud and Lynxce traffic uses in-process fakes."""

import asyncio
import base64
import io
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from octop.api.common.bot_desktop import _desktop_services
from octop.api.deps import current_user, get_server
from octop.api.routers import auth
from octop.api.routers import bot_desktop_computers as router
from octop.config import OctopConfig
from octop.infra.auth import lynxce_cloud
from octop.infra.auth.tokens import PURPOSE_ACCESS, sign_token
from octop.infra.cloud.computers import remote
from octop.infra.cloud.computers.remote import RemoteComputerManager, RemoteDriver
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import build_shared_services
from octop.infra.errors import OctopError
from octop.infra.utils.paths import PathLayout


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    monkeypatch.setenv("OCTOP_DESKTOP_SHELL", "1")
    monkeypatch.setenv("OCTOP_DESKTOP_PRODUCT", "bot")
    paths = PathLayout(tmp_path)
    db = SqlitePool(paths.db)
    run_migrations(db)
    services = build_shared_services(db=db, paths=paths, config=OctopConfig())
    owner = services.user_repo.create(username="test-owner", role="member")
    guest = services.user_repo.create(username="test-guest", role="admin")
    services.agent_repo.create(agent_id="writer", user_id=owner, name="Writer")
    grant = lynxce_cloud._Grant("test-account", None, "test-binding", "test-access", "test-refresh")
    lynxce_cloud._save(services, owner, grant)

    calls = []
    failures = []
    clipboard = [""]

    def cloud(request):
        calls.append(request)
        path = request.url.path
        if path.endswith("/token-login"):
            assert json.loads(request.content) == {"access_token": "test-access"}
            return httpx.Response(200, json={"access_token": "test-scoped", "expires_in": 3600})
        if "/screen-sessions/" in path:
            assert request.headers["X-Octop-Screen-Session"] == "test-cloud-session"
            assert "authorization" not in request.headers
            assert path in {
                "/api/octop-bot/screen-sessions/type",
                "/api/octop-bot/screen-sessions/clipboard",
            }
            if request.method == "POST":
                clipboard[0] = json.loads(request.content)["text"]
                return httpx.Response(204)
            return httpx.Response(200, json={"text": clipboard[0]})
        assert request.headers["authorization"] == "Bearer test-scoped"
        assert "test-scoped" not in str(request.url)
        if "/remote-bots/" in path:
            return httpx.Response(
                200,
                json={"agent_id": "test-shadow", "origin": path.split("/")[-1], "created": True},
            )
        assert "/computers/test-shadow" in path
        if failures:
            response = failures.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        leaf = path.split("/")[-1]
        if leaf == "screen":
            return httpx.Response(
                200,
                json={
                    "ws_path": path + "/ws?ticket=test-once",
                    "expires_in": 60,
                    "session": "test-cloud-session",
                    **(
                        {"session_transport": "header", "session_expires_in": 1800}
                        if request.headers.get("X-Octop-Screen-Transport") == "header"
                        else {}
                    ),
                },
            )
        if leaf == "files":
            assert request.url.params["path"] == "notes.txt"
            if request.method == "GET":
                return httpx.Response(200, content=b"abc")
            return httpx.Response(200, json={"path": "notes.txt", "size": len(request.content)})
        if leaf == "screenshot":
            return httpx.Response(200, content=b"test-png")
        if leaf == "accessibility":
            return httpx.Response(200, json={"xml": "<desktop/>"})
        if leaf == "python":
            return httpx.Response(200, json={"taken_over": False, "output": "ready"})
        if leaf == "run":
            return httpx.Response(
                200, json={"taken_over": False, "exit_code": 0, "output": "ready"}
            )
        return httpx.Response(200, json={"takeover": False, "state": "none", "spec": "standard"})

    monkeypatch.setattr(
        remote,
        "cloud_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(cloud), base_url="https://cloud.test"
        ),
    )

    jwt_key = services.secret_repo.get_or_create("jwt", lambda: b"s" * 32)
    login = sign_token(
        jwt_key, sub=owner, uname="test-owner", role="member", purpose=PURPOSE_ACCESS
    )
    app = FastAPI()
    app.include_router(router.router, prefix="/api/octop-bot")
    app.include_router(auth.router, prefix="/api/auth")
    app.dependency_overrides[_desktop_services] = lambda: services
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=owner)
    app.dependency_overrides[get_server] = lambda: SimpleNamespace(
        services=services,
        user_manager=SimpleNamespace(
            get_by_id=services.user_repo.get,
            revoke_sessions=services.user_repo.bump_session_version,
        ),
        app_runtime=SimpleNamespace(agent_registry=SimpleNamespace(reload=AsyncMock())),
    )

    @app.exception_handler(OctopError)
    async def error(request, exc):
        return JSONResponse(exc.to_envelope(), status_code=exc.status)

    yield SimpleNamespace(
        services=services,
        owner=owner,
        guest=guest,
        app=app,
        calls=calls,
        login=login,
        failures=failures,
        grant=grant,
    )
    db.close()


def client(env):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {env.login}"},
    )


TARGET = "/api/octop-bot/bots/writer/computer-target"
COMPUTER = "/api/octop-bot/computers/writer"


async def test_switch_and_ownership(desktop):
    async with client(desktop) as api:
        assert (await api.get(COMPUTER)).status_code == 404
        assert (await api.put(TARGET, json={"target": "cloud"})).json() == {"target": "cloud"}
        assert (await api.get(COMPUTER)).json()["state"] == "none"
        assert (await api.get(COMPUTER)).is_success
        assert len([r for r in desktop.calls if "/remote-bots/" in r.url.path]) == 1
        desktop.app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=desktop.guest)
        before = len(desktop.calls)
        assert (await api.get(COMPUTER)).status_code == 404
        assert (await api.put(TARGET, json={"target": "local"})).status_code == 404
        assert len(desktop.calls) == before
        desktop.app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=desktop.owner)
        assert (await api.put(TARGET, json={"target": "local"})).is_success
        assert (await api.get(COMPUTER)).status_code == 404
        desktop.services.secret_repo.delete(lynxce_cloud._key(desktop.owner))
        assert (await api.put(TARGET, json={"target": "cloud"})).status_code == 409


async def test_new_desktop_process_registers_before_using_a_cached_shadow(desktop):
    async with client(desktop) as api:
        assert (await api.put(TARGET, json={"target": "cloud"})).is_success
        registry = desktop.services.settings_repo
        key, raw = next(iter(registry.with_prefix(f"octop_bot:shadow:{desktop.owner}:").items()))
        before_restart = json.loads(raw)
        before_restart.update(id="old-cloud-id", updated=remote._PROCESS_STARTED_AT - 1)
        registry.set(key, json.dumps(before_restart))
        desktop.calls.clear()
        assert (await api.get(COMPUTER)).is_success
        assert (await api.get(COMPUTER)).is_success
        assert sum("/remote-bots/" in call.url.path for call in desktop.calls) == 1
        assert json.loads(registry.get(key))["id"] == "test-shadow"


async def test_one_retry_busy_and_logout(desktop, monkeypatch):
    async with client(desktop) as api:
        assert (await api.put(TARGET, json={"target": "cloud"})).is_success
        desktop.failures.extend(
            [
                httpx.Response(401),
                httpx.Response(
                    503,
                    json={
                        "error": {
                            "code": "BOT_COMPUTER_BUSY",
                            "message": "private upstream details",
                        }
                    },
                ),
            ]
        )
        res = await api.get(COMPUTER)
        assert res.status_code == 503 and res.json()["error"]["code"] == "BOT_COMPUTER_BUSY"
        assert "private upstream" not in res.text
        assert sum(r.url.path.endswith("/token-login") for r in desktop.calls) == 2
        monkeypatch.setattr(lynxce_cloud, "_send", AsyncMock())
        await lynxce_cloud.logout_cloud(
            desktop.services, desktop.owner, expected_account_id=desktop.grant.account_id
        )
        assert desktop.calls[-1].url.path.endswith("/pause")
        assert desktop.services.secret_repo.get(remote._key(desktop.owner)) is None
        assert (await api.get(COMPUTER)).status_code == 409


async def test_driver_and_transfers(desktop, monkeypatch):
    async with client(desktop) as api:
        await api.put(TARGET, json={"target": "cloud"})
        manager = RemoteComputerManager.owned(desktop.services, desktop.owner, "writer")
        driver = RemoteDriver(manager)
        assert (await api.get(COMPUTER + "/screenshot")).content == b"test-png"
        assert (await api.get(COMPUTER + "/accessibility")).json()["xml"] == "<desktop/>"
        assert await asyncio.to_thread(driver.run, "writer", "echo ready", 3) == (0, "ready")
        assert (
            await api.post(COMPUTER + "/python", json={"code": "print('ready')"})
        ).status_code == 429
        remote._next_command.clear()
        assert (await api.post(COMPUTER + "/python", json={"code": "print('ready')"})).json()[
            "output"
        ] == "ready"
        remote._next_command.clear()
        desktop.failures.append(httpx.Response(200, json={"taken_over": True, "output": "waiting"}))
        assert (await api.post(COMPUTER + "/python", json={"code": "print('ready')"})).json()[
            "taken_over"
        ]
        assert await asyncio.to_thread(driver.read, "writer", "notes.txt") == b"abc"
        await asyncio.to_thread(driver.write, "writer", "notes.txt", b"draft")
        assert (await api.get(COMPUTER + "/files", params={"path": "notes.txt"})).content == b"abc"
        assert (
            await api.put(COMPUTER + "/files", params={"path": "notes.txt"}, content=b"abc")
        ).json()["size"] == 3
        monkeypatch.setattr(router, "MAX_FILE_BYTES", 2)
        assert (
            await api.put(COMPUTER + "/files", params={"path": "notes.txt"}, content=b"abc")
        ).status_code == 413
        assert (await api.get(COMPUTER + "/files", params={"path": "notes.txt"})).status_code == 413


async def test_model_screen_results_and_legacy_service(desktop):
    from PIL import Image

    from octop.infra.cloud.computers.computer_use import computer_use_tool

    async with client(desktop) as api:
        await api.put(TARGET, json={"target": "cloud"})
    manager = RemoteComputerManager.owned(desktop.services, desktop.owner, "writer")
    tool = computer_use_tool(manager, "writer", desktop.owner, remote_action=manager.model_action)
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buffer, "JPEG")
    picture = base64.b64encode(buffer.getvalue()).decode()
    capable = httpx.Response(200, json={"model_screen_version": 1})
    config = {"configurable": {"thread_id": "chat-one"}}

    async def act(action, **params):
        return await tool.ainvoke(
            {
                "type": "tool_call",
                "id": "call",
                "name": "cloud_computer",
                "args": {"action": action, **params},
            },
            config=config,
        )

    for status, action in [("handback", "move"), ("ok", "screenshot")]:
        desktop.failures.extend(
            [
                capable,
                httpx.Response(
                    200, json={"status": status, "text": status, "image_base64": picture}
                ),
            ]
        )
        result = await act(action, x=10, y=10)
        note, observation = result.update["messages"]
        assert status in note.content
        assert ("not performed" in note.content) == (status == "handback")
        assert observation.content_blocks[-1]["base64"] == picture
        assert ("handback" in observation.content_blocks[0]["text"].lower()) == (
            status == "handback"
        )
    for status in ("taken_over", "busy", "withheld", "needs_human"):
        desktop.failures.extend(
            [
                capable,
                httpx.Response(200, json={"status": status, "text": status, "image_base64": None}),
            ]
        )
        assert (await act("move", x=len(status), y=10)).content == status
    desktop.calls.clear()
    for state in ({}, {"model_screen_version": True}):
        desktop.failures.append(httpx.Response(200, json=state))
        note = (await act("elements")).content
        assert "upgrade" in note.lower() or "升级" in note
    assert [r.method for r in desktop.calls] == ["GET", "GET"]
    desktop.failures.extend([capable, httpx.Response(404)])
    note = (await act("screenshot")).content
    assert "upgrade" in note.lower() or "升级" in note
    assert desktop.calls[-1].url.path.endswith("/model-screen")


@pytest.mark.parametrize(
    "path", ["../outside", "/absolute", "C:/file", r"a\..\outside", ".octop/auth/test"]
)
def test_transfer_path(path):
    with pytest.raises(OctopError):
        remote.transfer_path(path)


async def test_screen_uses_an_independent_one_time_ticket(desktop):
    async with client(desktop) as api:
        await api.put(TARGET, json={"target": "cloud"})
        res = await api.post(COMPUTER + "/screen")
        assert res.is_success
        assert all(
            s not in res.text
            for s in ["test-once", "test-scoped", "test-cloud-session", "test-shadow"]
        )
        ticket = res.json()["ws_path"].split("ticket=")[1]
        ws = SimpleNamespace(close=AsyncMock())
        await router.screen_ws(ws, "different", ticket)
        ws.close.assert_awaited_once_with(code=4001)
        assert ticket not in router._tickets


@pytest.mark.parametrize("revoke", ["version", "logout"])
async def test_screen_clipboard_is_bound_to_one_open_connection(desktop, monkeypatch, revoke):
    connected, finished = asyncio.Event(), asyncio.Event()

    async def wait_for_disconnect():
        yield b"RFB 003.008\n"
        await finished.wait()

    class FakeUpstream:
        send = AsyncMock()

        def __aiter__(self):
            return wait_for_disconnect()

    @asynccontextmanager
    async def connect(url, **kwargs):
        assert url.endswith("/computers/test-shadow/screen/ws?ticket=test-once")
        yield FakeUpstream()

    monkeypatch.setattr(router.websockets, "connect", connect)

    async def accept(**_kwargs):
        connected.set()

    ws = SimpleNamespace(
        accept=accept, close=AsyncMock(), send_bytes=AsyncMock(), iter_bytes=wait_for_disconnect
    )
    base = "/api/octop-bot/screen-sessions"
    async with client(desktop) as api:
        await api.put(TARGET, json={"target": "cloud"})
        body = (
            await api.post(COMPUTER + "/screen", headers={"X-Octop-Screen-Transport": "header"})
        ).json()
        assert body["session_transport"] == "header" and body["session_expires_in"] == 1800
        assert body["session_renewable"] is False
        assert body["session"] not in body["ws_path"] and "test-cloud-session" not in str(body)
        headers = {"X-Octop-Screen-Session": body["session"]}
        assert (await api.get(base + "/clipboard", headers=headers)).status_code == 404
        run = asyncio.create_task(
            router.screen_ws(ws, "writer", body["ws_path"].split("ticket=")[1])
        )
        try:
            await asyncio.wait_for(connected.wait(), timeout=5)
            assert (
                await api.post(base + "/type", json={"text": "中文联调"}, headers=headers)
            ).status_code == 204
            assert (await api.get(base + "/clipboard", headers=headers)).json() == {
                "text": "中文联调"
            }
            desktop.app.dependency_overrides[current_user] = lambda: SimpleNamespace(
                id=desktop.guest
            )
            assert (await api.get(base + "/clipboard", headers=headers)).status_code == 404
            desktop.app.dependency_overrides[current_user] = lambda: SimpleNamespace(
                id=desktop.owner
            )
            active = router._active_sessions[body["session"]]
            deadline = active.session_until
            active.session_until = 0
            assert (await api.get(base + "/clipboard", headers=headers)).status_code == 404
            active.session_until = deadline
            second = (await api.post(COMPUTER + "/screen")).json()["ws_path"].split("ticket=")[1]
            if revoke == "version":
                desktop.services.user_repo.bump_mfa_version(desktop.owner)
            else:
                desktop.app.dependency_overrides[current_user] = lambda: SimpleNamespace(
                    id=desktop.owner, username="test-owner"
                )
                assert (await api.post("/api/auth/logout")).status_code == 204
            assert lynxce_cloud.has_session(desktop.services, desktop.owner)
            # The existing connection closes; its unconsumed sibling cannot connect.
            await asyncio.wait_for(asyncio.shield(run), timeout=5)
            unused = SimpleNamespace(close=AsyncMock(), accept=AsyncMock())
            await router.screen_ws(unused, "writer", second)
            unused.accept.assert_not_awaited()
            unused.close.assert_awaited()
        finally:
            finished.set()
            await run
        ws.send_bytes.assert_awaited_once_with(b"RFB 003.008\n")
        FakeUpstream.send.assert_awaited_once_with(b"RFB 003.008\n")
        assert body["session"] not in router._active_sessions
        assert (await api.get(base + "/clipboard", headers=headers)).status_code == 404


async def test_deleting_while_signed_out_keeps_cleanup_for_original_account(desktop):
    async with client(desktop) as api:
        await api.put(TARGET, json={"target": "cloud"})
        await api.post(COMPUTER + "/screen")
        screen = next(r for r in desktop.calls if r.url.path.endswith("/screen"))
        assert screen.extensions["timeout"]["read"] >= 360
    settings = desktop.services.settings_repo
    prefix = f"octop_bot:shadow:{desktop.owner}:"
    (key,) = settings.with_prefix(prefix)
    desktop.services.agent_repo.delete("writer")
    desktop.services.secret_repo.delete(lynxce_cloud._key(desktop.owner))
    await remote.clean_deleted_shadows(desktop.services, desktop.owner)
    assert settings.get(key)
    other = lynxce_cloud._Grant("another-account", None, "other", "other-access", "other-refresh")
    lynxce_cloud._save(desktop.services, desktop.owner, other)
    await remote.clean_deleted_shadows(desktop.services, desktop.owner)
    assert settings.get(key)
    lynxce_cloud._save(desktop.services, desktop.owner, desktop.grant)
    await remote.clean_deleted_shadows(desktop.services, desktop.owner)
    assert not settings.get(key)
    assert desktop.calls[-1].method == "DELETE"
    assert desktop.calls[-1].url.path.endswith(":writer")


async def test_cloud_command_timeout_is_reported_without_repeating_it(desktop):
    async with client(desktop) as api:
        await api.put(TARGET, json={"target": "cloud"})
        desktop.failures.append(httpx.ReadTimeout("fixture transport timed out"))
        reply = await api.post(COMPUTER + "/run", json={"command": "echo ready", "timeout": 15})
        assert reply.status_code == 504
        assert reply.json()["error"]["code"] == "BOT_COMPUTER_OPERATION_TIMEOUT"
        assert "fixture transport" not in reply.text
        commands = [r for r in desktop.calls if r.url.path.endswith("/run")]
        assert len(commands) == 1 and commands[0].extensions["timeout"]["read"] >= 375


async def test_rejected_upstream_token_keeps_local_login(desktop):
    async with client(desktop) as api:
        await api.put(TARGET, json={"target": "cloud"})
        for _ in range(2):
            desktop.failures.append(httpx.Response(401, json={"error": {"code": "TOKEN_EXPIRED"}}))
        reply = await api.get(COMPUTER)
        assert reply.status_code == 401
        assert reply.json()["error"]["code"] == "BOT_CLOUD_REQUEST_REJECTED"
        assert (await api.get(COMPUTER)).is_success


async def test_transfer_slots_release_tempfiles_on_cancel_and_error(desktop):
    manager = SimpleNamespace(user_id=desktop.owner)
    slot = asynccontextmanager(router._transfer_spool)
    entered = asyncio.Event()

    async def held():
        async with slot(manager) as file:
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                assert not file.closed

    first = asyncio.create_task(held())
    await entered.wait()
    try:
        with pytest.raises(RuntimeError, match="transfer stopped"):
            async with slot(manager) as second:
                with pytest.raises(OctopError) as unavailable:
                    async with slot(manager):
                        pytest.fail("unexpected third transfer")
                assert unavailable.value.status == 429
                async with slot(SimpleNamespace(user_id=desktop.guest)):
                    pass
                raise RuntimeError("transfer stopped")
        assert second.closed
    finally:
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
    assert desktop.owner not in router._transfer_counts
