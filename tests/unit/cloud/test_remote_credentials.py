import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from octop.config import OctopConfig
from octop.infra.auth import lynxce_cloud
from octop.infra.cloud.computers.remote import RemoteCredentials, clear_token
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


def credential(services: SharedServices, handler: object, now: list[float]) -> RemoteCredentials:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return RemoteCredentials(
        services,
        1,
        client=lambda: httpx.AsyncClient(base_url="https://example.test", transport=transport),
        clock=lambda: now[0],
    )


async def test_exchange_cache_expiry_and_binding(
    services: SharedServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    grant = lynxce_cloud._Grant("test-account", None, "binding-a", "test-access", "test-refresh")
    monkeypatch.setattr(lynxce_cloud, "_load", lambda *_: grant)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200, json={"access_token": f"test-jwt-{len(calls)}", "expires_in": 60}
        )

    now = [100.0]
    remote = credential(services, handler, now)
    assert await remote.token() == "test-jwt-1"
    assert await remote.token() == "test-jwt-1"
    assert calls[0].url.path == "/api/auth/lynxce/token-login"
    assert b"test-access" in calls[0].content
    assert b"test-jwt-1" not in services.secret_repo.get("octop_bot.remote_computer.user.1")
    now[0] += 60
    assert await remote.token() == "test-jwt-2"
    grant = lynxce_cloud._Grant(
        "test-account-2", None, "binding-b", "test-access-2", "test-refresh"
    )
    assert await remote.token() == "test-jwt-3"
    clear_token(services, 1)
    assert services.secret_repo.get("octop_bot.remote_computer.user.1") is None


async def test_exchange_reverify(services: SharedServices, monkeypatch: pytest.MonkeyPatch) -> None:
    grant = lynxce_cloud._Grant("test-account", None, "binding-a", "test-access", "test-refresh")
    monkeypatch.setattr(lynxce_cloud, "_load", lambda *_: grant)
    remote = credential(
        services,
        lambda _: httpx.Response(409, json={"error": {"code": "BOT_CLOUD_SESSION_REQUIRED"}}),
        [100.0],
    )
    monkeypatch.setattr(
        lynxce_cloud, "_send", AsyncMock(side_effect=lynxce_cloud._UpstreamFailure(404))
    )
    with pytest.raises(OctopError) as exc:
        await remote.token()
    assert exc.value.code == ErrorCode.BOT_CLOUD_REVERIFY_REQUIRED


async def test_one_time_server_grant(services, monkeypatch):
    grant = lynxce_cloud._Grant("test-account", None, "b", "test-access", "test-refresh")
    monkeypatch.setattr(lynxce_cloud, "_load", lambda *_: grant)
    issuer = AsyncMock(return_value={"code": "one-use"})
    monkeypatch.setattr(lynxce_cloud, "_send", issuer)
    bodies = []

    def cloud(request):
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            return httpx.Response(409, json={"error": {"code": "BOT_CLOUD_SESSION_REQUIRED"}})
        return httpx.Response(200, json={"access_token": "scoped", "expires_in": 3600})

    assert await credential(services, cloud, [100.0]).token() == "scoped"
    assert bodies == [
        {"access_token": "test-access"},
        {"access_token": "test-access", "server_code": "one-use"},
    ]
    issuer.assert_awaited_once_with(
        "POST",
        "/api/auth/login-codes",
        bearer="test-access",
        json={"scope": "server", "site": "octop-bot"},
    )


def test_cloud_credentials_only_use_the_official_or_development_loopback_origin(monkeypatch):
    from unittest.mock import Mock

    from octop.infra.cloud.computers.remote import cloud_client
    from octop.infra.desktop import bot_cloud_origin
    from octop.infra.errors import OctopError

    monkeypatch.delenv("OCTOP_BOT_CLOUD_ORIGIN", raising=False)
    assert bot_cloud_origin() == "https://bot.lynxce.cn"
    monkeypatch.setenv("OCTOP_BOT_CLOUD_ORIGIN", "http://127.0.0.1:18400")
    monkeypatch.delenv("OCTOP_DASHBOARD_DEV", raising=False)
    transport = Mock()
    monkeypatch.setattr(httpx, "AsyncClient", transport)
    with pytest.raises(OctopError):
        cloud_client()
    monkeypatch.setenv("OCTOP_DASHBOARD_DEV", "1")
    assert bot_cloud_origin() == "http://127.0.0.1:18400"
    monkeypatch.setenv("OCTOP_BOT_CLOUD_ORIGIN", "https://workspace.example.test")
    with pytest.raises(OctopError):
        cloud_client()
    transport.assert_not_called()
