"""Real loopback browser redirects against an isolated fake Lynxce authorization server."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from aiohttp import web
from filelock import AsyncFileLock

from octop.config import OctopConfig
from octop.infra.auth import lynxce
from octop.infra.auth.lynxce import _grants, _provider
from octop.infra.connectors.oauth.pkce import s256_challenge
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import SharedServices, build_shared_services
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.paths import PathLayout


@pytest.fixture
def services(tmp_path: Path) -> Iterator[SharedServices]:
    paths = PathLayout(tmp_path)
    db = SqlitePool(paths.db)
    run_migrations(db)
    yield build_shared_services(db=db, paths=paths, config=OctopConfig())
    db.close()


@pytest.fixture
async def issuer(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[SimpleNamespace]:
    state = SimpleNamespace(
        registrations=[],
        exchanges=[],
        refreshes=[],
        scope="media chat social",
        ttl=3600,
        refresh_error="",
        hold=None,
        entered=asyncio.Event(),
    )

    async def register(request: web.Request) -> web.Response:
        state.registrations.append(await request.json())
        return web.json_response({"client_id": f"client-{len(state.registrations)}"}, status=201)

    async def token(request: web.Request) -> web.Response:
        form = dict(await request.post())
        refresh = form["grant_type"] == "refresh_token"
        calls = state.refreshes if refresh else state.exchanges
        calls.append(form)
        state.entered.set()
        if state.hold is not None:
            await state.hold.wait()
        if refresh and state.refresh_error:
            return web.json_response(
                {"error": state.refresh_error, "error_description": "upstream-private-detail"},
                status=400,
            )
        stage = ("rotated" if refresh else "initial") + str(len(calls))
        return web.json_response(
            {
                "access_token": f"test-access-{stage}",
                "refresh_token": f"test-refresh-{stage}",
                "scope": state.scope,
                "token_type": "Bearer",
                "expires_in": state.ttl,
            }
        )

    app = web.Application()
    app.router.add_post("/register", register)
    app.router.add_post("/token", token)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    monkeypatch.setattr(_provider, "ENDPOINT", f"http://127.0.0.1:{runner.addresses[0][1]}")
    try:
        yield state
    finally:
        if state.hold is not None:
            state.hold.set()
        for attempt in tuple(lynxce._attempts.values()):
            attempt.finish("cancelled")
        await asyncio.gather(*tuple(lynxce._closing))
        lynxce._attempts.clear()
        await runner.cleanup()


def query(url: str) -> dict[str, str]:
    return {key: value[0] for key, value in parse_qs(urlsplit(url).query).items()}


async def callback(auth_url: str, *, lang: str = "en", **params: str) -> httpx.Response:
    args = query(auth_url)
    async with httpx.AsyncClient(trust_env=False) as browser:
        return await browser.get(
            args["redirect_uri"],
            params={"code": "synthetic-code", "state": args["state"], **params},
            headers={"Accept-Language": lang},
        )


async def connect(svc: SharedServices, user: int = 1) -> tuple[str, str]:
    attempt, url = await lynxce.start_login(svc, user)
    assert (await callback(url)).status_code == 200
    assert await lynxce.poll_login(svc, user, attempt) == ("connected", None)
    return attempt, url


async def test_native_pkce_state_owner_locale_and_encrypted_grant(
    services: SharedServices, issuer: SimpleNamespace
) -> None:
    attempt, url = await lynxce.start_login(services, 1)
    args = query(url)
    assert await lynxce.start_login(services, 1) == (attempt, url)
    assert args["scope"] == "chat" and args["code_challenge_method"] == "S256"
    assert args["response_type"] == "code" and args["state"] != attempt
    assert issuer.registrations == [
        {
            "client_name": "Octop Bot",
            "redirect_uris": [args["redirect_uri"]],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": "chat",
        }
    ]
    assert urlsplit(args["redirect_uri"]).hostname == "127.0.0.1"
    wrong = await callback(url, state="wrong", code="<script>from-query</script>")
    assert wrong.status_code == 400 and "from-query" not in wrong.text
    assert not issuer.exchanges and await lynxce.poll_login(services, 1, attempt) == (
        "pending",
        None,
    )
    for action in (lynxce.poll_login, lynxce.cancel_login):
        with pytest.raises(OctopError) as error:
            await action(services, 2, attempt)
        assert error.value.status == 404
    result = await callback(url, lang="zh")
    assert result.status_code == 200 and "已连接灵策智算" in result.text
    assert "返回 Octop Bot，选择聊天模型后开始对话" in result.text
    assert result.headers["cache-control"] == "no-store" and "synthetic-code" not in result.text
    (exchange,) = issuer.exchanges
    assert s256_challenge(exchange["code_verifier"]) == args["code_challenge"]
    assert exchange["redirect_uri"] == args["redirect_uri"]
    assert await lynxce.get_access_token(services, 1) == "test-access-initial1"
    assert lynxce.is_connected(services, 1) and not lynxce.is_connected(services, 2)
    sealed = services.secret_repo.get(_grants.grant_key(1))
    assert sealed and b"test-access-" not in sealed and b"test-refresh-" not in sealed
    with pytest.raises(OctopError) as error:
        await lynxce.get_access_token(services, 2)
    assert error.value.status == 403 and error.value.code == ErrorCode.CONNECTOR_AUTH_REQUIRED


async def test_reauth_changes_connection_reuses_dcr_and_isolates_users(
    services: SharedServices, issuer: SimpleNamespace
) -> None:
    _, first_url = await connect(services)
    first_id = lynxce.connection_id(services, 1)
    assert first_id
    await asyncio.gather(*tuple(lynxce._closing))
    _, second_url = await connect(services)
    assert query(first_url)["redirect_uri"] == query(second_url)["redirect_uri"]
    assert len(issuer.registrations) == 1 and first_id != lynxce.connection_id(services, 1)
    with pytest.raises(OctopError):
        await lynxce.get_access_token(services, 1, expected_connection_id=first_id)
    await connect(services, 2)
    assert len(issuer.registrations) == 2
    await lynxce.disconnect(services, 1)
    assert lynxce.connection_id(services, 1) is None and not lynxce.is_connected(services, 1)
    assert await lynxce.get_access_token(services, 2) == "test-access-initial3"


async def test_cancel_denial_missing_scope_timeout_and_busy_cached_port(
    services: SharedServices, issuer: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempt, url = await lynxce.start_login(services, 1)
    rejected = await callback(url, error="access_denied", error_description="private-denial")
    assert (
        rejected.status_code == 400
        and "Authorization cancelled" in rejected.text
        and "private-denial" not in rejected.text
    )
    assert await lynxce.poll_login(services, 1, attempt) == ("failed", "access_denied")
    await asyncio.gather(*tuple(lynxce._closing))
    port = urlsplit(query(url)["redirect_uri"]).port
    assert port is not None
    async with await asyncio.start_server(lambda _r, w: w.close(), "127.0.0.1", port):
        next_id, next_url = await lynxce.start_login(services, 1)
        assert query(next_url)["redirect_uri"] != query(url)["redirect_uri"]
        issuer.scope = "media"
        assert (await callback(next_url)).status_code == 502
        assert await lynxce.poll_login(services, 1, next_id) == ("failed", "missing_chat_scope")
    cancel_id, _ = await lynxce.start_login(services, 1)
    await lynxce.cancel_login(services, 1, cancel_id)
    assert await lynxce.poll_login(services, 1, cancel_id) == ("cancelled", None)
    monkeypatch.setattr(lynxce, "_ATTEMPT_SECONDS", 0.01)
    expired_id, _ = await lynxce.start_login(services, 1)
    await asyncio.sleep(0.05)
    assert await lynxce.poll_login(services, 1, expired_id) == ("expired", None)
    assert not lynxce.is_connected(services, 1)


async def test_simultaneous_refresh_survives_cancelled_caller_and_preserves_connection(
    services: SharedServices, issuer: SimpleNamespace
) -> None:
    issuer.ttl = 5
    await connect(services)
    connection = lynxce.connection_id(services, 1)
    issuer.ttl = 3600
    issuer.hold = asyncio.Event()
    issuer.entered.clear()
    first = asyncio.create_task(lynxce.get_access_token(services, 1))
    await asyncio.wait_for(issuer.entered.wait(), 3)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    reads = [
        asyncio.create_task(lynxce.get_access_token(services, 1, expected_connection_id=connection))
        for _ in range(8)
    ]
    issuer.hold.set()
    assert set(await asyncio.gather(*reads)) == {"test-access-rotated1"}
    assert (
        len(issuer.refreshes) == 1
        and issuer.refreshes[0]["refresh_token"] == "test-refresh-initial1"
    )
    assert lynxce.connection_id(services, 1) == connection


async def test_refresh_failure_keeps_transient_grant_and_removes_invalid_grant(
    services: SharedServices, issuer: SimpleNamespace
) -> None:
    issuer.ttl = 1
    await connect(services)
    issuer.refresh_error = "temporarily_unavailable"
    with pytest.raises(OctopError) as transient:
        await lynxce.get_access_token(services, 1)
    assert transient.value.status == 502 and "upstream-private-detail" not in str(transient.value)
    assert lynxce.is_connected(services, 1)
    issuer.refresh_error = "invalid_grant"
    with pytest.raises(OctopError) as invalid:
        await lynxce.get_access_token(services, 1)
    assert invalid.value.status == 403 and not lynxce.is_connected(services, 1)


async def test_separate_runtime_reopens_encrypted_grant_and_serializes_rotation(
    services: SharedServices, issuer: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    issuer.ttl = 1
    await connect(services)
    second_db = SqlitePool(services.paths.db)
    peer = build_shared_services(db=second_db, paths=services.paths, config=services.config)
    try:
        assert lynxce.connection_id(peer, 1) == lynxce.connection_id(services, 1)
        issuer.ttl = 3600
        issuer.hold = asyncio.Event()
        issuer.entered.clear()
        first = asyncio.create_task(lynxce.get_access_token(services, 1))
        await asyncio.wait_for(issuer.entered.wait(), 3)
        # A different loop cannot join the in-memory single-flight task. It
        # must reload the newly rotated grant after acquiring the OS file lock.
        loop = asyncio.get_running_loop()
        peer_entered = asyncio.Event()
        original_lock = _grants.account_lock

        def observed_lock(runtime: SharedServices, user_id: int) -> AsyncFileLock:
            if runtime is peer:
                loop.call_soon_threadsafe(peer_entered.set)
            return original_lock(runtime, user_id)

        monkeypatch.setattr(_grants, "account_lock", observed_lock)

        def peer_turn() -> str:
            return asyncio.run(lynxce.get_access_token(peer, 1))

        second = loop.run_in_executor(None, peer_turn)
        await asyncio.wait_for(peer_entered.wait(), 3)
        issuer.hold.set()
        assert await asyncio.gather(first, second) == ["test-access-rotated1"] * 2
        assert len(issuer.refreshes) == 1
    finally:
        second_db.close()


async def test_disconnect_during_code_exchange_cannot_restore_old_grant(
    services: SharedServices, issuer: SimpleNamespace
) -> None:
    attempt, url = await lynxce.start_login(services, 1)
    issuer.hold = asyncio.Event()
    response = asyncio.create_task(callback(url))
    await asyncio.wait_for(issuer.entered.wait(), 3)
    await lynxce.disconnect(services, 1)
    issuer.hold.set()
    assert (await response).status_code == 400
    assert await lynxce.poll_login(services, 1, attempt) == ("cancelled", None)
    assert not lynxce.is_connected(services, 1)
