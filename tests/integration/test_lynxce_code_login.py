"""Lynxce one-time code sign-in: desktop cloud account and Bot web owner identity."""

import json
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import pytest

from octop.api.routers import auth_lynxce
from octop.infra.auth import lynxce_cloud as cloud
from octop.infra.auth.lynxce_owner import owner_binding
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.server import OctopServer
from tests.support.app import octop_client

CODE = "/api/auth/lynxce/code"
CODE_LOGIN = "/api/auth/lynxce/code-login"
DESKTOP = "/api/octop-bot/cloud/account"
Env = tuple[httpx.AsyncClient, OctopServer, dict[str, str], dict[str, str]]


class Upstream:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.bodies: dict[str, Any] = {}
        self.send_status = 200
        self.profiles: dict[str, dict[str, str]] = {}

    def __call__(self, req: httpx.Request) -> httpx.Response:
        assert req.url.host == "api.lynxce.cn" and req.url.scheme == "https"
        assert req.headers["X-Lynxce-Client"] == "web"
        # New accounts made through Octop Bot are recorded as coming from it (admin 来源, WeCom notice).
        assert req.headers["X-Lynxce-Signup-Site"] == "octop-bot"
        path = req.url.path
        self.counts[path] += 1
        if path == "/api/auth/logout":
            return httpx.Response(200, json={"code": 0, "data": {}})
        if path == "/api/user/profile":
            profile = self.profiles.get(req.headers.get("Authorization", ""))
            if profile is None:
                return httpx.Response(401)
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {**profile, "avatarUrl": "https://cdn.avatars.test/owner.jpg"},
                },
            )
        body = json.loads(req.content)
        self.bodies[path] = body
        if path in {"/api/auth/phone-code", "/api/auth/email-code"}:
            if self.send_status != 200:
                return httpx.Response(self.send_status, json={"error": {"code": "rate"}})
            return httpx.Response(
                200, json={"code": 0, "data": {"isRegister": True, "devCode": "654321"}}
            )
        if path in {"/api/auth/phone-login", "/api/auth/email-login"}:
            if body["code"] != "123456":
                return httpx.Response(401, json={"error": {"code": "sms_code_invalid"}})
            # Like Lynxce: a new email signs up only with a password; the code stays valid.
            if body.get("email", "").startswith("new") and len(body.get("password", "")) < 8:
                return httpx.Response(
                    400,
                    json={
                        "statusCode": 400,
                        "message": "首次注册请设置登录密码",
                        "error": {"code": "signup_password_required", "message": "x"},
                    },
                )
            uid = body.get("phone") or body["email"]
            profile = {"id": "id-" + uid, "displayName": "Name " + uid}
            self.profiles[f"Bearer access-{uid}"] = profile
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "accessToken": f"access-{uid}",
                        "refreshToken": f"refresh-{uid}",
                        "user": profile,
                    },
                },
            )
        return httpx.Response(404, json={})


@pytest.fixture
def upstream(monkeypatch: pytest.MonkeyPatch) -> Upstream:
    fake = Upstream()
    monkeypatch.setattr(
        cloud, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake))
    )
    monkeypatch.setattr(auth_lynxce, "_failures", {})
    monkeypatch.setattr(auth_lynxce, "_sends", {})
    return fake


@pytest.mark.parametrize(
    ("target", "channel"),
    [
        ("13800000000", "phone"),
        (" +86 138-0000-0000 ", "phone"),
        ("a@b.cn", "email"),
    ],
)
def test_code_target_classifies_phone_and_email(target: str, channel: str) -> None:
    assert cloud.code_target(target) == (channel, target.strip())


@pytest.mark.parametrize("target", ["", "abc", "12", "a@b", "@b.cn", "a b@c.cn"])
def test_code_target_rejects_garbage(target: str) -> None:
    with pytest.raises(OctopError) as err:
        cloud.code_target(target)
    assert err.value.code == ErrorCode.LYNXCE_CODE_TARGET_INVALID


async def test_web_code_sign_in_claims_a_fresh_instance(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOP_BOT_WEB", "1")
    async with octop_client(tmp_octop_home) as (client, srv):
        sent = await client.post(CODE, json={"target": "13800000000"})
        assert sent.status_code == 200, sent.text
        assert sent.json() == {"channel": "phone"}
        # Lynxce's development echo of the code never reaches the browser.
        assert "654321" not in sent.text
        assert upstream.bodies["/api/auth/phone-code"] == {"phone": "13800000000"}

        wrong = await client.post(CODE_LOGIN, json={"target": "13800000000", "code": "000000"})
        assert wrong.status_code == 401
        assert wrong.json()["error"]["code"] == "LYNXCE_CODE_INVALID"
        assert srv.user_manager.count() == 0

        ok = await client.post(CODE_LOGIN, json={"target": "13800000000", "code": "123456"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["user"]["username"] == "owner"
        binding = owner_binding(srv.services.settings_repo)
        assert binding is not None and binding.account_id == "id-13800000000"
        assert binding.avatar_url == "https://cdn.avatars.test/owner.jpg"
        me = await client.get(
            "/api/auth/me", headers={"Authorization": "Bearer " + ok.json()["access_token"]}
        )
        assert me.json()["avatar_url"] == binding.avatar_url
        assert upstream.counts["/api/auth/logout"] == 1

        other = await client.post(CODE_LOGIN, json={"target": "x@y.cn", "code": "123456"})
        assert other.json()["error"]["code"] == "LYNXCE_OWNER_MISMATCH"


async def test_web_email_code_uses_the_requested_language(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOP_BOT_WEB", "1")
    async with octop_client(tmp_octop_home) as (client, _srv):
        sent = await client.post(CODE, json={"target": "a@b.cn", "locale": "en"})
        assert sent.json() == {"channel": "email"}
        assert upstream.bodies["/api/auth/email-code"] == {"email": "a@b.cn", "locale": "en"}


async def test_web_code_sends_are_rate_limited_and_validated(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOP_BOT_WEB", "1")
    async with octop_client(tmp_octop_home) as (client, _srv):
        bad = await client.post(CODE, json={"target": "not a phone"})
        assert bad.status_code == 422
        assert bad.json()["error"]["code"] == "LYNXCE_CODE_TARGET_INVALID"
        assert upstream.counts["/api/auth/phone-code"] == 0
        for _ in range(4):
            assert (await client.post(CODE, json={"target": "13800000000"})).status_code == 200
        limited = await client.post(CODE, json={"target": "13800000001"})
        assert limited.status_code == 429
        assert limited.json()["error"]["code"] == "LYNXCE_CODE_THROTTLED"
        assert upstream.counts["/api/auth/phone-code"] == 4


async def test_upstream_throttle_is_reported(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOP_BOT_WEB", "1")
    upstream.send_status = 429
    async with octop_client(tmp_octop_home) as (client, _srv):
        res = await client.post(CODE, json={"target": "13800000000"})
        assert res.status_code == 429
        assert res.json()["error"]["code"] == "LYNXCE_CODE_THROTTLED"


async def test_web_code_routes_are_off_outside_the_bot_web_build(
    tmp_octop_home: Path, upstream: Upstream
) -> None:
    async with octop_client(tmp_octop_home) as (client, _srv):
        assert (await client.post(CODE, json={"target": "13800000000"})).status_code == 403
        res = await client.post(CODE_LOGIN, json={"target": "13800000000", "code": "123456"})
        assert res.status_code == 403
        assert not upstream.counts


async def test_desktop_code_sign_in_saves_the_cloud_account(
    env_admin_alice: Env, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOP_DESKTOP_SHELL", "1")
    monkeypatch.setenv("OCTOP_DESKTOP_PRODUCT", "bot")
    client, server, _admin, alice = env_admin_alice
    assert server.services is not None
    aid = server.user_manager.get("alice").id
    assert (await client.post(DESKTOP + "/code", json={"target": "a@b.cn"})).status_code == 401

    sent = await client.post(DESKTOP + "/code", headers=alice, json={"target": "a@b.cn"})
    assert sent.json() == {"channel": "email"}
    assert upstream.bodies["/api/auth/email-code"] == {"email": "a@b.cn", "locale": "zh-CN"}

    wrong = await client.post(
        DESKTOP + "/code-login", headers=alice, json={"target": "a@b.cn", "code": "999999"}
    )
    assert wrong.status_code == 401 and "999999" not in wrong.text
    assert wrong.json()["error"]["code"] == "LYNXCE_CODE_INVALID"

    ok = await client.post(
        DESKTOP + "/code-login", headers=alice, json={"target": "a@b.cn", "code": "123456"}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["account_id"] == "id-a@b.cn"
    assert cloud.cloud_status(server.services, aid).account_id == "id-a@b.cn"
    # The session is kept (unlike the web identity check).
    assert upstream.counts["/api/auth/logout"] == 0


async def test_web_new_email_sets_a_password_with_the_same_code(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOP_BOT_WEB", "1")
    login = "/api/auth/email-login"
    async with octop_client(tmp_octop_home) as (client, srv):
        first = await client.post(CODE_LOGIN, json={"target": "new@b.cn", "code": "123456"})
        assert first.status_code == 422, first.text
        assert first.json()["error"]["code"] == "LYNXCE_SIGNUP_PASSWORD_REQUIRED"
        assert "password" not in upstream.bodies[login]
        assert srv.user_manager.count() == 0

        short = await client.post(
            CODE_LOGIN, json={"target": "new@b.cn", "code": "123456", "password": " 1234567 "}
        )
        assert short.json()["error"]["code"] == "LYNXCE_SIGNUP_PASSWORD_REQUIRED"
        assert upstream.counts[login] == 1  # refused before asking Lynxce

        ok = await client.post(
            CODE_LOGIN,
            json={"target": "new@b.cn", "code": "123456", "password": " secret-pass "},
        )
        assert ok.status_code == 200, ok.text
        assert upstream.bodies[login] == {
            "email": "new@b.cn",
            "code": "123456",
            "password": "secret-pass",
        }
        assert "secret-pass" not in ok.text
        binding = owner_binding(srv.services.settings_repo)
        assert binding is not None and binding.account_id == "id-new@b.cn"


async def test_desktop_new_email_sets_a_password_with_the_same_code(
    env_admin_alice: Env, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOP_DESKTOP_SHELL", "1")
    monkeypatch.setenv("OCTOP_DESKTOP_PRODUCT", "bot")
    client, server, _admin, alice = env_admin_alice
    assert server.services is not None
    aid = server.user_manager.get("alice").id
    body = {"target": "new@b.cn", "code": "123456"}

    first = await client.post(DESKTOP + "/code-login", headers=alice, json=body)
    assert first.status_code == 422, first.text
    assert first.json()["error"]["code"] == "LYNXCE_SIGNUP_PASSWORD_REQUIRED"
    assert cloud.cloud_status(server.services, aid).account_id is None

    ok = await client.post(
        DESKTOP + "/code-login", headers=alice, json={**body, "password": "secret-pass"}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["account_id"] == "id-new@b.cn"
    assert upstream.bodies["/api/auth/email-login"]["password"] == "secret-pass"


async def test_cloud_code_session_passes_the_signup_password(upstream: Upstream) -> None:
    with pytest.raises(OctopError) as err:
        await cloud.open_code_session("new@b.cn", "123456")
    assert err.value.code == ErrorCode.LYNXCE_SIGNUP_PASSWORD_REQUIRED
    session = await cloud.open_code_session("new@b.cn", "123456", "secret-pass")
    assert session.account_id == "id-new@b.cn"
    # A phone number never needs one, and none is sent unasked.
    await cloud.open_code_session("13800000000", "123456")
    assert "password" not in upstream.bodies["/api/auth/phone-login"]


async def _post_from(
    client: httpx.AsyncClient, address: str, path: str, **body: str
) -> httpx.Response:
    transport = httpx.ASGITransport(app=client._octop_app, client=(address, 12345))
    async with httpx.AsyncClient(transport=transport, base_url=client.base_url) as caller:
        return await caller.post(path, json=body)


async def test_sign_in_lockouts_follow_real_clients_and_accounts(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Behind a proxy, one client's wrong codes must not lock everyone out; and trying one
    account from many addresses still locks it."""
    monkeypatch.setenv("OCTOP_BOT_WEB", "1")
    async with octop_client(tmp_octop_home) as (client, _srv):

        async def wrong(target: str, address: str) -> httpx.Response:
            return await _post_from(client, address, CODE_LOGIN, target=target, code="000000")

        for _ in range(5):
            assert (await wrong("13800000001", "203.0.113.1")).status_code == 401
        locked = await wrong("13800000002", "203.0.113.1")
        assert locked.status_code == 429 and locked.json()["error"]["code"] == "LOGIN_LOCKED"
        # Someone else, elsewhere, is not affected.
        assert (await wrong("13800000003", "203.0.113.2")).status_code == 401

        # One account tried from many addresses: locked for that account only.
        for n in range(10):
            assert (await wrong("13800000009", f"198.51.100.{n}")).status_code == 401
        account = await wrong("13800000009", "198.51.100.50")
        assert account.status_code == 429
        assert (await wrong("13800000010", "198.51.100.50")).status_code == 401


async def test_code_sends_are_limited_per_phone_too(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOP_BOT_WEB", "1")
    async with octop_client(tmp_octop_home) as (client, _srv):
        for n in range(5):
            sent = await _post_from(client, f"192.0.2.{n}", CODE, target="13800000020")
            assert sent.status_code == 200, sent.text
        flood = await _post_from(client, "192.0.2.99", CODE, target="13800000020")
        assert flood.json()["error"]["code"] == "LYNXCE_CODE_THROTTLED"
        other = await _post_from(client, "192.0.2.99", CODE, target="13800000021")
        assert other.status_code == 200


@pytest.mark.parametrize(
    "value",
    ["139 2345 6789", "+86 139-2345-6789", "86 13923456789", "0086 13923456789"],
)
def test_account_key_uses_lynxce_phone_identity(value: str) -> None:
    assert cloud.login_account_key(value) == "+8613923456789"
    assert cloud.login_account_key(" Someone@Example.COM ") == "someone@example.com"
