"""Bot web build: the first Lynxce sign-in claims the instance; only that account signs in later."""

import json
from collections import Counter
from pathlib import Path

import httpx
import pytest

from octop.api.routers import auth_lynxce
from octop.infra.auth import lynxce_cloud as cloud
from octop.infra.auth.lynxce_owner import owner_binding
from octop.infra.setup.completion import setup_wizard_completed
from tests.support.app import octop_client

LOGIN = "/api/auth/lynxce/login"
STATUS = "/api/auth/lynxce/status"


class Upstream:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()

    def __call__(self, req: httpx.Request) -> httpx.Response:
        assert req.url.host == "api.lynxce.cn" and req.url.scheme == "https"
        self.counts[req.url.path] += 1
        if req.url.path == "/api/auth/password-login":
            payload = json.loads(req.content)
            if payload["password"] != "test-password":
                return httpx.Response(401, json={"message": "no"})
            uid = payload["account"]
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "accessToken": f"access-{uid}",
                        "refreshToken": f"refresh-{uid}",
                        "user": {"id": "id-" + uid, "displayName": "Name " + uid},
                    },
                },
            )
        if req.url.path == "/api/auth/logout":
            return httpx.Response(200, json={"code": 0, "data": {}})
        return httpx.Response(404, json={})


@pytest.fixture
def upstream(monkeypatch: pytest.MonkeyPatch) -> Upstream:
    fake = Upstream()
    monkeypatch.setenv("OCTOP_BOT_WEB", "1")
    monkeypatch.setattr(
        cloud, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake))
    )
    monkeypatch.setattr(auth_lynxce, "_failures", {})
    return fake


async def test_first_lynxce_sign_in_claims_a_fresh_instance(
    tmp_octop_home: Path, upstream: Upstream
) -> None:
    async with octop_client(tmp_octop_home) as (client, srv):
        setup = (await client.get("/api/setup/status")).json()
        assert setup["lynxce_login"] is True
        assert setup["wizard_password_required"] is False
        assert (await client.get(STATUS)).json() == {"enabled": True, "claimed": False}

        res = await client.post(LOGIN, json={"account": "alice", "password": "test-password"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["user"]["username"] == "owner"
        assert body["user"]["role"] == "admin"
        token = body["access_token"]

        binding = owner_binding(srv.services.settings_repo)
        assert binding is not None and binding.account_id == "id-alice"
        assert setup_wizard_completed(srv.services.settings_repo)
        assert srv.services.settings_repo.get(f"octop_bot:chief:{binding.user_id}")
        # The upstream session opened for the check is closed immediately.
        assert upstream.counts["/api/auth/logout"] == 1
        # The Lynxce password and tokens are not kept.
        assert srv.services.secret_repo.get(f"lynxce.cloud.user.{binding.user_id}") is None

        me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert (await client.get(STATUS)).json() == {"enabled": True, "claimed": True}

        again = await client.post(LOGIN, json={"account": "alice", "password": "test-password"})
        assert again.status_code == 200
        assert again.json()["user"]["id"] == binding.user_id
        assert srv.user_manager.count() == 1


async def test_other_accounts_and_wrong_passwords_are_refused(
    tmp_octop_home: Path, upstream: Upstream
) -> None:
    async with octop_client(tmp_octop_home) as (client, srv):
        first = await client.post(LOGIN, json={"account": "alice", "password": "test-password"})
        assert first.status_code == 200

        other = await client.post(LOGIN, json={"account": "mallory", "password": "test-password"})
        assert other.status_code == 403
        assert other.json()["error"]["code"] == "LYNXCE_OWNER_MISMATCH"

        wrong = await client.post(LOGIN, json={"account": "alice", "password": "wrong-password"})
        assert wrong.status_code == 403
        assert wrong.json()["error"]["code"] == "AUTH_FAILED"
        assert srv.user_manager.count() == 1


async def test_repeated_failures_are_throttled(tmp_octop_home: Path, upstream: Upstream) -> None:
    async with octop_client(tmp_octop_home) as (client, _srv):
        for _ in range(5):
            res = await client.post(LOGIN, json={"account": "a", "password": "wrong-password"})
            assert res.status_code == 403
        locked = await client.post(LOGIN, json={"account": "a", "password": "test-password"})
        assert locked.json()["error"]["code"] == "LOGIN_LOCKED"


async def test_lynxce_sign_in_is_off_outside_the_bot_web_build(
    tmp_octop_home: Path, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OCTOP_BOT_WEB")
    async with octop_client(tmp_octop_home) as (client, srv):
        res = await client.post(LOGIN, json={"account": "alice", "password": "test-password"})
        assert res.status_code == 403
        assert upstream.counts["/api/auth/password-login"] == 0
        assert (await client.get("/api/setup/status")).json()["lynxce_login"] is False
        assert srv.user_manager.count() == 0


async def test_local_owner_on_the_web_build_must_choose_a_password(
    tmp_octop_home: Path, upstream: Upstream
) -> None:
    async with octop_client(tmp_octop_home) as (client, _srv):
        token = (await client.post("/api/setup/begin")).json()["wizard_token"]
        auth = {"Authorization": f"Bearer {token}"}
        missing = await client.post(
            "/api/setup/initial-admin", headers=auth, json={"username": "local"}
        )
        assert missing.status_code == 400
        created = await client.post(
            "/api/setup/initial-admin",
            headers=auth,
            json={"username": "local", "password": "Str0ng-Passw0rd!"},
        )
        assert created.status_code == 201, created.text


async def test_deleting_a_user_clears_lynxce_grants_and_bot_state(
    tmp_octop_home: Path, upstream: Upstream
) -> None:
    async with octop_client(tmp_octop_home) as (client, srv):
        res = await client.post(LOGIN, json={"account": "alice", "password": "test-password"})
        uid = res.json()["user"]["id"]
        settings, secrets = srv.services.settings_repo, srv.services.secret_repo
        for key in (f"lynxce.oauth.user.{uid}", f"lynxce.oauth.client.{uid}"):
            secrets.put(key, b"x")
        settings.set(f"octop_bot:layout:{uid}", "{}")
        settings.set(f"octop_bot:computer:{uid}:bot-1", "{}")
        settings.set(f"octop_bot:layout:{uid}1", "{}")  # another user's key survives
        srv.services.user_repo.delete(uid)
        assert secrets.get(f"lynxce.oauth.user.{uid}") is None
        assert secrets.get(f"lynxce.oauth.client.{uid}") is None
        assert settings.get(f"octop_bot:chief:{uid}") is None
        assert settings.get(f"octop_bot:layout:{uid}") is None
        assert settings.get(f"octop_bot:computer:{uid}:bot-1") is None
        assert settings.get(f"octop_bot:layout:{uid}1") == "{}"
        assert owner_binding(settings) is None
