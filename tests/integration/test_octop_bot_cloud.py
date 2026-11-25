"""Octop Bot cloud (OCTOP_BOT_CLOUD): every Lynxce account gets its own account and model key."""

import asyncio
import json
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
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
        self.login_fields: dict[str, Any] = {}

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
        if path in {"/api/auth/phone-login", "/api/auth/password-login", "/api/auth/refresh"}:
            payload = json.loads(req.content)
            if path == "/api/auth/phone-login" and payload["code"] != "123456":
                return httpx.Response(401, json={"message": "bad code"})
            uid = payload.get("phone", payload.get("account", "13800000001"))
            data: dict[str, Any] = {
                "accessToken": f"access-{uid}",
                "refreshToken": f"refresh-{uid}",
                **self.login_fields,
            }
            if path != "/api/auth/refresh":
                data["user"] = {"id": "lx-" + uid, "displayName": "User " + uid}
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": data,
                },
            )
        if path == "/api/user/profile":
            return httpx.Response(200, json={"code": 0, "data": {"id": "lx-13800000001"}})
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


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (CODE_LOGIN, {"target": "13800000001", "code": "123456"}),
        ("/api/auth/lynxce/login", {"account": "13800000001", "password": "test-password"}),
        ("/api/auth/lynxce/session-login", {"refresh_token": "test-refresh"}),
    ],
)
@pytest.mark.parametrize(
    ("upstream_fields", "expected"),
    [
        (
            {
                "isNewUser": True,
                "signupGrant": {"credits": 100.5, "expiresAt": "2027-01-01T00:00:00Z"},
            },
            {
                "isNewUser": True,
                "signupGrant": {"credits": 100.5, "expiresAt": "2027-01-01T00:00:00Z"},
            },
        ),
        ({"isNewUser": False, "signupGrant": None}, {"isNewUser": False, "signupGrant": None}),
        (
            {"isNewUser": True, "signupGrant": {"credits": 50, "expiresAt": None}},
            {"isNewUser": True, "signupGrant": {"credits": 50, "expiresAt": None}},
        ),
        ({}, {}),
        ({"isNewUser": "true", "signupGrant": {"credits": True, "expiresAt": "x"}}, {}),
        ({"isNewUser": 1, "signupGrant": {"credits": 10, "expiresAt": 123}}, {}),
        ({"isNewUser": False, "signupGrant": "invalid"}, {"isNewUser": False}),
        (
            {"isNewUser": True, "signupGrant": {"credits": -1, "expiresAt": None}},
            {"isNewUser": True},
        ),
        (
            {"isNewUser": True, "signupGrant": {"credits": 5, "expiresAt": "x" * 65}},
            {"isNewUser": True},
        ),
        (
            {"isNewUser": None, "signupGrant": {"credits": 0, "expiresAt": "x", "other": "hidden"}},
            {"signupGrant": {"credits": 0, "expiresAt": "x"}},
        ),
    ],
)
async def test_cloud_login_signup_fields(
    tmp_octop_home: Path,
    upstream: Upstream,
    path: str,
    body: dict[str, Any],
    upstream_fields: dict[str, Any],
    expected: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Session hand-over is off on the cloud unless switched on.
    monkeypatch.setenv("OCTOP_BOT_SESSION_LOGIN", "1")
    upstream.login_fields = {**upstream_fields, "otherUpstreamField": "hidden"}
    async with octop_client(tmp_octop_home) as (client, srv):
        response = await client.post(path, json=body)
        assert response.status_code == 200, response.text
        result = response.json()
        assert {k: result[k] for k in ("isNewUser", "signupGrant") if k in result} == expected
        assert "otherUpstreamField" not in result
        stored = cloud._load(srv.services, result["user"]["id"])
        assert stored is not None and stored.login_fields == {}


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


async def test_three_cloud_sessions_share_a_paged_conversation(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket
    import time
    from types import SimpleNamespace

    from langchain_core.messages import AIMessage, HumanMessage
    from octop_harness import HarnessAgent

    from octop.infra.auth import tokens
    from tests.support.http import chat_ws_path, ws_connect

    # HTTP and WS run inside ASGI. Every external dependency uses a local
    # stand-in, so this fixture needs neither DNS nor TCP, including proxies.
    attempted_connections: list[str] = []

    def deny_network(*_args: Any, **_kwargs: Any) -> Any:
        attempted_connections.append("unconfigured connection")
        raise AssertionError("The cloud conversation fixture attempted a network connection")

    monkeypatch.setattr(socket, "getaddrinfo", deny_network)
    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket.socket, "connect_ex", deny_network)
    monkeypatch.setattr(
        cloud_files,
        "harness_spec",
        lambda spec, config=None: {
            "type": "filesystem",
            "root_dir": str(tmp_octop_home / "object-store" / spec["agent_id"]),
            "virtual_mode": True,
        },
    )

    async with octop_client(tmp_octop_home) as (client, server):
        issuance_times = iter(range(int(time.time()) - 4, int(time.time()) + 1))

        async def login(phone: str) -> dict[str, str]:
            # Access JWTs for a user issued in the same second are identical.
            with monkeypatch.context() as clock:
                clock.setattr(tokens, "time", SimpleNamespace(time=lambda: next(issuance_times)))
                session = await _sign_in(client, phone)
            return {"Authorization": f"Bearer {session['access_token']}"}

        ios, android, web = [await login("13800000001") for _ in range(3)]
        assert len({s["Authorization"] for s in (ios, android, web)}) == 3
        other_account = await login("13800000002")
        created = await client.post(
            "/api/agents", headers=ios, json={"name": "Shared conversation"}
        )
        created.raise_for_status()
        aid = created.json()["agent_id"]
        directory = f"/api/agents/{aid}/threads"
        thread_ids = []
        for auth in (ios, android):
            new = await client.post(directory, headers=auth)
            new.raise_for_status()
            thread_ids.append(new.json()["thread_id"])
        tid = thread_ids[0]
        history = f"{directory}/{tid}/history"
        (
            await client.patch(f"{directory}/{tid}", headers=ios, json={"title": "Shared topic"})
        ).raise_for_status()
        pages = [
            (await client.get(directory, headers=web, params={"limit": 1, "offset": n})).json()
            for n in (0, 1)
        ]
        assert {p[0]["thread_id"] for p in pages} == set(thread_ids)

        agent = server.app_runtime.agent_registry.get_agent(aid)
        # Cloud tenants get a per-turn account-bound harness instance.
        monkeypatch.setattr(HarnessAgent, "stream", lambda self, request: agent.stream(request))
        app = client._octop_app  # type: ignore[attr-defined]

        async def turn(auth: dict[str, str], label: str) -> None:
            agent.chunks = [
                {"type": "token", "node": "agent", "content": f"reply {label}"},
                {
                    "type": "state_update",
                    "data": {
                        "messages": [
                            HumanMessage(content=label, id=f"user-{label}"),
                            AIMessage(content=f"reply {label}", id=f"assistant-{label}"),
                        ]
                    },
                },
            ]
            async with ws_connect(app, chat_ws_path(aid, auth)) as socket:
                await socket.send_json({"type": "subscribe", "thread_id": tid})
                assert await socket.receive_json() == {
                    "type": "turn_status",
                    "thread_id": tid,
                    "active": False,
                }
                await socket.send_json({"type": "user_turn", "text": label, "thread_id": tid})
                assert (await socket.drain_turn())[-1]["type"] == "done"

        await turn(ios, "one")
        latest = (await client.get(history, headers=android, params={"limit": 1})).json()
        assert [m["id"] for m in latest["messages"]] == ["assistant-one"]
        assert latest["has_more"] and latest["next_cursor"]
        await turn(android, "two")
        older = (
            await client.get(history, headers=web, params={"cursor": latest["next_cursor"]})
        ).json()
        assert [m["id"] for m in older["messages"]] == ["user-one"]
        assert not older["has_more"] and older["next_cursor"] is None
        await turn(web, "three")

        for auth in (ios, android, web):
            synced = (await client.get(history, headers=auth)).json()
            assert synced["thread_id"] == tid and not synced["history_loading"]
            assert [m["id"] for m in synced["messages"]] == [
                f"{role}-{label}"
                for label in ("one", "two", "three")
                for role in ("user", "assistant")
            ]
            assert [m["history_seq"] for m in synced["messages"]] == list(range(1, 7))
        assert (await client.get(directory, headers=other_account)).status_code in (403, 404)
        assert (await client.get(history, headers=other_account)).status_code in (403, 404)
    assert not attempted_connections


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
        assert mine.json()["disk_gb"] == 0
        assert mine.json()["disk_paid_through"] is None
        assert mine.json()["disk_overdue_days"] == 0
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
        # A deliverable the store lacks: not found, unless a paused computer may still hold it
        # (made before deliverables were mirrored); starting the computer brings it back.
        old = {"path": "/generated/old.md"}
        gone = await client.head(base + "/workspace/download", params=old, headers=auth)
        assert gone.status_code == 404
        manager = computers.current_manager()
        assert manager is not None
        paused = manager.record(aid, signed["user"]["id"])
        paused.instance_id = "ins-old"
        manager._save(paused)
        kept = await client.get(base + "/workspace/download", params=old, headers=auth)
        assert kept.status_code == 409
        assert kept.json()["error"]["code"] == "BOT_COMPUTER_OFF"
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


@pytest.mark.parametrize(
    "credits", [float("nan"), float("inf"), float("-inf"), 10**400, 10**12 + 1]
)
def test_signup_grant_credits_must_be_finite(credits: float) -> None:
    from octop.infra.auth import lynxce_cloud

    fields = lynxce_cloud._login_fields(
        {"isNewUser": True, "signupGrant": {"credits": credits, "expiresAt": None}}
    )
    assert fields == {"isNewUser": True}


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
