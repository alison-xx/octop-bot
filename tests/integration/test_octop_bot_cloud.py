"""Octop Bot cloud (OCTOP_BOT_CLOUD): every Lynxce account gets its own account and model key."""

import asyncio
import json
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import jwt
import pytest

from octop.api.routers import auth_lynxce
from octop.infra.agents.providers.lynxce import GATEWAY_URL, CloudAccountModel, account_selection
from octop.infra.auth import lynxce_cloud as cloud
from octop.infra.cloud.bot_cloud import accounts
from octop.infra.cloud.bot_cloud import files as cloud_files
from tests.support.app import octop_client

CODE_LOGIN = "/api/auth/lynxce/code-login"
STATUS = "/api/auth/lynxce/status"
INFO = "/api/octop-bot/server-info"


def _lynxce_jwt(**claims: Any) -> str:
    return jwt.encode({"typ": "access", **claims}, "test-secret", algorithm="HS256")


class Upstream:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.keys: list[dict[str, Any]] = []
        self.revoked: set[str] = set()
        self.forbidden: set[str] = set()
        self.mint_fails = False
        self.patched: list[tuple[str, dict[str, Any]]] = []
        # Unrevoked personal API keys by id, as the Lynxce account centre lists them.
        self.live: dict[str, dict[str, Any]] = {}
        self.deleted: list[str] = []
        self.list_fails = False

    def __call__(self, req: httpx.Request) -> httpx.Response:
        assert req.url.host == "api.lynxce.cn" and req.url.scheme == "https"
        path = req.url.path
        self.counts[path] += 1
        if path == "/api/v1/models":  # the open gateway, called with a personal API key
            secret = req.headers["Authorization"].removeprefix("Bearer ")
            if secret in self.revoked:
                return httpx.Response(401, json={"error": {"message": "invalid key"}})
            if secret in self.forbidden:
                return httpx.Response(403, json={"error": {"message": "insufficient balance"}})
            return httpx.Response(200, json={"object": "list", "data": []})
        assert req.headers["X-Lynxce-Client"] == "web"
        if path == "/api/auth/phone-login":
            payload = json.loads(req.content)
            if payload["code"] != "123456":
                return httpx.Response(401, json={"message": "bad code"})
            uid = payload["phone"]
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "accessToken": f"access-{uid}",
                        "refreshToken": f"refresh-{uid}",
                        "user": {"id": "lx-" + uid, "displayName": "User " + uid},
                    },
                },
            )
        if path == "/api/user/personal-api-keys" and req.method == "GET":
            owner = req.headers["Authorization"].removeprefix("Bearer ")
            if self.list_fails:
                return httpx.Response(503, json={"message": "busy"})
            items = [
                {k: v for k, v in key.items() if k != "owner"}
                for key in self.live.values()
                if key["owner"] == owner
            ]
            return httpx.Response(200, json={"code": 0, "data": {"items": items}})
        if req.method == "DELETE" and path.startswith("/api/user/personal-api-keys/"):
            key_id = path.rsplit("/", 1)[1]
            owner = req.headers["Authorization"].removeprefix("Bearer ")
            if self.live.get(key_id, {}).get("owner") != owner:
                return httpx.Response(404, json={"error": {"code": "personal_api_key_not_found"}})
            del self.live[key_id]
            self.deleted.append(key_id)
            return httpx.Response(200, json={"code": 0, "data": {}})
        if path == "/api/user/personal-api-keys":
            assert req.headers["Authorization"].startswith("Bearer access-")
            if self.mint_fails:
                return httpx.Response(503, json={"message": "busy"})
            body = json.loads(req.content)
            self.keys.append(body)
            n = len(self.keys)
            self.live[f"key-{n}"] = {
                "id": f"key-{n}",
                "name": body["name"],
                "lastUsedAt": None,
                "owner": req.headers["Authorization"].removeprefix("Bearer "),
            }
            return httpx.Response(
                200, json={"code": 0, "data": {"id": f"key-{n}", "secret": f"sk-test-{n}"}}
            )
        if req.method == "PATCH" and path.startswith("/api/user/personal-api-keys/"):
            assert req.headers["Authorization"].startswith("Bearer access-")
            self.patched.append((path.rsplit("/", 1)[1], json.loads(req.content)))
            return httpx.Response(200, json={"code": 0, "data": {}})
        if path == "/api/user/profile":  # who an access token belongs to (token-login)
            bearer = req.headers.get("Authorization", "").removeprefix("Bearer ")
            if bearer.count(".") == 2:
                return httpx.Response(200, json={"code": 0, "data": {"id": "lx-13800000050"}})
            if not bearer.startswith("access-"):
                return httpx.Response(401, json={"error": {"message": "invalid token"}})
            uid = bearer.removeprefix("access-")
            return httpx.Response(200, json={"code": 0, "data": {"id": "lx-" + uid}})
        if path == "/api/auth/logout":
            return httpx.Response(200, json={"code": 0, "data": {}})
        if path == "/api/billing/app/recharge-packages":
            assert req.headers["X-Lynxce-Iap-App"] == "cn.lynxce.octopbot"
            return httpx.Response(
                200,
                json={"code": 0, "data": {"packages": [], "payment": {"apple": {"enabled": True}}}},
            )
        if path == "/api/billing/apple/purchase-intents":
            assert req.headers["X-Lynxce-Iap-App"] == "cn.lynxce.octopbot"
            assert json.loads(req.content) == {"packageId": "pack-1"}
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "productId": "cn.lynxce.octopbot.credits.1000",
                        "appAccountToken": "00000000-0000-0000-0000-000000000001",
                    },
                },
            )
        if path == "/api/user/account/deletion-request":
            assert json.loads(req.content) == {"confirm": "注销账号"}
            return httpx.Response(
                200, json={"code": 0, "data": {"status": "deactivated", "coolingDays": 7}}
            )
        return httpx.Response(404, json={})


@pytest.fixture
def upstream(monkeypatch: pytest.MonkeyPatch) -> Upstream:
    fake = Upstream()
    monkeypatch.setenv("OCTOP_BOT_CLOUD", "1")
    monkeypatch.setenv("OCTOP_FILE_STORE_BUCKET", "octop-bot-test")
    monkeypatch.setenv("OCTOP_FILE_STORE_ACCESS_KEY_ID", "AKID")
    monkeypatch.setenv("OCTOP_FILE_STORE_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("OCTOP_FILE_STORE_ENDPOINT", "http://127.0.0.1:9")
    monkeypatch.delenv("OCTOP_BOT_WEB", raising=False)
    monkeypatch.setattr(
        cloud, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake))
    )
    monkeypatch.setattr(auth_lynxce, "_failures", {})
    return fake


async def _sign_in(client: httpx.AsyncClient, phone: str) -> dict[str, Any]:
    res = await client.post(CODE_LOGIN, json={"target": phone, "code": "123456"})
    assert res.status_code == 200, res.text
    body: dict[str, Any] = res.json()
    return body


async def test_each_lynxce_account_gets_its_own_tenant(
    tmp_octop_home: Path, upstream: Upstream
) -> None:
    async with octop_client(tmp_octop_home) as (client, srv):
        assert (await client.get(STATUS)).json() == {
            "enabled": True,
            "claimed": False,
            "cloud": True,
            "legacy_owner": False,
        }
        info = (await client.get(INFO)).json()
        assert info["edition"] == "cloud"
        assert info["sign_in"] == ["lynxce"]
        assert info["setup_required"] is False
        assert info["capabilities"]["wallet"] is True
        assert info["capabilities"]["file_store"] == "object"

        alice = await _sign_in(client, "13800000001")
        bob = await _sign_in(client, "13800000002")
        assert alice["user"]["role"] == "user"
        assert alice["user"]["id"] != bob["user"]["id"]

        # Signing in again finds the same tenant and keeps its model key.
        again = await _sign_in(client, "13800000001")
        assert again["user"]["id"] == alice["user"]["id"]
        names = [k["name"] for k in upstream.keys]
        assert names == [
            accounts.key_name(srv.services, alice["user"]["id"]),
            accounts.key_name(srv.services, bob["user"]["id"]),
        ]
        assert names[0].startswith(accounts.KEY_NAME + " · ") and names[0] != names[1]
        assert upstream.deleted == []
        assert upstream.keys[0]["scopes"] == ["model:chat", "media:image", "media:video"]
        assert upstream.patched == []  # new keys already have the media scopes
        # The replaced session is closed upstream.
        assert upstream.counts["/api/auth/logout"] == 1

        uid = alice["user"]["id"]
        key = accounts.load_model_key(srv.services, uid)
        assert key is not None and key.secret == "sk-test-1"
        assert cloud.cloud_status(srv.services, uid).account_id == "lx-13800000001"

        # The tenant's chats use their own key on the Lynxce open gateway.
        selected = account_selection(srv.services, uid)
        assert isinstance(selected, CloudAccountModel)
        assert selected.model_id == accounts.DEFAULT_MODEL
        provider = selected.provider(srv.services)
        assert provider.base_url == GATEWAY_URL
        assert await provider.api_key() == "sk-test-1"  # type: ignore[operator]


async def test_tenants_cannot_reach_the_host(tmp_octop_home: Path, upstream: Upstream) -> None:
    async with octop_client(tmp_octop_home) as (client, srv):
        signed_in = await _sign_in(client, "13800000003")
        token = signed_in["access_token"]
        auth = {"Authorization": f"Bearer {token}"}
        fs = await client.get("/api/filesystem/roots", headers=auth)
        assert fs.status_code == 403
        mcp = await client.put("/api/connectors/custom-mcp", headers=auth, json={"servers": {}})
        assert mcp.status_code == 403
        # Nor the server's own browser or screen: their Bots use their own cloud computers.
        from octop.infra.agents.manager import TENANT_HOST_TOOLS

        registry = srv.app_runtime.agent_registry
        assert registry._tenant_tools_disabled(signed_in["user"]["id"], {"x"}) == {
            "x",
            *TENANT_HOST_TOOLS,
        }
        assert registry._tenant_tools_disabled(None, {"x"}) == {"x"}


async def test_a_tenants_agent_is_pinned_to_its_object_store_prefix(
    tmp_octop_home: Path, upstream: Upstream
) -> None:
    from octop.infra.agents.manager import AgentCreateSpec

    async with octop_client(tmp_octop_home) as (client, srv):
        uid = (await _sign_in(client, "13800000004"))["user"]["id"]
        row = await srv.app_runtime.agent_registry.create(
            AgentCreateSpec(
                user_id=uid,
                name="Writer",
                config={"backend": {"type": "local_shell", "root_dir": "/"}},
            ),
            defer_bootstrap=True,
        )
        config = json.loads(row.config_json)
        assert config["backend"] == cloud_files.agent_backend(uid, row.agent_id)
        await srv.app_runtime.agent_registry.update_config_json(
            row.agent_id, json.dumps({**config, "backend": {"type": "local_shell"}})
        )
        stored = json.loads(srv.services.agent_repo.get(row.agent_id).config_json)
        assert stored["backend"] == cloud_files.agent_backend(uid, row.agent_id)


async def test_tenants_buy_credits_and_delete_their_account_through_the_server(
    tmp_octop_home: Path, upstream: Upstream
) -> None:
    async with octop_client(tmp_octop_home) as (client, srv):
        signed = await _sign_in(client, "13800000005")
        assert signed["cloud"] is True
        assert (await client.get("/api/setup/status")).json()["lynxce_login"] is True
        auth = {"Authorization": f"Bearer {signed['access_token']}"}
        packs = await client.get("/api/octop-bot/wallet/packs", headers=auth)
        assert packs.status_code == 200 and packs.json()["payment"]["apple"]["enabled"] is True
        intent = await client.post(
            "/api/octop-bot/wallet/apple/intent", headers=auth, json={"package_id": "pack-1"}
        )
        assert intent.json()["productId"] == "cn.lynxce.octopbot.credits.1000"

        uid = signed["user"]["id"]
        gone = await client.post("/api/octop-bot/account/delete", headers=auth)
        assert gone.status_code == 200 and gone.json() == {"cooling_days": 7}
        assert srv.services.user_repo.get(uid).disabled
        assert accounts.load_model_key(srv.services, uid) is None
        assert cloud.cloud_status(srv.services, uid).connected is False


async def test_with_ags_configured_each_bot_gets_its_own_computer(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    from octop.infra.agents.manager import AgentCreateSpec
    from octop.infra.backend.resolver import resolve_agent_backend_spec
    from octop.infra.cloud.computers import manager as computers
    from octop.infra.cloud.computers.backend import CloudComputer

    for name, value in {
        "OCTOP_AGS_SECRET_ID": "id",
        "OCTOP_AGS_SECRET_KEY": "key",
        "OCTOP_AGS_TOOL": "octop-bot-desktop",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(computers, "_manager", None)
    async with octop_client(tmp_octop_home) as (client, srv):
        alice = await _sign_in(client, "13800000006")
        bob = await _sign_in(client, "13800000007")
        row = await srv.app_runtime.agent_registry.create(
            AgentCreateSpec(user_id=alice["user"]["id"], name="Analyst"), defer_bootstrap=True
        )
        backend = resolve_agent_backend_spec(
            cloud_files.agent_backend(alice["user"]["id"], row.agent_id), repo=None
        )
        assert isinstance(backend, CloudComputer)
        assert backend.id == f"computer-{row.agent_id}"

        # A tenant's Bot gets the computer tools (shown on every turn: phone, IM, schedule).
        registry = srv.app_runtime.agent_registry
        tools = registry._cloud_computer_tools(row)
        assert [t.name for t in tools] == ["cloud_computer", "request_takeover"]

        path = f"/api/octop-bot/computers/{row.agent_id}"
        mine = await client.get(path, headers={"Authorization": f"Bearer {alice['access_token']}"})
        assert mine.status_code == 200
        assert mine.json()["state"] == "none"
        theirs = await client.get(path, headers={"Authorization": f"Bearer {bob['access_token']}"})
        assert theirs.status_code == 404


async def test_review_fixes_locale_probe_policy_and_im_billing(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from octop.infra.users.resource_policy import backend_policy_types_in

    assert backend_policy_types_in(
        cloud_files.agent_backend(1, "abc"), named_kind=lambda _: None
    ) == {"s3"}
    async with octop_client(tmp_octop_home) as (client, srv):
        # A new tenant starts in the language of their first sign-in, then keeps it.
        first = await client.post(
            CODE_LOGIN, json={"target": "13800000010", "code": "123456", "locale": "en"}
        )
        assert first.json()["user"]["locale"] == "en"
        again = await client.post(
            CODE_LOGIN, json={"target": "13800000010", "code": "123456", "locale": "zh"}
        )
        assert srv.services.user_repo.get(again.json()["user"]["id"]).locale == "en"

        auth = {"Authorization": f"Bearer {first.json()['access_token']}"}
        probe = await client.post(
            "/api/connectors/custom-mcp/test",
            headers=auth,
            json={"server": {"transport": "stdio", "command": "touch", "args": ["/tmp/x"]}},
        )
        assert probe.status_code == 403

        # IM threads of a tenant's Bot bill the tenant too.
        uid = first.json()["user"]["id"]
        registry = srv.app_runtime.agent_registry
        from octop.infra.agents.manager import AgentCreateSpec

        row = await registry.create(AgentCreateSpec(user_id=uid, name="Desk"), defer_bootstrap=True)
        thread = SimpleNamespace(channel_type="telegram", user_id=uid, agent_id=row.agent_id)
        monkeypatch.setattr(registry._repos.thread_repo, "get", lambda _id: thread)
        selected = registry._account_for_bot_turn(row.agent_id, "t1", {"user": "tg:42"})
        assert selected is not None and selected.user_id == uid


async def test_screen_tickets_are_owner_only_and_single_use(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    from octop.infra.agents.manager import AgentCreateSpec
    from octop.infra.cloud.computers import manager as computers

    for name, value in {
        "OCTOP_AGS_SECRET_ID": "id",
        "OCTOP_AGS_SECRET_KEY": "key",
        "OCTOP_AGS_TOOL": "octop-bot-desktop",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(computers, "_manager", None)
    monkeypatch.setattr(computers.ComputerManager, "ensure_running", lambda self, a, u: "ins-1")
    async with octop_client(tmp_octop_home) as (client, srv):
        alice = await _sign_in(client, "13800000008")
        bob = await _sign_in(client, "13800000009")
        row = await srv.app_runtime.agent_registry.create(
            AgentCreateSpec(user_id=alice["user"]["id"], name="Clerk"), defer_bootstrap=True
        )
        mine = {"Authorization": f"Bearer {alice['access_token']}"}
        path = f"/api/octop-bot/computers/{row.agent_id}"
        assert (
            await client.post(
                path + "/screen", headers={"Authorization": f"Bearer {bob['access_token']}"}
            )
        ).status_code == 404
        ticket = (await client.post(path + "/screen", headers=mine)).json()
        assert ticket["ws_path"].startswith(path + "/screen/ws?ticket=")

        # Typing and the clipboard go through the screen session, with no sign-in (the
        # phone apps' screen page has none), and only while the user has taken over.
        pasted: list[str] = []
        monkeypatch.setattr(
            computers.AgsDriver, "paste_text", lambda self, i, text: pasted.append(text)
        )
        monkeypatch.setattr(computers.AgsDriver, "read_clipboard", lambda self, i: "剪贴板")
        manager = computers.computer_manager(srv.services)
        assert manager is not None
        record = manager.record(row.agent_id, alice["user"]["id"])
        record.running, record.instance_id = True, "ins-1"
        manager._save(record)
        typing = f"/api/octop-bot/screen-sessions/{ticket['session']}"
        refused = await client.post(typing + "/type", json={"text": "你好"})
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "BOT_COMPUTER_NOT_TAKEN_OVER"

        taken = await client.post(path + "/takeover", headers=mine, json={"active": True})
        assert taken.json()["takeover"] is True
        assert (await client.post(typing + "/type", json={"text": "你好"})).status_code == 204
        assert pasted == ["你好"]
        assert (await client.get(typing + "/clipboard")).json() == {"text": "剪贴板"}
        forged = "/api/octop-bot/screen-sessions/forged/clipboard"
        assert (await client.get(forged)).status_code == 404
        from octop.api.routers import bot_computers

        one_time = ticket["ws_path"].split("ticket=", 1)[1]
        assert one_time in bot_computers._tickets
        bot_computers._tickets.pop(one_time)
        assert one_time not in bot_computers._tickets


async def test_a_revoked_model_key_is_replaced_at_the_next_sign_in(
    tmp_octop_home: Path, upstream: Upstream
) -> None:
    async with octop_client(tmp_octop_home) as (client, srv):
        uid = (await _sign_in(client, "13800000020"))["user"]["id"]
        assert accounts.load_model_key(srv.services, uid).secret == "sk-test-1"
        # Still valid: signing in again keeps it.
        await _sign_in(client, "13800000020")
        assert len(upstream.keys) == 1
        # Revoked in the Lynxce account centre: the next sign-in issues a new one.
        upstream.revoked.add("sk-test-1")
        await _sign_in(client, "13800000020")
        assert accounts.load_model_key(srv.services, uid).secret == "sk-test-2"
        assert len(upstream.keys) == 2


async def test_racing_first_sign_ins_mint_one_model_key(
    tmp_octop_home: Path, upstream: Upstream
) -> None:
    async with octop_client(tmp_octop_home) as (client, srv):
        uid = (await _sign_in(client, "13800000021"))["user"]["id"]
        accounts.forget_model_key(srv.services, uid)
        keys = await asyncio.gather(
            accounts.ensure_model_key(srv.services, uid),
            accounts.ensure_model_key(srv.services, uid),
        )
        assert keys[0] == keys[1]
        assert len(upstream.keys) == 2  # the sign-in's key and one replacement


async def test_tenants_one_shot_calls_use_their_own_key_and_not_the_servers_voice(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    from octop.api.routers import text_assist as text_assist_router
    from octop.infra.users.identity import Role

    seen: dict[str, Any] = {}

    async def _fake_assist(**kwargs: Any) -> str:
        access = kwargs["models"].get(kwargs["default_model"])
        seen["model"] = access.model_ref
        seen["base_url"] = access.chat_model.openai_api_base
        return "polished"

    monkeypatch.setattr(text_assist_router, "run_text_assist", _fake_assist)
    async with octop_client(tmp_octop_home) as (client, srv):
        signed = await _sign_in(client, "13800000022")
        auth = {"Authorization": f"Bearer {signed['access_token']}"}
        res = await client.post(
            "/api/text/assist",
            headers=auth,
            json={"kind": "chat.prompt", "text": "hi", "default_model": "openai/gpt-4o"},
        )
        assert res.status_code == 200, res.text
        # Whatever model the client asks for, a tenant's call runs on their own Lynxce key.
        assert seen["model"] == f"lynxce/{accounts.DEFAULT_MODEL}"
        assert seen["base_url"] == GATEWAY_URL

        registry = srv.app_runtime.agent_registry
        admin = await srv.user_manager.create(
            username="operator", password="Operator-pass1!", role=Role.ADMIN
        )
        assert registry.cloud_tenant_model(admin.id) is None

        tts = await client.post("/api/voice/tts", headers=auth, json={"text": "hi"})
        assert tts.status_code == 403
        stt = await client.post(
            "/api/voice/stt", headers=auth, files={"audio": ("a.webm", b"x", "audio/webm")}
        )
        assert stt.status_code == 403


async def test_host_files_are_closed_to_tenant_agents_only(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    from octop.infra.agents.manager import AgentCreateSpec
    from octop.infra.users.identity import Role

    async with octop_client(tmp_octop_home) as (client, srv):
        registry = srv.app_runtime.agent_registry
        uid = (await _sign_in(client, "13800000023"))["user"]["id"]
        tenant_bot = await registry.create(
            AgentCreateSpec(user_id=uid, name="Tenant"), defer_bootstrap=True
        )
        admin = await srv.user_manager.create(
            username="operator", password="Operator-pass1!", role=Role.ADMIN
        )
        operator_bot = await registry.create(
            AgentCreateSpec(user_id=admin.id, name="Ops"), defer_bootstrap=True
        )
        assert registry.host_files_allowed(tenant_bot.agent_id) is False
        assert registry.host_files_allowed(operator_bot.agent_id) is True

        # Image and video generation run on the operator's providers: not for tenants.
        from octop.infra.agents.settings.media_generation import MediaProviderUpdate

        await registry.save_media_generation(
            enabled=True,
            providers=[
                MediaProviderUpdate(
                    id="ark",
                    provider="volcengine",
                    display_name="Ark",
                    enabled=True,
                    base_url="https://ark.cn-beijing.volces.com/api/v3",
                    image_enabled=True,
                    video_enabled=True,
                    image_model="seedream-test",
                    video_model="seedance-test",
                    api_key="ark-test",
                )
            ],
            default_image_provider="ark",
            default_video_provider="ark",
        )
        rows = srv.services.agent_repo
        # Building the config peeks at the bootstrap marker; there is no object store here.
        import octop_harness.middleware.bootstrap as bootstrap

        monkeypatch.setattr(bootstrap, "bootstrap_marker_exists", lambda *a, **k: True)
        tenant_cfg = registry._build_harness_config(rows.get(tenant_bot.agent_id))
        operator_cfg = registry._build_harness_config(rows.get(operator_bot.agent_id))
        assert tenant_cfg.media_generation is None
        assert operator_cfg.media_generation is not None
        # Tenants make them with their own Lynxce key instead.
        from octop.infra.agents.providers.lynxce_media import LynxceMediaTools

        def media_tools(cfg: Any) -> list[str]:
            return [
                t.name
                for m in cfg.middleware or []
                if isinstance(m, LynxceMediaTools)
                for t in m.tools
            ]

        assert media_tools(tenant_cfg) == ["generate_image", "generate_video"]
        assert media_tools(operator_cfg) == []
        info = (await client.get("/api/octop-bot/server-info")).json()
        assert info["capabilities"]["media_generation"] is True


async def test_a_chat_only_model_key_gets_the_media_scopes_once(
    tmp_octop_home: Path, upstream: Upstream
) -> None:
    async with octop_client(tmp_octop_home) as (client, srv):
        uid = (await _sign_in(client, "13800000024"))["user"]["id"]
        key = accounts.load_model_key(srv.services, uid)
        assert key is not None and key.scopes == accounts.KEY_SCOPES
        # A key minted before media generation: no scopes recorded.
        accounts._save_model_key(
            srv.services, uid, accounts.ModelKey(key.key_id, key.secret, uncapped=True)
        )
        from octop.infra.agents.providers import lynxce as lynxce_provider

        auth = await lynxce_provider.media_auth(srv.services, uid)
        assert (auth.base_url, auth.bearer) == (lynxce_provider.GATEWAY_URL, key.secret)
        assert upstream.patched == [(key.key_id, {"scopes": list(accounts.KEY_SCOPES)})]
        await lynxce_provider.media_auth(srv.services, uid)
        assert len(upstream.patched) == 1


async def test_model_keys_have_no_credit_cap_so_only_the_balance_limits_a_user(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    from octop.infra.agents.providers import lynxce as lynxce_provider

    async with octop_client(tmp_octop_home) as (client, srv):
        uid = (await _sign_in(client, "13800000031"))["user"]["id"]
        # New keys: Lynxce's default daily cap (1000 credits) is turned off explicitly.
        assert upstream.keys[0]["dailyCreditLimit"] is None
        assert upstream.keys[0]["monthlyCreditLimit"] is None
        key = accounts.load_model_key(srv.services, uid)
        assert key is not None and key.uncapped
        assert upstream.patched == []

        # A key minted before this kept the default cap: the next key check lifts it, once.
        accounts._save_model_key(
            srv.services, uid, accounts.ModelKey(key.key_id, key.secret, accounts.KEY_SCOPES)
        )
        model = lynxce_provider.CloudAccountModel(uid, "", accounts.DEFAULT_MODEL)
        key_for_request = model.provider(srv.services).api_key
        lynxce_provider._key_checked.pop(uid, None)
        assert await key_for_request() == key.secret  # type: ignore[operator]
        lifted = (key.key_id, {"dailyCreditLimit": None, "monthlyCreditLimit": None})
        assert upstream.patched == [lifted]
        assert accounts.load_model_key(srv.services, uid).uncapped  # type: ignore[union-attr]
        lynxce_provider._key_checked.pop(uid, None)
        await key_for_request()  # type: ignore[operator]
        await _sign_in(client, "13800000031")
        assert upstream.patched == [lifted]

        # An operator who sets a daily cap keeps it, on new keys and old ones.
        monkeypatch.setenv("OCTOP_BOT_CLOUD_KEY_DAILY_LIMIT", "5000")
        other = (await _sign_in(client, "13800000032"))["user"]["id"]
        assert upstream.keys[-1]["dailyCreditLimit"] == 5000
        assert not accounts.load_model_key(srv.services, other).uncapped  # type: ignore[union-attr]
        lynxce_provider._key_checked.pop(other, None)
        await lynxce_provider.cloud_model_key(srv.services, other)
        assert upstream.patched == [lifted]


async def test_only_a_401_replaces_the_model_key(tmp_octop_home: Path, upstream: Upstream) -> None:
    async with octop_client(tmp_octop_home) as (client, srv):
        uid = (await _sign_in(client, "13800000030"))["user"]["id"]
        # Out of credits (403): a new key would not help, so none is minted.
        upstream.forbidden.add("sk-test-1")
        await _sign_in(client, "13800000030")
        assert len(upstream.keys) == 1
        # Revoked (401) while the tenant is chatting: replaced on the next check, no sign-in.
        from octop.infra.agents.providers import lynxce as lynxce_provider

        upstream.revoked.add("sk-test-1")
        model = lynxce_provider.CloudAccountModel(uid, "", accounts.DEFAULT_MODEL)
        key_for_request = model.provider(srv.services).api_key
        lynxce_provider._key_checked.pop(uid, None)
        assert await key_for_request() == "sk-test-2"  # type: ignore[operator]
        assert len(upstream.keys) == 2


async def test_a_sign_in_that_cannot_get_a_model_key_closes_its_session(
    tmp_octop_home: Path, upstream: Upstream
) -> None:
    from octop.infra.auth import lynxce_cloud

    async with octop_client(tmp_octop_home) as (client, srv):
        upstream.mint_fails = True
        res = await client.post(CODE_LOGIN, json={"target": "13800000031", "code": "123456"})
        assert res.status_code >= 400
        assert upstream.counts["/api/auth/logout"] >= 1
        provider_id = accounts._provider_id(srv.services)
        user = srv.services.user_repo.get_by_sso(provider_id, "lx-13800000031")
        assert user is not None
        assert lynxce_cloud._load(srv.services, user.id) is None


async def test_disabled_tenants_and_cancelled_deletions(
    tmp_octop_home: Path, upstream: Upstream
) -> None:
    async with octop_client(tmp_octop_home) as (client, srv):
        users = srv.user_manager
        # Deleted, then the deletion is cancelled at Lynxce: signing in again restores the account.
        signed = await _sign_in(client, "13800000024")
        uid = signed["user"]["id"]
        auth = {"Authorization": f"Bearer {signed['access_token']}"}
        assert (await client.post("/api/octop-bot/account/delete", headers=auth)).status_code == 200
        assert srv.services.user_repo.get(uid).disabled
        back = await _sign_in(client, "13800000024")
        assert back["user"]["id"] == uid
        assert not srv.services.user_repo.get(uid).disabled
        assert users.disabled_reason(uid) is None
        assert accounts.load_model_key(srv.services, uid) is not None

        # Disabled by the operator (even after a deletion request): stays out, and the Lynxce
        # session opened by the attempt is closed again.
        await users.disable(
            srv.services.user_repo.get(uid).username, reason=accounts.DELETION_PENDING
        )
        await users.disable(srv.services.user_repo.get(uid).username)
        logouts = upstream.counts["/api/auth/logout"]
        refused = await client.post(CODE_LOGIN, json={"target": "13800000024", "code": "123456"})
        assert refused.status_code == 403
        assert srv.services.user_repo.get(uid).disabled
        assert upstream.counts["/api/auth/logout"] == logouts + 1


async def test_a_replaced_model_key_is_revoked_not_left_behind(
    tmp_octop_home: Path, upstream: Upstream
) -> None:
    """Revoked or lost keys are replaced without piling up in the Lynxce account."""
    async with octop_client(tmp_octop_home) as (client, srv):
        phone = "13800000040"
        owner = f"access-{phone}"
        uid = (await _sign_in(client, phone))["user"]["id"]
        name = accounts.key_name(srv.services, uid)
        # Another server and a desktop chat through the same account; an old untagged key
        # was used once, another never.
        upstream.live.update(
            {
                "web": {"id": "web", "name": "Octop Bot 云端 · 0a0a0a", "lastUsedAt": None},
                "old-used": {
                    "id": "old-used",
                    "name": accounts.KEY_NAME,
                    "lastUsedAt": "2026-11-01T00:00:00.000Z",
                },
                "old-idle": {"id": "old-idle", "name": accounts.KEY_NAME, "lastUsedAt": None},
                "mine": {"id": "mine", "name": "我的脚本", "lastUsedAt": None},
            }
        )
        for key in upstream.live.values():
            key.setdefault("owner", owner)

        # Signing in again with a working key mints nothing and revokes nothing.
        await _sign_in(client, phone)
        assert len(upstream.keys) == 1 and upstream.deleted == []

        # Revoked in the console (401): the old key is deleted with the idle untagged one.
        upstream.revoked.add("sk-test-1")
        await _sign_in(client, phone)
        assert sorted(upstream.deleted) == ["key-1", "old-idle"]
        assert accounts.load_model_key(srv.services, uid).key_id == "key-2"

        # Database swap (the key is forgotten here): this server's key is found by its name.
        accounts.forget_model_key(srv.services, uid)
        await accounts.ensure_model_key(srv.services, uid)
        assert upstream.deleted[-1] == "key-2"
        assert {k["name"] for k in upstream.live.values() if k["owner"] == owner} == {
            name,
            "Octop Bot 云端 · 0a0a0a",
            accounts.KEY_NAME,
            "我的脚本",
        }
        assert sorted(upstream.live) == ["key-3", "mine", "old-used", "web"]

        # Lynxce cannot list keys right now: the replacement is still minted.
        upstream.list_fails = True
        accounts.forget_model_key(srv.services, uid)
        assert (await accounts.ensure_model_key(srv.services, uid)).key_id == "key-4"


async def test_model_key_names_are_fixed_per_server_and_user(
    tmp_octop_home: Path, upstream: Upstream
) -> None:
    async with octop_client(tmp_octop_home) as (_client, srv):
        first = accounts.key_name(srv.services, 1)
        assert accounts.key_name(srv.services, 1) == first
        assert accounts.key_name(srv.services, 2) != first
        assert len(first) <= 40  # Lynxce's limit on key names
        # A new database on the same OCTOP_HOME keeps the names; another home does not.
        (tmp_octop_home / accounts.INSTANCE_FILE).write_text("other-server")
        assert accounts.key_name(srv.services, 1) != first


async def test_only_the_bots_work_or_its_screen_start_a_cloud_computer(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Signing up, making Bots, writing deliverables, file cards, previews and the @ menu
    never start a cloud computer; opening its screen does (as do commands, unit-tested)."""
    import octop_harness.backends as harness_backends
    from deepagents.backends.filesystem import FilesystemBackend
    from octop_harness.backends.workspace import BackendWorkspace

    from octop.infra.agents.manager import AgentCreateSpec
    from octop.infra.cloud.computers import manager as computers
    from octop.infra.cloud.computers.backend import CloudComputer

    # As in production: new computers on CVM, older ones on AGS.
    for name, value in {
        "OCTOP_AGS_SECRET_ID": "id",
        "OCTOP_AGS_SECRET_KEY": "key",
        "OCTOP_AGS_TOOL": "octop-bot-desktop",
        "OCTOP_CVM_SECRET_ID": "AKID-test",
        "OCTOP_CVM_SECRET_KEY": "secret-test",
        "OCTOP_CVM_IMAGE_ID": "img-octop",
        "OCTOP_CVM_VPC_ID": "vpc-1",
        "OCTOP_CVM_SUBNETS": "ap-guangzhou-6:subnet-6",
        "OCTOP_CVM_SECURITY_GROUP": "sg-1",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(computers, "_manager", None)
    started: list[str] = []
    monkeypatch.setattr(
        computers.ComputerManager,
        "ensure_running",
        lambda self, agent_id, user_id, seed=None: started.append(agent_id) or "ins-1",
    )
    # The object store, as a local folder per Bot.
    monkeypatch.setattr(
        cloud_files.FileStoreConfig, "from_env", classmethod(lambda cls, env=None: object())
    )
    monkeypatch.setattr(
        cloud_files,
        "harness_spec",
        lambda spec, config=None: {"type": "test-store", "agent_id": spec["agent_id"]},
    )
    real_resolve = harness_backends.resolve_backend

    def resolve(spec: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(spec, dict) and spec.get("type") == "test-store":
            return FilesystemBackend(root_dir=str(tmp_path / spec["agent_id"]), virtual_mode=True)
        return real_resolve(spec, *args, **kwargs)

    monkeypatch.setattr(harness_backends, "resolve_backend", resolve)

    async with octop_client(tmp_octop_home) as (client, srv):
        from octop.infra.cloud.computers.mixed import MixedDriver

        assert isinstance(computers.current_manager()._driver, MixedDriver)  # type: ignore[union-attr]
        signed = await _sign_in(client, "13800000040")
        auth = {"Authorization": f"Bearer {signed['access_token']}"}
        assert (await client.get("/api/octop-bot/workspace", headers=auth)).status_code == 200
        row = await srv.app_runtime.agent_registry.create(
            AgentCreateSpec(user_id=signed["user"]["id"], name="Analyst")
        )
        aid = row.agent_id
        # Tests run a fake harness agent: give it the workspace production builds, on the
        # Bot's own backend (its cloud computer, with the store in front).
        entry = srv.app_runtime.agent_registry._harness_manager.get_agent(aid)
        assert isinstance(entry.config.backend, CloudComputer)
        entry.agent._backend = entry.config.backend
        entry.agent._workspace = BackendWorkspace(entry.config.backend, tmp_path / "host")
        # A document it writes in a chat, an image it generates.
        workspace = srv.app_runtime.agent_registry.workspace_for_agent(aid)
        await workspace.aupload_bytes("generated/report.md", b"# Report")
        await workspace.aupload_bytes("generated/cat.png", b"\x89PNG fake")
        assert started == []

        base = f"/api/agents/{aid}"
        card = await client.head(
            base + "/workspace/download", params={"path": "/generated/report.md"}, headers=auth
        )
        assert card.status_code == 200 and card.headers["content-length"] == "8"
        preview = await client.get(
            base + "/media/preview", params={"source": "/generated/cat.png"}, headers=auth
        )
        assert preview.status_code == 200
        mentions = await client.get(base + "/workspace/mention-index", headers=auth)
        assert mentions.status_code == 200
        assert "generated/report.md" in mentions.json()["paths"]
        # Files only on the (off) computer: a clear answer instead of starting it.
        off = await client.head(
            base + "/workspace/download", params={"path": "/notes/plan.md"}, headers=auth
        )
        assert off.status_code == 409
        shot = await client.get(
            base + "/media/preview", params={"source": "/shots/screen.png"}, headers=auth
        )
        assert shot.status_code == 409
        assert shot.json()["error"]["code"] == "BOT_COMPUTER_OFF"
        assert started == []

        # The user opening its screen starts it.
        screen = await client.post(f"/api/octop-bot/computers/{aid}/screen", headers=auth)
        assert screen.status_code == 200, screen.text
        assert started == [aid]


async def test_tenant_config_allowlist(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A tenant's agent config keeps only what a tenant may set, whether sent when creating or
    editing a Bot or already stored; the agent is built on its object-store backend."""
    import json as _json

    import octop_harness.middleware.bootstrap as bootstrap

    from octop.infra.agents.manager import AgentCreateSpec
    from octop.infra.agents.workspace.dir import default_workspace_for_chat_agent

    monkeypatch.setattr(bootstrap, "bootstrap_marker_exists", lambda *a, **k: True)
    target = tmp_path / "victim"
    extra = {
        "acp": {"tool_enabled": True, "runners": {"sh": {"command": "/bin/sh", "enabled": True}}},
        "workspace_dir": str(target),
        "memory": {"backend": {"type": "sqlite", "db_path": str(tmp_path / "x.db")}, "x": 1},
        "security": {"enabled": False},
        "skills": [str(tmp_path)],
        "persona": "INTJ",
    }
    async with octop_client(tmp_octop_home) as (client, srv):
        signed = await _sign_in(client, "13800000060")
        auth = {"Authorization": f"Bearer {signed['access_token']}"}
        uid = signed["user"]["id"]
        registry = srv.app_runtime.agent_registry
        rows = srv.services.agent_repo

        made = await client.post("/api/agents", headers=auth, json={"name": "A", "config": extra})
        assert made.status_code == 201, made.text
        aid = made.json()["agent_id"]
        stored = _json.loads(rows.get(aid).config_json)
        assert {"acp", "security", "skills"}.isdisjoint(stored)
        assert stored["workspace_dir"] == default_workspace_for_chat_agent(aid)
        assert "backend" not in stored.get("memory", {})
        assert stored["backend"]["type"] == "bot_cloud"
        assert not target.exists()

        edited = await client.patch(f"/api/agents/{aid}", headers=auth, json={"config": extra})
        assert edited.status_code == 200, edited.text
        stored = _json.loads(rows.get(aid).config_json)
        assert "acp" not in stored and stored["workspace_dir"] == default_workspace_for_chat_agent(
            aid
        )

        # A stored row with extra keys, and runners saved for the account: built the same way.
        rows.update_config(
            aid, config_json=_json.dumps({**extra, "backend": {"type": "local_shell"}})
        )
        registry._acp_settings.save_runners(uid, {"sh": {"command": "/bin/sh", "enabled": True}})
        cfg = registry._build_harness_config(rows.get(aid))
        assert cfg.acp_delegate_enabled is False
        assert "sh" not in cfg.acp_runners
        assert {"acp_runner", "web_fetch", "browser_use"} <= set(cfg.tools_disabled)
        assert not target.exists()
        healed = _json.loads(rows.get(aid).config_json)
        assert "acp" not in healed and healed["backend"]["type"] == "bot_cloud"

        # A tenant row without its object-store backend does not build.
        from octop.infra.errors import ErrorCode as _Code
        from octop.infra.errors import OctopError as _Error

        with pytest.raises(_Error) as refused:
            registry._backend_spec_for_row(rows.get(aid), cfg={"workspace_dir": str(tmp_path)})
        assert refused.value.code == _Code.FORBIDDEN

        # Managed agents are not for tenants.
        with pytest.raises(_Error):
            await registry.create(AgentCreateSpec(user_id=uid, name="M", kind="managed"))


async def test_tenant_workspace_replace_keeps_local_files(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import io
    import zipfile

    from deepagents.backends.filesystem import FilesystemBackend
    from octop_harness.backends.workspace import BackendWorkspace

    from octop.api.routers import workspace as workspace_routes
    from octop.infra.agents.manager import AgentCreateSpec

    store = tmp_path / "store"
    store.mkdir()

    async def running(*args: Any, **kwargs: Any) -> Any:
        return BackendWorkspace(FilesystemBackend(root_dir=str(store), virtual_mode=True), store)

    monkeypatch.setattr(workspace_routes, "require_running_workspace", running)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("new.txt", "new")
    async with octop_client(tmp_octop_home) as (client, srv):
        signed = await _sign_in(client, "13800000061")
        auth = {"Authorization": f"Bearer {signed['access_token']}"}
        registry = srv.app_runtime.agent_registry
        row = await registry.create(
            AgentCreateSpec(user_id=signed["user"]["id"], name="R"), defer_bootstrap=True
        )
        local = registry.resolve_workspace_dir(row.agent_id)
        (local / "keep.txt").write_text("local file")
        sent = await client.post(
            f"/api/agents/{row.agent_id}/workspace/archive",
            params={"mode": "replace"},
            headers=auth,
            files={"file": ("w.zip", archive.getvalue(), "application/zip")},
        )
        assert sent.status_code == 200, sent.text
        assert (local / "keep.txt").read_text() == "local file"
        assert (store / "new.txt").read_text() == "new"


async def test_tenant_host_routes_are_closed(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    from octop.infra.agents.manager import AgentCreateSpec
    from octop.infra.users.identity import Role

    async with octop_client(tmp_octop_home) as (client, srv):
        signed = await _sign_in(client, "13800000070")
        auth = {"Authorization": f"Bearer {signed['access_token']}"}
        registry = srv.app_runtime.agent_registry
        mine = await registry.create(
            AgentCreateSpec(user_id=signed["user"]["id"], name="T"), defer_bootstrap=True
        )
        aid = mine.agent_id
        closed = [
            ("GET", "/api/acp"),
            ("GET", "/api/managed-agents/template"),
            ("GET", f"/api/agents/{aid}/git/status"),
            ("GET", f"/api/agents/{aid}/threads/t/files/latest-message"),
            ("GET", "/api/bridge/connections"),
            ("POST", "/api/bridge/probe"),
            ("GET", "/api/memory/portable/sources"),
            ("POST", f"/api/agents/{aid}/memory/portable/pack"),
            ("GET", "/api/browser/env-status"),
            ("GET", "/api/browser/harness-sessions"),
        ]
        for method, path in closed:
            got = await client.request(method, path, headers=auth, json={})
            assert got.status_code == 403, (path, got.status_code, got.text)

        # The operator still has them.
        admin = await srv.user_manager.create(
            username="operator", password="Operator-pass1!", role=Role.ADMIN
        )
        from octop.infra.users.manager import UserManager  # noqa: F401

        login = await client.post(
            "/api/auth/login", json={"username": "operator", "password": "Operator-pass1!"}
        )
        admin_auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
        for method, path in (("GET", "/api/acp"), ("GET", "/api/bridge/connections")):
            got = await client.request(method, path, headers=admin_auth)
            assert got.status_code != 403, (path, got.text)
        assert admin.is_admin


async def test_tenants_use_only_agents_in_tenant_space(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    from octop.infra.agents.manager import AgentCreateSpec
    from octop.infra.users.identity import Role

    async with octop_client(tmp_octop_home) as (client, srv):
        registry = srv.app_runtime.agent_registry
        admin = await srv.user_manager.create(
            username="operator", password="Operator-pass1!", role=Role.ADMIN
        )
        shared = await registry.create(
            AgentCreateSpec(user_id=admin.id, name="Ops", is_shared=True), defer_bootstrap=True
        )
        assert shared.is_shared
        signed = await _sign_in(client, "13800000071")
        auth = {"Authorization": f"Bearer {signed['access_token']}"}
        seen = await client.get(f"/api/agents/{shared.agent_id}", headers=auth)
        assert seen.status_code in (403, 404)
        files = await client.get(f"/api/agents/{shared.agent_id}/workspace/tree", headers=auth)
        assert files.status_code in (403, 404)

        # A tenant's own Bots stay its own.
        made = await client.post(
            "/api/agents", headers=auth, json={"name": "Mine", "is_shared": True}
        )
        assert made.status_code == 201, made.text
        assert made.json()["is_shared"] is False
        widened = await client.patch(
            f"/api/agents/{made.json()['agent_id']}", headers=auth, json={"visibility": "all"}
        )
        assert widened.status_code == 403


async def test_tenant_connector_and_channel_addresses_are_public(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    from octop.infra.agents.manager import AgentCreateSpec

    async with octop_client(tmp_octop_home) as (client, srv):
        signed = await _sign_in(client, "13800000072")
        auth = {"Authorization": f"Bearer {signed['access_token']}"}
        for kind, credentials in (
            ("gitea", {"base_url": "http://172.17.0.1:3000", "token": "x"}),
            ("ragflow", {"base_url": "https://100.100.100.200/", "api_key": "x"}),
            ("obsidian-cli", {"binary_path": "/bin/sh"}),
        ):
            for path in ("/api/connectors/test-credentials", "/api/connector-instances"):
                got = await client.post(
                    path,
                    headers=auth,
                    json={"kind": kind, "display_name": kind, "credentials": credentials},
                )
                assert got.status_code == 400, (kind, path, got.text)
                assert got.json()["error"]["code"] == "ENDPOINT_NOT_ALLOWED"
        bot = await srv.app_runtime.agent_registry.create(
            AgentCreateSpec(user_id=signed["user"]["id"], name="C"), defer_bootstrap=True
        )
        channel = await client.post(
            f"/api/agents/{bot.agent_id}/channels",
            headers=auth,
            json={"kind": "mqtt", "name": "m", "config": {"host": "127.0.0.1"}},
        )
        assert channel.status_code == 400, channel.text


async def test_tenant_group_member_builds_in_its_room(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import octop_harness.middleware.bootstrap as bootstrap

    from octop.infra.agents.manager import AgentCreateSpec
    from octop.infra.errors import ErrorCode as _Code
    from octop.infra.errors import OctopError as _Error

    monkeypatch.setattr(bootstrap, "bootstrap_marker_exists", lambda *a, **k: True)
    async with octop_client(tmp_octop_home) as (client, srv):
        signed = await _sign_in(client, "13800000073")
        registry = srv.app_runtime.agent_registry
        row = await registry.create(
            AgentCreateSpec(user_id=signed["user"]["id"], name="G"), defer_bootstrap=True
        )
        room = tmp_path / "room"
        cfg = registry._build_harness_config(
            srv.services.agent_repo.get(row.agent_id), room_workspace=room
        )
        assert cfg is not None
        with pytest.raises(_Error) as refused:
            registry._backend_spec_for_row(
                srv.services.agent_repo.get(row.agent_id),
                cfg={"backend": {"type": "filesystem", "root_dir": str(tmp_path)}},
                room=room,
            )
        assert refused.value.code == _Code.FORBIDDEN
        # The room itself, but resolving absolute paths on the host: refused too.
        with pytest.raises(_Error) as unbounded:
            registry._backend_spec_for_row(
                srv.services.agent_repo.get(row.agent_id),
                cfg={"backend": {"type": "filesystem", "root_dir": str(room)}},
                room=room,
            )
        assert unbounded.value.code == _Code.FORBIDDEN


class _Computer:
    """A cloud-computer provider that answers instantly (no Tencent Cloud)."""

    def __init__(self) -> None:
        self.states: dict[str, str] = {}
        self.files: dict[str, bytes] = {}
        self.ran: list[str] = []

    def start(self, *, spec: str, labels: Any) -> str:
        instance = f"ins-{len(self.states) + 1}"
        self.states[instance] = "running"
        return instance

    def state(self, instance_id: str) -> str:
        return self.states.get(instance_id, "gone")

    def resume(self, instance_id: str) -> None:
        self.states[instance_id] = "running"

    def pause(self, instance_id: str) -> None:
        self.states[instance_id] = "paused"

    def stop(self, instance_id: str) -> None:
        self.states[instance_id] = "gone"

    def wait_ready(self, instance_id: str, timeout: float = 90.0) -> None:
        return None

    def stopped_at(self, instance_id: str) -> float | None:
        return None

    def instances(self) -> list[Any]:
        return []

    def run(self, instance_id: str, command: str, timeout: int) -> tuple[int, str]:
        self.ran.append(command)
        if command.startswith("stat -Lc %s -- "):
            import shlex

            path = shlex.split(command)[-1]
            return (0, str(len(self.files[path]))) if path in self.files else (1, "")
        return 0, f"ran {command}"

    def run_python(self, instance_id: str, code: str) -> str:
        return f"python {code}"

    def screenshot(self, instance_id: str) -> bytes:
        return b"\x89PNG screen"

    def accessibility(self, instance_id: str) -> str:
        return "<desktop/>"

    def write(self, instance_id: str, path: str, data: bytes) -> None:
        self.files[path] = data

    def read(self, instance_id: str, path: str) -> bytes | None:
        return self.files.get(path)


async def test_desktop_bots_get_cloud_computers_through_hidden_shadow_bots(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    from octop.infra.cloud.computers import manager as computers

    provider = _Computer()
    monkeypatch.setattr(computers, "_manager", None)
    monkeypatch.setattr(computers, "computer_driver", lambda: provider)
    monkeypatch.setenv("OCTOP_BOT_COMPUTE_BILLING", "off")
    token_login = "/api/auth/lynxce/token-login"
    origin = "01JD3Q8Z2N6W4M5X7Y9A0B1C2D:K7Q2PZ"

    async with octop_client(tmp_octop_home) as (client, srv):
        # An account that never signed in here: the desktop asks the user to verify once.
        first = await client.post(token_login, json={"access_token": _lynxce_jwt()})
        assert first.status_code == 409
        assert first.json()["error"]["code"] == "BOT_CLOUD_SESSION_REQUIRED"
        bad = await client.post(token_login, json={"access_token": "forged"})
        assert bad.status_code == 403
        signed = await _sign_in(client, "13800000050")
        sessions_before = upstream.counts["/api/auth/refresh"]
        got = await client.post(token_login, json={"access_token": _lynxce_jwt()})
        assert got.status_code == 200, got.text
        assert got.json()["user"]["id"] == signed["user"]["id"] and got.json()["cloud"]
        # Only read: the desktop's session is neither renewed nor taken.
        assert upstream.counts["/api/auth/refresh"] == sessions_before
        auth = {"Authorization": f"Bearer {got.json()['access_token']}"}

        made = await client.put(
            f"/api/octop-bot/remote-bots/{origin}", headers=auth, json={"name": "Writer"}
        )
        assert made.status_code == 200, made.text
        shadow = made.json()["agent_id"]
        assert made.json()["created"] is True
        again = await client.put(
            f"/api/octop-bot/remote-bots/{origin}", headers=auth, json={"name": "Writer 2"}
        )
        assert again.json() == {"agent_id": shadow, "origin": origin, "created": False}
        assert (
            await client.put(
                "/api/octop-bot/remote-bots/no-colon", headers=auth, json={"name": "x"}
            )
        ).status_code == 422

        full_auth = {"Authorization": f"Bearer {signed['access_token']}"}
        srv.services.agent_repo.create(
            agent_id="regular-bot", user_id=signed["user"]["id"], name="Regular"
        )
        regular_run = "/api/octop-bot/computers/regular-bot/run"
        assert (
            await client.post(regular_run, headers=auth, json={"command": "echo hi"})
        ).status_code == 404
        assert (
            await client.post(regular_run, headers=full_auth, json={"command": "echo hi"})
        ).status_code == 200
        for endpoint in ("/api/auth/me", "/api/octop-bot/wallet"):
            assert (await client.get(endpoint, headers=auth)).status_code in (401, 403)
        assert "X-Octop-Access-Token" not in made.headers
        for method, endpoint in (
            ("POST", f"/api/agents/{shadow}/start"),
            ("GET", f"/api/agents/{shadow}"),
            ("PATCH", f"/api/agents/{shadow}"),
            ("GET", f"/api/agents/{shadow}/workspace/tree"),
            ("GET", f"/api/agents/{shadow}/chat/welcome"),
        ):
            assert (
                await client.request(
                    method, endpoint, headers=full_auth, json={} if method == "PATCH" else None
                )
            ).status_code == 404

        # The tenant cannot remove server-owned origin metadata by changing the config.
        from octop.infra.cloud.bot_cloud import shadows as shadow_helpers

        srv.services.agent_repo.update_config(shadow, config_json="{}")
        assert (
            shadow_helpers.find_shadow(srv.services, signed["user"]["id"], origin).agent_id
            == shadow
        )

        # Never listed: web, phones, groups; and no Bot pages for it.
        for listing in ("/api/agents", "/api/octop-bot/workspace", "/api/octop-bot/groups"):
            seen = await client.get(listing, headers=full_auth)
            assert seen.status_code == 200, (listing, seen.text)
            assert shadow not in seen.text, listing
        assert (
            await client.get(f"/api/octop-bot/bots/{shadow}/upcoming", headers=full_auth)
        ).status_code == 404
        group = await client.post(
            "/api/octop-bot/groups",
            headers=full_auth,
            json={"name": "Team", "member_ids": [shadow]},
        )
        assert group.status_code >= 400

        # Its computer, driven from the desktop.
        base = f"/api/octop-bot/computers/{shadow}"
        assert (await client.get(base, headers=auth)).json()["state"] == "none"
        ran = await client.post(base + "/run", headers=auth, json={"command": "echo hi"})
        assert ran.json() == {
            "exit_code": 0,
            "output": "ran echo hi",
            "taken_over": False,
            "truncated": False,
        }
        py = await client.post(base + "/python", headers=auth, json={"code": "print(1)"})
        assert py.json()["output"] == "python print(1)"
        entries = srv.services.audit_repo.query(action="computer.run")
        assert entries[0].target == shadow and "echo hi" in entries[0].payload
        monkeypatch.setattr(provider, "run_python", lambda instance, code: "x" * (1024 * 1024 + 1))
        large = await client.post(base + "/python", headers=auth, json={"code": "long"})
        assert large.json()["truncated"] is True
        assert len(large.json()["output"]) == 1024 * 1024
        shot = await client.get(base + "/screenshot", headers=auth)
        assert shot.headers["content-type"] == "image/png" and shot.content.startswith(b"\x89PNG")
        assert (await client.get(base + "/accessibility", headers=auth)).json() == {
            "xml": "<desktop/>"
        }
        put = await client.put(
            base + "/files", params={"path": "notes/a.txt"}, headers=auth, content=b"hello"
        )
        assert put.json() == {"path": "/home/user/workspace/notes/a.txt", "size": 5}
        read = await client.get(base + "/files", params={"path": "notes/a.txt"}, headers=auth)
        assert read.content == b"hello"
        missing = await client.get(base + "/files", params={"path": "/tmp/none"}, headers=auth)
        assert missing.status_code == 404
        monkeypatch.setattr("octop.api.routers.bot_computers.MAX_FILE_BYTES", 4)
        too_large_upload = await client.put(
            base + "/files", params={"path": "large"}, headers=auth, content=b"12345"
        )
        assert too_large_upload.status_code == 413
        too_large_download = await client.get(
            base + "/files", params={"path": "notes/a.txt"}, headers=auth
        )
        assert too_large_download.status_code == 413
        outside = await client.get(base + "/files", params={"path": "/etc/passwd"}, headers=auth)
        assert outside.status_code == 403
        await client.post(base + "/takeover", headers=auth, json={"active": True})
        held = await client.post(base + "/run", headers=auth, json={"command": "ls"})
        assert held.json()["taken_over"] is True and "ls" not in provider.ran

        # One account can only register so many desktop Bots.
        from octop.infra.cloud.bot_cloud import shadows

        monkeypatch.setattr(shadows, "MAX_SHADOWS", 1)
        full = await client.put(
            "/api/octop-bot/remote-bots/01JD3Q8Z2N6W4M5X7Y9A0B1C2D:OTHER",
            headers=auth,
            json={"name": "B"},
        )
        assert full.status_code == 429
        assert full.json()["error"]["code"] == "BOT_REMOTE_BOT_LIMIT"
        # Updating one it already has still works.
        assert (
            await client.put(
                f"/api/octop-bot/remote-bots/{origin}", headers=auth, json={"name": "W"}
            )
        ).status_code == 200
        monkeypatch.setattr(shadows, "MAX_SHADOWS", 50)

        # Someone else's: invisible; their own desktop Bot of the same origin is theirs alone.
        bob = await _sign_in(client, "13800000051")
        bob_auth = {"Authorization": f"Bearer {bob['access_token']}"}
        assert (
            await client.post(base + "/run", headers=bob_auth, json={"command": "id"})
        ).status_code == 404
        theirs = await client.put(
            f"/api/octop-bot/remote-bots/{origin}", headers=bob_auth, json={"name": "Writer"}
        )
        assert theirs.json()["agent_id"] != shadow

        gone = await client.delete(f"/api/octop-bot/remote-bots/{origin}", headers=auth)
        assert gone.status_code == 204
        assert srv.services.agent_repo.get(shadow) is None
        assert (await client.get(base, headers=auth)).status_code == 404
        assert (
            await client.delete(f"/api/octop-bot/remote-bots/{origin}", headers=auth)
        ).status_code == 204


async def test_desktop_token_login_limits_ip_and_account(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    from octop.api.routers import auth_lynxce

    monkeypatch.setattr(auth_lynxce, "_token_login_ips", {})
    monkeypatch.setattr(auth_lynxce, "_token_login_accounts", {})
    async with octop_client(tmp_octop_home) as (client, _):
        await _sign_in(client, "13800000050")
        current_ip = ["ip-0"]
        monkeypatch.setattr(auth_lynxce, "_client_ip", lambda request: current_ip[0])
        for i in range(11):
            current_ip[0] = f"ip-{i}"
            response = await client.post(
                "/api/auth/lynxce/token-login", json={"access_token": _lynxce_jwt()}
            )
            assert response.status_code == (200 if i < 10 else 429)
        auth_lynxce._token_login_accounts.clear()
        current_ip[0] = "fixed-ip"
        for i in range(31):
            auth_lynxce._token_login_accounts.clear()
            response = await client.post(
                "/api/auth/lynxce/token-login", json={"access_token": _lynxce_jwt()}
            )
            assert response.status_code == (200 if i < 30 else 429)


async def test_token_login_prechecks_and_src_switch(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    from octop.infra.metrics import METRICS

    monkeypatch.setattr(auth_lynxce, "_token_login_ips", {})
    monkeypatch.setattr(auth_lynxce, "_token_login_accounts", {})
    monkeypatch.delenv("OCTOP_TOKEN_LOGIN_REQUIRE_SRC", raising=False)
    async with octop_client(tmp_octop_home) as (client, _):
        await _sign_in(client, "13800000050")
        path = "/api/auth/lynxce/token-login"
        profile_calls = upstream.counts["/api/user/profile"]
        for token in ("sk-secret", "first.second"):
            result = await client.post(path, json={"access_token": token})
            assert result.status_code == 403 and result.json()["error"]["code"] == "AUTH_FAILED"
        assert upstream.counts["/api/user/profile"] == profile_calls
        before = METRICS.snapshot()["token_login_without_src_total"]
        assert (await client.post(path, json={"access_token": _lynxce_jwt()})).status_code == 200
        assert METRICS.snapshot()["token_login_without_src_total"] == before + 1
        assert (
            await client.post(path, json={"access_token": _lynxce_jwt(client="web")})
        ).status_code == 200
        monkeypatch.setenv("OCTOP_TOKEN_LOGIN_REQUIRE_SRC", "1")
        assert (await client.post(path, json={"access_token": _lynxce_jwt()})).status_code == 403
        assert (
            await client.post(path, json={"access_token": _lynxce_jwt(src="octopbot")})
        ).status_code == 200
        assert METRICS.snapshot()["token_login_without_src_total"] == before + 2


@pytest.mark.parametrize(
    "token",
    [
        _lynxce_jwt(typ="refresh"),
        _lynxce_jwt(client="desktop"),
        _lynxce_jwt(client="mobile"),
        *[_lynxce_jwt(**{field: ""}) for field in ("appId", "appVer", "desktopVer", "mobileVer")],
        "a.a.c",
    ],
)
async def test_token_login_rejects_verified_non_web_claims(
    token: str, tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth_lynxce, "_token_login_ips", {})
    async with octop_client(tmp_octop_home) as (client, _):
        before = upstream.counts["/api/user/profile"]
        response = await client.post("/api/auth/lynxce/token-login", json={"access_token": token})
        assert response.status_code == 403 and response.json()["error"]["code"] == "AUTH_FAILED"
        assert upstream.counts["/api/user/profile"] == before + 1


async def test_fifty_shadow_limit(tmp_octop_home: Path, upstream: Upstream) -> None:
    async with octop_client(tmp_octop_home) as (client, _):
        signed = await _sign_in(client, "13800000050")
        auth = {"Authorization": f"Bearer {signed['access_token']}"}
        for i in range(51):
            response = await client.put(
                f"/api/octop-bot/remote-bots/0123456789:bot{i}",
                headers=auth,
                json={"name": "Bot"},
            )
            assert response.status_code == (200 if i < 50 else 429)


async def test_upload_stops_reading_at_limit_and_transfer_slots_are_per_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from octop.api.routers import bot_computers
    from octop.infra.errors import OctopError

    monkeypatch.setattr(bot_computers, "MAX_FILE_BYTES", 4)
    monkeypatch.setattr(bot_computers, "_owned", lambda *args: object())
    consumed: list[int] = []

    class Request:
        async def stream(self) -> Any:
            for i, chunk in enumerate((b"123", b"45", b"never read")):
                consumed.append(i)
                yield chunk

    with pytest.raises(OctopError) as exc:
        await bot_computers.write_file(
            "bot",
            Request(),
            path="file",
            user=SimpleNamespace(id=1),
            server=None,  # type: ignore[arg-type]
        )
    assert exc.value.status == 413 and consumed == [0, 1]
    for counts in (bot_computers._transfer_counts, bot_computers._command_counts):
        with bot_computers._slot(counts, 1), bot_computers._slot(counts, 1):
            with pytest.raises(OctopError) as limited, bot_computers._slot(counts, 1):
                pass
            assert limited.value.status == 429
            with bot_computers._slot(counts, 2):
                pass
