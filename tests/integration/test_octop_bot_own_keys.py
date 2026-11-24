"""Octop Bot users add their own model vendor keys (Tencent Cloud, Bailian, ...) and chat on them."""

from pathlib import Path

import httpx
import pytest

from octop.infra.agents.providers import own_keys
from octop.infra.agents.providers.lynxce import (
    CloudAccountModel,
    account_selection,
    pays_with_account_credits,
)
from octop.infra.agents.providers.own_keys import OwnKeyModel
from tests.integration.test_octop_bot_cloud import _sign_in
from tests.integration.test_octop_bot_cloud import upstream as cloud_upstream  # noqa: F401
from tests.support.app import octop_client

KEYS = "/api/octop-bot/model-keys"
GOOD = "sk-tencent-good-1234"


class Vendor:
    """Tencent TokenHub stand-in: lists models for the good key, refuses any other."""

    def __init__(self) -> None:
        self.calls: list[httpx.URL] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req.url)
        if req.headers.get("Authorization") != f"Bearer {GOOD}":
            return httpx.Response(401, json={"error": {"message": "invalid api key"}})
        return httpx.Response(
            200, json={"object": "list", "data": [{"id": "hy4"}, {"id": "deepseek-v4"}]}
        )


@pytest.fixture
def vendor(monkeypatch: pytest.MonkeyPatch) -> Vendor:
    fake = Vendor()
    monkeypatch.setattr(
        own_keys, "_vendor_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake))
    )
    return fake


@pytest.mark.usefixtures("cloud_upstream")
async def test_a_tenant_chats_on_their_own_tencent_key_without_lynxce_credits(
    tmp_octop_home: Path, vendor: Vendor
) -> None:
    async with octop_client(tmp_octop_home) as (client, srv):
        alice = await _sign_in(client, "13800000011")
        bob = await _sign_in(client, "13800000012")
        a = {"Authorization": f"Bearer {alice['access_token']}"}
        b = {"Authorization": f"Bearer {bob['access_token']}"}
        uid = alice["user"]["id"]

        catalog = (await client.get(f"{KEYS}/vendors", headers=a)).json()
        ids = {v["id"] for v in catalog["vendors"]}
        assert {"tencent-tokenhub", "volcengine-cn", "dashscope", "deepseek"} <= ids
        assert not ids & {"lynxce", "ollama", "onnx", "magpie", "openai-codex"}
        assert all(v["base_url"].startswith("https://") for v in catalog["vendors"])
        assert catalog["custom_allowed"] is False

        refused = await client.post(
            KEYS, headers=a, json={"vendor": "tencent-tokenhub", "api_key": "sk-wrong"}
        )
        assert refused.status_code == 400
        assert refused.json()["error"]["code"] == "BOT_MODEL_KEY_INVALID"

        added = await client.post(
            KEYS, headers=a, json={"vendor": "tencent-tokenhub", "api_key": GOOD}
        )
        assert added.status_code == 201, added.text
        key = added.json()
        assert key["key_hint"] == "****1234" and GOOD not in added.text
        assert [m["id"] for m in key["models"]] == ["hy4", "deepseek-v4"]
        assert vendor.calls[-1].host == "tokenhub.tencentmaas.com"

        # Stored encrypted, and only for Alice.
        services = srv.services
        assert GOOD.encode() not in services.secret_repo.get(f"octop_bot:own_model_keys:{uid}")
        assert (await client.get(KEYS, headers=b)).json()["keys"] == []
        assert (await client.delete(f"{KEYS}/{key['id']}", headers=b)).status_code == 404

        used = await client.put(f"{KEYS}/{key['id']}/model", headers=a, json={"model_id": "hy4"})
        assert used.status_code == 200, used.text
        assert used.json()["in_use"] == key["id"] and used.json()["selected_model"] == "hy4"
        assert GOOD not in used.text

        selected = account_selection(services, uid)
        assert isinstance(selected, OwnKeyModel)
        provider = selected.provider(services)
        assert provider.base_url == "https://tokenhub.tencentmaas.com/v1"
        assert await provider.api_key() == GOOD  # type: ignore[operator]
        assert selected.ref == "own/hy4"
        assert not pays_with_account_credits(services.settings_repo, services.user_repo, uid)
        # Bob still chats through Lynxce and pays in credits.
        assert isinstance(account_selection(services, bob["user"]["id"]), CloudAccountModel)

        unknown = await client.put(
            f"{KEYS}/{key['id']}/model", headers=a, json={"model_id": "not-listed"}
        )
        assert unknown.status_code == 404

        # Removing the key in use puts Alice back on her Lynxce model.
        assert (await client.delete(f"{KEYS}/{key['id']}", headers=a)).status_code == 204
        assert isinstance(account_selection(services, uid), CloudAccountModel)
        assert pays_with_account_credits(services.settings_repo, services.user_repo, uid)
        listing = (await client.get(KEYS, headers=a)).json()
        assert listing["keys"] == [] and listing["in_use"] is None


@pytest.mark.usefixtures("cloud_upstream")
async def test_cloud_tenants_cannot_point_a_key_at_their_own_url(
    tmp_octop_home: Path, vendor: Vendor
) -> None:
    async with octop_client(tmp_octop_home) as (client, _srv):
        auth = {
            "Authorization": f"Bearer {(await _sign_in(client, '13800000013'))['access_token']}"
        }
        for body in (
            {"vendor": "custom", "api_key": GOOD, "base_url": "http://127.0.0.1:18080/v1"},
            {"vendor": "custom", "api_key": GOOD, "base_url": "http://100.100.100.200/latest"},
            {"vendor": "ollama", "api_key": GOOD},
            {"vendor": "lynxce", "api_key": GOOD},
        ):
            resp = await client.post(KEYS, headers=auth, json=body)
            assert resp.status_code == 400, body
            assert resp.json()["error"]["code"] == "BOT_MODEL_VENDOR_UNSUPPORTED"
        assert vendor.calls == []


def test_the_desktop_app_also_takes_a_custom_openai_compatible_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OCTOP_BOT_CLOUD", raising=False)
    assert own_keys.custom_urls_allowed()


@pytest.mark.usefixtures("cloud_upstream")
async def test_a_tenant_goes_back_to_lynxce_credits_and_keeps_the_key(
    tmp_octop_home: Path, vendor: Vendor
) -> None:
    async with octop_client(tmp_octop_home) as (client, srv):
        alice = await _sign_in(client, "13800000014")
        a = {"Authorization": f"Bearer {alice['access_token']}"}
        uid = alice["user"]["id"]
        key = (
            await client.post(KEYS, headers=a, json={"vendor": "tencent-tokenhub", "api_key": GOOD})
        ).json()
        await client.put(f"{KEYS}/{key['id']}/model", headers=a, json={"model_id": "hy4"})
        assert isinstance(account_selection(srv.services, uid), OwnKeyModel)

        left = await client.delete(f"{KEYS}/in-use", headers=a)
        assert left.status_code == 200, left.text
        body = left.json()
        assert body["in_use"] is None
        assert [k["id"] for k in body["keys"]] == [key["id"]]
        assert isinstance(account_selection(srv.services, uid), CloudAccountModel)
        assert pays_with_account_credits(srv.services.settings_repo, srv.services.user_repo, uid)
        # Nothing in use: still fine.
        assert (await client.delete(f"{KEYS}/in-use", headers=a)).status_code == 200


async def test_a_self_hosted_server_keeps_its_users_own_keys(
    tmp_octop_home: Path, vendor: Vendor, monkeypatch: pytest.MonkeyPatch
) -> None:
    from octop.infra.agents.providers.lynxce import _key
    from tests.support.auth import auth_header, bootstrap_admin, resolve_user_id

    monkeypatch.delenv("OCTOP_BOT_CLOUD", raising=False)
    monkeypatch.delenv("OCTOP_BOT_WEB", raising=False)
    async with octop_client(tmp_octop_home) as (client, srv):
        await bootstrap_admin(client, tmp_octop_home)
        a = await auth_header(client)
        uid = await resolve_user_id(client, a, "admin")
        # The NAS / Docker build (its owner signs in with Lynxce; a local admin here).
        monkeypatch.setenv("OCTOP_BOT_WEB", "1")

        catalog = (await client.get(f"{KEYS}/vendors", headers=a)).json()
        assert catalog["custom_allowed"] is True  # the server's admin
        key = (
            await client.post(KEYS, headers=a, json={"vendor": "tencent-tokenhub", "api_key": GOOD})
        ).json()
        assert account_selection(srv.services, uid) is None  # the server's models until picked
        await client.put(f"{KEYS}/{key['id']}/model", headers=a, json={"model_id": "hy4"})
        selected = account_selection(srv.services, uid)
        assert isinstance(selected, OwnKeyModel) and selected.ref == "own/hy4"

        assert (await client.delete(f"{KEYS}/in-use", headers=a)).json()["in_use"] is None
        assert account_selection(srv.services, uid) is None
        assert srv.services.settings_repo.get(_key(uid))


def test_only_a_self_hosted_servers_admins_add_custom_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OCTOP_BOT_CLOUD", raising=False)
    monkeypatch.setenv("OCTOP_BOT_WEB", "1")
    assert own_keys.custom_urls_allowed(admin=True)
    assert not own_keys.custom_urls_allowed(admin=False)
    monkeypatch.setenv("OCTOP_BOT_CLOUD", "1")
    assert not own_keys.custom_urls_allowed(admin=True)
