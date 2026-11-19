"""Lynxce only exposes the billing identity's accessible chat models to Octop."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from octop.config import OctopConfig
from octop.infra.agents.providers import lynxce
from octop.infra.agents.providers.lynxce import lynxce_chat_models
from octop.infra.auth import lynxce as oauth
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import build_shared_services
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.paths import PathLayout


def test_account_catalog_keeps_text_and_excludes_other_api_endpoints() -> None:
    data = [
        {"id": "shared-name", "modality": "image"},
        {"id": "shared-name", "object": "model", "owned_by": "team"},
        {"id": "new-chat", "modality": "text", "name": "New chat"},
        {"id": "shared-name"},
        *(
            {"id": f"aux-{kind}", "modality": kind}
            for kind in ("speech", "embedding", "audio", "video")
        ),
        {"id": "", "modality": "text"},
    ]
    assert lynxce_chat_models({"object": "list", "data": data}) == [
        {"id": "shared-name", "name": "shared-name"},
        {"id": "new-chat", "name": "New chat"},
    ]
    assert lynxce_chat_models({"data": [{"id": "second-account-only"}]}) == [
        {"id": "second-account-only", "name": "second-account-only"},
    ]
    assert lynxce_chat_models({"data": []}) == []
    with pytest.raises(ValueError):
        lynxce_chat_models({"error": {"code": "unauthorized"}})


@pytest.fixture
def accounts(tmp_path, monkeypatch):
    monkeypatch.setenv("OCTOP_DESKTOP_SHELL", "1")
    monkeypatch.setenv("OCTOP_DESKTOP_PRODUCT", "bot")
    pool = SqlitePool(tmp_path / "octop.db")
    run_migrations(pool)
    services = build_shared_services(db=pool, paths=PathLayout(tmp_path), config=OctopConfig())
    grants = {1: "first-login", 2: "other-account"}
    monkeypatch.setattr(oauth, "connection_id", lambda _, uid: grants.get(uid))
    monkeypatch.setattr(lynxce, "_models", AsyncMock(return_value=[{"id": "chat", "name": "Chat"}]))
    yield services, grants
    pool.close()


async def test_private_clients_follow_token_refresh_and_refuse_a_different_account(
    accounts, monkeypatch
):
    services, grants = accounts
    await lynxce.select_account_model(services, 1, "chat")
    selected = lynxce.account_selection(services, 1)
    assert lynxce.account_selection(services, 2) is None
    await lynxce.select_account_model(services, 2, "chat")
    other = lynxce.account_selection(services, 2)
    tokens = {1: "first-access", 2: "other-access"}

    async def get_token(_, uid, *, expected_connection_id):
        assert grants[uid] == expected_connection_id
        return tokens[uid]

    monkeypatch.setattr(oauth, "get_access_token", get_token)
    alice, bob = selected.provider(services).api_key, other.provider(services).api_key
    assert await asyncio.gather(alice(), bob()) == ["first-access", "other-access"]
    tokens[1] = "refreshed"
    assert await alice() == "refreshed"
    grants[1] = "new-personal-login"
    assert lynxce.selected_account_model(services, 1) is None
    with pytest.raises(OctopError, match="Lynxce") as exc:
        await alice()
    assert exc.value.code == ErrorCode.CONNECTOR_AUTH_REQUIRED
    with pytest.raises(OctopError):
        await selected.provider(None).api_key()
    assert await bob() == "other-access"
    assert services.provider_repo.list_all() == []


@pytest.mark.parametrize("action", ["logout", "switch-account", "switch-provider"])
async def test_inflight_model_discovery_cannot_restore_a_cleared_or_replaced_selection(
    accounts, monkeypatch, action
):
    services, grants = accounts
    started, released = asyncio.Event(), asyncio.Event()

    async def catalog(*_):
        started.set()
        await released.wait()
        return [{"id": "chat", "name": "Chat"}]

    monkeypatch.setattr(lynxce, "_models", catalog)
    select = asyncio.create_task(lynxce.select_account_model(services, 1, "chat"))
    await started.wait()
    if action == "logout":
        del grants[1]
    elif action == "switch-account":
        grants[1] = "replacement"
    else:
        lynxce.clear_account_model(services, 1)
    released.set()
    with pytest.raises(OctopError):
        await select
    assert lynxce.selected_account_model(services, 1) is None


async def test_full_dashboard_and_cli_ignore_an_existing_bot_billing_choice(accounts, monkeypatch):
    services, _ = accounts
    await lynxce.select_account_model(services, 1, "chat")
    assert lynxce.selected_account_model(services, 1) == "chat"
    monkeypatch.setenv("OCTOP_DESKTOP_PRODUCT", "octop")
    assert lynxce.account_selection(services, 1) is None
    monkeypatch.setenv("OCTOP_DESKTOP_PRODUCT", "bot")
    monkeypatch.delenv("OCTOP_DESKTOP_SHELL")
    assert lynxce.account_selection(services, 1) is None
