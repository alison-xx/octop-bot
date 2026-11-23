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


def test_lynxce_api_key_preset_is_listed_first_and_openai_compatible():
    from octop.infra.agents.providers.presets import load_provider_presets

    presets = load_provider_presets()
    lynxce = presets[0]
    assert lynxce["id"] == "lynxce"
    assert [p["id"] for p in presets].count("lynxce") == 1
    assert lynxce["base_url"] == "https://api.lynxce.cn/api/v1"
    assert lynxce["protocol"] == "openai"
    assert lynxce["api_key_prefix"] == "sk-"
    assert lynxce["logo_id"] == "lynxce"
    ids = [m["id"] for m in lynxce["models"]]
    assert "deepseek-flash" in ids and len(ids) == len(set(ids))
    # Callers mutate presets (reasoning flags); the module constant stays untouched.
    lynxce["models"].clear()
    assert load_provider_presets()[0]["models"]


async def test_desktop_sign_in_chats_through_the_account_key_without_a_browser_grant(
    accounts, monkeypatch
):
    """One Lynxce sign-in on the desktop brings the account's models; sign-out takes them away."""
    from octop.infra.cloud.bot_cloud import accounts as cloud_accounts

    services, grants = accounts
    grants.clear()  # no browser (OAuth) grant at all
    minted: list[str] = []

    async def mint(_services, user_id, _body):
        minted.append(f"sk-key-{len(minted)}")
        return {"id": f"key-{user_id}-{len(minted)}", "secret": minted[-1]}

    monkeypatch.setattr(cloud_accounts.lynxce_cloud, "create_model_key", mint)
    monkeypatch.setattr(
        lynxce, "_cloud_models", AsyncMock(return_value=[{"id": "deepseek-flash", "name": "D"}])
    )

    assert await lynxce.adopt_cloud_account(services, 1, "acct-a") is True
    selected = lynxce.account_selection(services, 1)
    assert isinstance(selected, lynxce.CloudAccountModel)
    assert selected.model_id == cloud_accounts.cloud_model_id()
    assert lynxce.has_cloud_key(services, 1)
    assert lynxce.pays_with_account_credits(services.settings_repo, services.user_repo, 1)

    # Signing in again with the same account keeps the key and the chosen model.
    assert await lynxce.select_account_model(services, 1, "deepseek-flash") == "deepseek-flash"
    assert await lynxce.adopt_cloud_account(services, 1, "acct-a") is False
    assert minted == ["sk-key-0"]

    # A different Lynxce account never reuses the previous account's key.
    await lynxce.adopt_cloud_account(services, 1, "acct-b")
    assert minted == ["sk-key-0", "sk-key-1"]
    assert cloud_accounts.load_model_key(services, 1).secret == "sk-key-1"

    lynxce.release_cloud_account(services, 1)
    assert not lynxce.has_cloud_key(services, 1)
    assert lynxce.account_selection(services, 1) is None
    assert not lynxce.pays_with_account_credits(services.settings_repo, services.user_repo, 1)


async def test_desktop_sign_in_keeps_a_model_the_user_already_chose(accounts, monkeypatch):
    from octop.infra.cloud.bot_cloud import accounts as cloud_accounts

    services, _grants = accounts
    monkeypatch.setattr(
        cloud_accounts.lynxce_cloud,
        "create_model_key",
        AsyncMock(return_value={"id": "k", "secret": "sk-x"}),
    )
    assert await lynxce.select_account_model(services, 1, "chat") == "chat"
    assert await lynxce.adopt_cloud_account(services, 1, "acct-a") is False
    assert lynxce.account_selection(services, 1).model_id == "chat"
