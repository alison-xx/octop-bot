"""Ordinary Lynxce Cloud login stays bound to the local caller across refresh and account changes."""

import asyncio
import json
from collections import Counter
from collections.abc import AsyncIterator
from threading import Event
from typing import Any

import httpx
import pytest
from filelock import Timeout

from octop.infra.auth import lynxce_cloud as cloud
from octop.infra.auth.lynxce import is_connected as model_connected
from octop.infra.db.services import SharedServices
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.server import OctopServer

API = "/api/octop-bot/cloud/account"
CAPABILITIES = "/api/user/cloud-work/capabilities"
TASKS = "/api/user/cloud-work/tasks"
Auth = dict[str, str]
Env = tuple[httpx.AsyncClient, OctopServer, Auth, Auth]


class Upstream:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.refresh_status = 200
        self.operation_status = 200
        self.expired: set[str] = set()
        self.observed: list[str] = []
        self.envelope: dict[str, Any] | None = None
        self.refreshed_account: str | None = None

    def __call__(self, req: httpx.Request) -> httpx.Response:
        assert req.url.host == "api.lynxce.cn" and req.url.scheme == "https"
        assert req.headers["X-Lynxce-Client"] == "web" and "x-lynxce-app-id" not in req.headers
        path = req.url.path
        self.counts[path] += 1
        if path == "/api/auth/password-login":
            payload = json.loads(req.content)
            assert "Authorization" not in req.headers
            if payload["password"] != "test-password":
                return httpx.Response(401, json={"message": payload["password"]})
            uid = payload["account"]
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "accessToken": f"access-{uid}",
                        "refreshToken": f"refresh-{uid}",
                        "user": {
                            "id": uid,
                            "displayName": "Name " + uid,
                            "avatarUrl": f"https://cdn.avatars.test/{uid}.jpg",
                            "email": "private@example.invalid",
                        },
                        "apiKey": {"secretFull": "sensitive-api-key"},
                        "quota": {"private": True},
                    },
                },
            )
        if path == "/api/auth/refresh":
            assert "Authorization" not in req.headers
            value = json.loads(req.content)["refreshToken"]
            return httpx.Response(
                self.refresh_status,
                json={
                    "code": 0,
                    "data": {
                        "accessToken": value.replace("refresh-", "renewed-"),
                        "refreshToken": value + "-new",
                    },
                },
            )
        bearer = req.headers["Authorization"].removeprefix("Bearer ")
        self.observed.append(bearer)
        if path == "/api/auth/logout":
            return httpx.Response(503, text="unavailable")
        if bearer in self.expired:
            return httpx.Response(401)
        if path == "/api/user/profile":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "id": self.refreshed_account
                        or bearer.removeprefix("renewed-").removeprefix("access-"),
                        "avatarUrl": "https://cdn.avatars.test/profile.jpg",
                    },
                },
            )
        return httpx.Response(
            self.operation_status,
            json=(
                self.envelope
                if self.envelope is not None
                else {"code": 0, "data": {"fixture-owner": bearer}}
            ),
        )


@pytest.fixture
def upstream(monkeypatch: pytest.MonkeyPatch) -> Upstream:
    fake = Upstream()
    monkeypatch.setenv("OCTOP_DESKTOP_SHELL", "1")
    monkeypatch.setenv("OCTOP_DESKTOP_PRODUCT", "bot")
    monkeypatch.setattr(
        cloud, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake))
    )
    return fake


async def test_password_login_encrypted_grants_are_local_owner_only(
    env_admin_alice: Env, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, server, admin, alice = env_admin_alice
    assert server.services is not None
    services = server.services
    aid = server.user_manager.get("alice").id
    blank = {"connected": False, "account_id": None, "display_name": None, "avatar_url": None}
    assert (await client.get(API)).status_code == 401
    assert (await client.get(API, headers=alice)).json() == blank
    malformed = await client.post(
        API, headers=alice, json={"password": "unique-secret-missing-account"}
    )
    assert malformed.status_code == 422 and "unique-secret" not in malformed.text
    bad = await client.post(
        API, headers=alice, json={"account": "a", "password": "unique-bad-password"}
    )
    assert bad.status_code == 403 and "unique-bad-password" not in bad.text
    result = await client.post(
        API, headers=alice, json={"account": "a", "password": "test-password"}
    )
    result.raise_for_status()
    assert result.json() == {
        "connected": True,
        "account_id": "a",
        "display_name": "Name a",
        "avatar_url": "https://cdn.avatars.test/a.jpg",
    }
    assert (await client.get(API, headers=admin)).json() == blank
    assert not model_connected(services, aid)
    raw = services.secret_repo.get(cloud._key(aid))
    assert raw
    for secret in [
        b"access-a",
        b"refresh-a",
        b"test-password",
        b"sensitive-api-key",
        b"example.invalid",
    ]:
        assert secret not in raw and secret.decode() not in result.text
    assert (await cloud.request_cloud(services, aid, "GET", CAPABILITIES))[
        "fixture-owner"
    ] == "access-a"
    assert (await client.get(API, headers=alice)).json() == result.json()
    denied = await client.post(
        API, headers=alice, json={"account": "b", "password": "invalid-password"}
    )
    assert denied.status_code == 403 and cloud.cloud_status(services, aid).account_id == "a"
    monkeypatch.delenv("OCTOP_DESKTOP_PRODUCT")
    assert (await client.get(API, headers=alice)).status_code == 403
    with pytest.raises(OctopError) as other_product:
        await cloud.request_cloud(services, aid, "GET", CAPABILITIES)
    assert other_product.value.code == ErrorCode.FORBIDDEN
    monkeypatch.setenv("OCTOP_DESKTOP_PRODUCT", "bot")
    assert (await client.delete(API, headers=alice)).json() == blank
    assert (
        not services.secret_repo.get(cloud._key(aid)) and upstream.counts["/api/auth/logout"] == 1
    )
    (
        await client.post(API, headers=alice, json={"account": "a", "password": "test-password"})
    ).raise_for_status()
    (await client.delete(f"/api/users/{aid}", headers=admin)).raise_for_status()
    assert not services.secret_repo.get(cloud._key(aid))
    assert not services.secret_repo.get(cloud._key(aid) + ".fernet")


async def test_restricted_requests_and_refresh_isolation(
    env_admin_alice: Env, upstream: Upstream
) -> None:
    client, server, admin, alice = env_admin_alice
    assert server.services is not None
    services = server.services
    uid = server.user_manager.get("alice").id
    admin_id = server.user_manager.get("admin").id
    for auth, account in ((alice, "alice-cloud"), (admin, "admin-cloud")):
        (
            await client.post(
                API, headers=auth, json={"account": account, "password": "test-password"}
            )
        ).raise_for_status()
    denied = [
        ("GET", "https://example.invalid/api/user/cloud-work/tasks"),
        ("GET", "//example.invalid/path"),
        ("GET", "/api/user/web-chat-sessions/.."),
        ("GET", "/api/user/web-chat-sessions/%2e%2e"),
        ("GET", "/api/user/cloud-work/tasks?sessionId=abc"),
        ("GET", "/api/user/profile"),
        ("POST", "/api/auth/refresh"),
        ("DELETE", "/api/user/scheduled-tasks/abc"),
        ("POST", "/api/user/cloud-work/tasks/../actions"),
    ]
    for method, path in denied:
        with pytest.raises(OctopError) as invalid:
            await cloud.request_cloud(services, uid, method, path)
        assert invalid.value.code == ErrorCode.FORBIDDEN
    with pytest.raises(OctopError):
        await cloud.request_cloud(
            services, uid, "GET", TASKS, params={"baseUrl": "https://example.invalid"}
        )
    with pytest.raises(OctopError) as switched:
        await cloud.request_cloud(services, uid, "POST", TASKS, expected_account_id="admin-cloud")
    assert switched.value.code == ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED and not upstream.observed
    await cloud.request_cloud(services, uid, "GET", "/api/user/web-chat-sessions/cowork%3Aa1.b2")
    await cloud.request_cloud(
        services,
        uid,
        "POST",
        "/api/user/web-chat-sessions/cowork:a1.b2/items",
        json={"items": [{"role": "user", "content": "hello"}]},
        expected_account_id="alice-cloud",
    )
    with pytest.raises(OctopError) as unsafe_action:
        await cloud.request_cloud(
            services, uid, "POST", TASKS + "/task-id/actions", json={"action": "budget"}
        )
    assert unsafe_action.value.code == ErrorCode.FORBIDDEN
    upstream.expired.add("access-alice-cloud")
    results = await asyncio.gather(
        *(
            cloud.request_cloud(services, uid, "GET", TASKS, params={"sessionId": "s"})
            for _ in range(2)
        )
    )
    assert all(result == {"fixture-owner": "renewed-alice-cloud"} for result in results)
    assert upstream.counts["/api/auth/refresh"] == 1
    assert (await cloud.request_cloud(services, admin_id, "GET", CAPABILITIES))[
        "fixture-owner"
    ] == "access-admin-cloud"
    for status in (402, 403, 404, 409, 422, 429, 503):
        upstream.operation_status = status
        with pytest.raises(OctopError) as exc:
            await cloud.request_cloud(
                services,
                uid,
                "POST",
                TASKS,
                json={"prompt": "work"},
                expected_account_id="alice-cloud",
            )
        assert exc.value.status == (502 if status == 503 else status)
    assert upstream.counts["/api/auth/refresh"] == 1
    assert (
        upstream.counts[TASKS] == 10
    )  # 2 successful reads, 1 expired read, 7 failed writes, no write retries
    upstream.operation_status = 200
    for invalid in ({"code": False, "data": {}}, {"code": 1, "data": {}}, {"code": 0}):
        upstream.envelope = invalid
        with pytest.raises(OctopError) as envelope_err:
            await cloud.request_cloud(services, uid, "GET", CAPABILITIES)
        assert envelope_err.value.status == 502
    upstream.envelope = None
    upstream.expired.add("renewed-alice-cloud")
    upstream.refresh_status = 503
    with pytest.raises(OctopError) as temporary:
        await cloud.request_cloud(services, uid, "GET", CAPABILITIES)
    assert temporary.value.status == 502 and cloud.cloud_status(services, uid).connected
    upstream.refresh_status = 401
    with pytest.raises(OctopError) as expired:
        await cloud.request_cloud(services, uid, "GET", CAPABILITIES)
    assert (
        expired.value.code == ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED
        and not cloud.cloud_status(services, uid).connected
    )
    assert cloud.cloud_status(services, admin_id).account_id == "admin-cloud"
    upstream.refresh_status = 200
    upstream.expired.add("access-admin-cloud")
    upstream.refreshed_account = "unexpected"
    before = upstream.counts[TASKS]
    with pytest.raises(OctopError) as wrong_identity:
        await cloud.request_cloud(
            services, admin_id, "POST", TASKS, json={}, expected_account_id="admin-cloud"
        )
    assert wrong_identity.value.code == ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED
    assert before + 1 == upstream.counts[TASKS]


async def test_queued_write_never_runs_with_another_cloud_identity(
    env_admin_alice: Env, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, server, _, _ = env_admin_alice
    assert server.services is not None
    services = server.services
    uid = server.user_manager.get("alice").id
    await cloud.login_cloud(services, uid, "old", "test-password")
    entered, proceed = asyncio.Event(), asyncio.Event()
    original = cloud._lock
    import contextlib

    @contextlib.asynccontextmanager
    async def delayed() -> AsyncIterator[None]:
        entered.set()
        await proceed.wait()
        async with original(services, uid):
            yield

    monkeypatch.setattr(cloud, "_lock", lambda *_: delayed())
    write = asyncio.create_task(
        cloud.request_cloud(services, uid, "POST", TASKS, json={}, expected_account_id="old")
    )
    await asyncio.wait_for(entered.wait(), timeout=3)
    monkeypatch.setattr(cloud, "_lock", original)
    await cloud.login_cloud(services, uid, "new", "test-password")
    proceed.set()
    with pytest.raises(OctopError) as changed:
        await write
    assert changed.value.code == ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED
    assert not upstream.counts[TASKS] and cloud.cloud_status(services, uid).account_id == "new"


async def test_cancelled_login_finishes_saving_before_another_account_can_switch(
    env_admin_alice: Env, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, server, _, _ = env_admin_alice
    assert server.services is not None
    services = server.services
    uid = server.user_manager.get("alice").id
    pending, release = Event(), Event()
    save = cloud._save

    def pause(svc: SharedServices, local_owner: int, grant: cloud._Grant) -> None:
        pending.set()
        assert release.wait(5)
        save(svc, local_owner, grant)

    monkeypatch.setattr(cloud, "_save", pause)
    old = asyncio.create_task(cloud.login_cloud(services, uid, "old", "test-password"))
    try:
        assert await asyncio.to_thread(pending.wait, 3)
        old.cancel()
        await asyncio.sleep(0)
        with pytest.raises(Timeout):
            await cloud._lock(services, uid).acquire(timeout=0)
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await old
    await cloud.login_cloud(services, uid, "new", "test-password")
    assert cloud.cloud_status(services, uid).account_id == "new"


async def test_saved_login_without_avatar_reads_it_once(
    env_admin_alice: Env, upstream: Upstream
) -> None:
    client, server, _admin, alice = env_admin_alice
    assert server.services is not None
    services = server.services
    aid = server.user_manager.get("alice").id
    assert (
        await client.post(API, headers=alice, json={"account": "a", "password": "test-password"})
    ).status_code == 200
    # A login saved before avatars were kept has no avatar field at all.
    old = cloud._load(services, aid)
    assert old is not None
    cloud._save(services, aid, cloud._Grant(**{**cloud.asdict(old), "avatar_url": None}))

    first = (await client.get(API, headers=alice)).json()
    second = (await client.get(API, headers=alice)).json()
    assert first == second and first["avatar_url"] == "https://cdn.avatars.test/profile.jpg"
    assert upstream.counts["/api/user/profile"] == 1


async def test_avatar_lookup_failure_still_returns_the_account(
    env_admin_alice: Env, upstream: Upstream
) -> None:
    client, server, _admin, alice = env_admin_alice
    assert server.services is not None
    services = server.services
    aid = server.user_manager.get("alice").id
    await client.post(API, headers=alice, json={"account": "a", "password": "test-password"})
    old = cloud._load(services, aid)
    assert old is not None
    cloud._save(services, aid, cloud._Grant(**{**cloud.asdict(old), "avatar_url": None}))
    upstream.expired.add("access-a")

    body = (await client.get(API, headers=alice)).json()
    assert body["connected"] and body["account_id"] == "a" and body["avatar_url"] is None
    assert cloud._load(services, aid) == cloud._Grant(**{**cloud.asdict(old), "avatar_url": None})
