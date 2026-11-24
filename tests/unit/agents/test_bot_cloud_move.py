"""Desktop → Octop Bot cloud move: one desktop database, one cloud database, Lynxce faked."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from octop.config import OctopConfig
from octop.infra.agents.bot_appearance import Character, bot_appearance, set_character
from octop.infra.agents.bot_workspace import chief_key
from octop.infra.auth import lynxce_cloud
from octop.infra.bot_groups.service import create_group, list_messages
from octop.infra.cloud import move_in, move_out
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import build_shared_services
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.history.projection import message_inputs
from octop.infra.users.identity import User
from octop.infra.utils.paths import PathLayout


def _services(path):
    path.mkdir()
    pool = SqlitePool(path / "octop.db")
    run_migrations(pool)
    services = build_shared_services(db=pool, paths=PathLayout(path), config=OctopConfig())
    uid = services.user_repo.create(username="owner", role="user")
    return pool, services, User(uid, "owner", "user", "Owner")


class _Graph:
    def __init__(self) -> None:
        self.written: dict[str, list[Any]] = {}

    async def aupdate_state(self, config, values):
        self.written[config["configurable"]["thread_id"]] = values["messages"]


class _CloudRegistry:
    def __init__(self, services) -> None:
        self.services = services
        self.graph = _Graph()

    async def create(self, spec, **_):
        agent_id = (
            spec.agent_id or f"cloud{len(self.services.agent_repo.list_by_user(spec.user_id))}"
        )
        self.services.agent_repo.create(
            agent_id=agent_id,
            user_id=spec.user_id,
            name=spec.name,
            description=spec.description,
            system_prompt=spec.system_prompt,
        )
        return self.services.agent_repo.get(agent_id)

    def get_agent(self, agent_id):
        return SimpleNamespace(graph=self.graph)

    async def start(self, agent_id):
        return None


class _DesktopRegistry:
    def get_agent(self, agent_id):
        raise OctopError.localized(ErrorCode.AGENT_NOT_RUNNING)


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(lynxce_cloud, "_enabled", lambda: True)
    local_pool, local, me = _services(tmp_path / "desktop")
    cloud_pool, cloud, tenant = _services(tmp_path / "cloud")

    # Desktop: Chief, an architect with a look and a chat, a group with a timeline, notes.
    local.agent_repo.create(agent_id="LOCALCHIEF", user_id=me.id, name="Chief")
    local.settings_repo.set(chief_key(me.id), "LOCALCHIEF")
    local.agent_repo.create(
        agent_id="ARCH01", user_id=me.id, name="架构师", system_prompt="你是架构师"
    )
    set_character(
        local.settings_repo,
        local.agent_repo.get("ARCH01"),
        "LOCALCHIEF",
        Character(shape="orb", color="blue"),
    )
    registry = ThreadRegistry(session_repo=local.session_repo, thread_repo=local.thread_repo)
    chat = registry.create_thread(
        agent_id="ARCH01",
        user_id=me.id,
        channel_type="dashboard",
        session_key="dash",
        title="选型",
        last_active=1700000000,
    )
    local.thread_message_repo.append_if_ready(
        chat,
        message_inputs([HumanMessage("用什么数据库", id="h1"), AIMessage("PostgreSQL", id="a1")]),
    )
    group = create_group(
        local, me.id, name="软件研发组", admin_id="LOCALCHIEF", member_ids=["ARCH01"]
    )
    local.repos.bot_group_repo.import_messages(
        group.group_id,
        [
            {
                "request_id": "r1",
                "slot": "user",
                "role": "user",
                "agent_id": None,
                "text": "开工",
                "created_at": 1700000100,
            },
            {
                "request_id": "r1",
                "slot": "reply:ARCH01",
                "role": "assistant",
                "agent_id": "ARCH01",
                "text": "方案如下",
                "created_at": 1700000200,
            },
        ],
    )
    local.repos.bot_group_repo.set_memory(group.group_id, me.id, "用 Python")
    local.settings_repo.set(f"octop_bot:memory:{me.id}", "团队偏好简洁")
    lynxce_cloud._save(
        local, me.id, lynxce_cloud._Grant("lx1", "Alison", "b1", "access", "refresh-1", "")
    )

    cloud_registry = _CloudRegistry(cloud)
    cloud.settings_repo.set(chief_key(tenant.id), "CLOUDCHIEF")
    cloud.agent_repo.create(agent_id="CLOUDCHIEF", user_id=tenant.id, name="Chief")
    cloud_threads = ThreadRegistry(session_repo=cloud.session_repo, thread_repo=cloud.thread_repo)
    seen: list[str] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        seen.append(request.url.path)
        path = request.url.path
        if path == "/api/auth/lynxce/session-login":
            assert body["refresh_token"] == "refresh-1"
            return httpx.Response(200, json={"access_token": "cloud-jwt"})
        assert request.headers["authorization"] == "Bearer cloud-jwt"
        if path == "/api/octop-bot/move-in/bots":
            out = await move_in.move_bot(cloud, cloud_registry, tenant, move_in.MovedBot(**body))
        elif path == "/api/octop-bot/move-in/threads":
            out = await move_in.move_thread(
                cloud, cloud_registry, cloud_threads, tenant, move_in.MovedThread(**body)
            )
        elif path == "/api/octop-bot/move-in/groups":
            out = move_in.move_group(cloud, tenant, move_in.MovedGroup(**body))
        elif path == "/api/octop-bot/move-in/notes":
            move_in.move_notes(cloud, tenant, move_in.MovedNotes(**body))
            return httpx.Response(204)
        else:
            return httpx.Response(404)
        return httpx.Response(200, json=out.model_dump())

    def client(base: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=base, transport=httpx.MockTransport(handle))

    async def move() -> move_out.MoveStatus:
        move_out._runs.clear()
        move_out.start_move(
            local, _DesktopRegistry(), me.id, "https://cloud.test", "zh", client=client
        )
        await move_out._runs[me.id].task
        return move_out.move_status(me.id)

    yield SimpleNamespace(
        local=local,
        me=me,
        cloud=cloud,
        tenant=tenant,
        graph=cloud_registry.graph,
        move=move,
        seen=seen,
    )
    local_pool.close()
    cloud_pool.close()


@pytest.mark.asyncio
async def test_move_hands_over_sign_in_and_sends_bots_chats_groups_and_notes(world):
    status = await world.move()
    assert status.state == "done", status
    assert status.access_token == "cloud-jwt"
    assert (status.done, status.total) == (5, 5)
    # The cloud now holds the Lynxce session; the desktop no longer does.
    assert lynxce_cloud._load(world.local, world.me.id) is None

    cloud, tenant = world.cloud, world.tenant
    bots = {row.name: row for row in cloud.agent_repo.list_by_user(tenant.id)}
    assert set(bots) == {"Chief", "架构师"}
    arch = bots["架构师"]
    assert arch.system_prompt == "你是架构师"
    look = bot_appearance(cloud.settings_repo, arch, "CLOUDCHIEF")
    assert (look.shape, look.color) == ("orb", "blue")

    [thread] = cloud.thread_repo.list_by_agent_user(agent_id=arch.agent_id, user_id=tenant.id)
    assert (thread.title, thread.last_active, thread.channel_type) == (
        "选型",
        1700000000,
        "dashboard",
    )
    assert [m.content for m in world.graph.written[thread.thread_id]] == [
        "用什么数据库",
        "PostgreSQL",
    ]
    rows, _ = cloud.thread_message_repo.page(thread.thread_id, limit=10)
    assert len(rows) == 2

    [group] = cloud.repos.bot_group_repo.list_by_owner(tenant.id)
    assert group["name"] == "软件研发组"
    assert group["admin_id"] == "CLOUDCHIEF"
    assert json.loads(group["member_ids"]) == ["CLOUDCHIEF", arch.agent_id]
    assert group["memory"] == "用 Python"
    timeline = list_messages(cloud, tenant.id, group["group_id"])
    assert [(m.role, m.agent_id, m.text) for m in timeline] == [
        ("user", None, "开工"),
        ("assistant", arch.agent_id, "方案如下"),
    ]
    assert cloud.settings_repo.get(f"octop_bot:memory:{tenant.id}") == "团队偏好简洁"


@pytest.mark.asyncio
async def test_moving_again_adds_nothing_twice(world):
    assert (await world.move()).state == "done"
    # Signed in locally again (e.g. after switching back): the same move runs again.
    lynxce_cloud._save(
        world.local, world.me.id, lynxce_cloud._Grant("lx1", "Alison", "b2", "a", "refresh-1", "")
    )
    assert (await world.move()).state == "done"
    cloud, tenant = world.cloud, world.tenant
    assert len(cloud.agent_repo.list_by_user(tenant.id)) == 2
    assert len(cloud.repos.bot_group_repo.list_by_owner(tenant.id)) == 1
    arch = next(r for r in cloud.agent_repo.list_by_user(tenant.id) if r.name == "架构师")
    assert len(cloud.thread_repo.list_by_agent_user(agent_id=arch.agent_id, user_id=tenant.id)) == 1
    assert cloud.settings_repo.get(f"octop_bot:memory:{tenant.id}") == "团队偏好简洁"


@pytest.mark.asyncio
async def test_move_without_a_lynxce_sign_in_fails_and_sends_nothing(world):
    world.local.secret_repo.delete(lynxce_cloud._key(world.me.id))
    status = await world.move()
    assert status.state == "failed"
    assert status.error_code == ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED.value
    assert world.seen == []


@pytest.mark.asyncio
async def test_cloud_renews_a_handed_over_session_before_keeping_it(monkeypatch):
    calls = []

    async def send(method, path, *, bearer=None, json=None, **_):
        calls.append((method, path, bearer, json))
        if path == "/api/auth/refresh":
            return {"accessToken": "fresh", "refreshToken": "rotated"}
        return {"id": "lx1", "nickname": "Alison"}

    monkeypatch.setattr(lynxce_cloud, "_send", send)
    session = await lynxce_cloud.open_refresh_session("refresh-1")
    assert (session.account_id, session.display_name) == ("lx1", "Alison")
    assert (session.access_token, session.refresh_token) == ("fresh", "rotated")
    assert calls == [
        ("POST", "/api/auth/refresh", None, {"refreshToken": "refresh-1"}),
        ("GET", "/api/user/profile", "fresh", None),
    ]

    async def refused(*_a, **_k):
        raise lynxce_cloud._UpstreamFailure(401)

    monkeypatch.setattr(lynxce_cloud, "_send", refused)
    with pytest.raises(OctopError) as exc:
        await lynxce_cloud.open_refresh_session("stolen")
    assert exc.value.code == ErrorCode.AUTH_FAILED


@pytest.mark.asyncio
async def test_an_expired_cloud_sign_in_is_handed_over_again(world, monkeypatch):
    run = move_out._runs.setdefault(world.me.id, move_out._Run())
    run.token = "expired"
    move_out.start_move(world.local, _DesktopRegistry(), world.me.id, "https://cloud.test", "zh")
    # The default client cannot reach the test cloud; only the token reset matters here.
    monkeypatch.setattr(move_out._Cloud, "post", _refuse)
    await run.task
    assert run.status.error_code == ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED.value
    assert run.token is None


async def _refuse(*_a, **_k):
    raise OctopError.localized(ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED)


@pytest.mark.asyncio
async def test_a_private_same_name_bot_does_not_block_the_group(world):
    cloud, tenant = world.cloud, world.tenant
    cloud.agent_repo.create(
        agent_id="CLOUDARCH",
        user_id=tenant.id,
        name="架构师",
        config_json=json.dumps({"octop_bot": {"private": True}}),
    )
    status = await world.move()
    assert status.state == "done", status
    [group] = cloud.repos.bot_group_repo.list_by_owner(tenant.id)
    assert json.loads(group["member_ids"]) == ["CLOUDCHIEF"]
    assert [m.text for m in list_messages(cloud, tenant.id, group["group_id"])] == ["开工"]
