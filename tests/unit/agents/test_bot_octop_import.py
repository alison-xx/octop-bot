"""One-click import of an Octop install (``~/.octop``) into the Octop Bot desktop app."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from octop.config import OctopConfig
from octop.infra.agents import bot_octop_import as octop_import
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import build_shared_services
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.paths import PathLayout


def _services(root: Path):
    root.mkdir(parents=True)
    pool = SqlitePool(root / "octop.db")
    run_migrations(pool)
    return pool, build_shared_services(db=pool, paths=PathLayout(root), config=OctopConfig())


class _Registry:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.provider_changes: list[str | None] = []

    def get_agent(self, agent_id: str):
        raise OctopError.localized(ErrorCode.AGENT_NOT_RUNNING)

    async def start(self, agent_id: str) -> None:
        self.started.append(agent_id)

    async def on_provider_changed(self, *, provider_name: str | None = None) -> None:
        self.provider_changes.append(provider_name)


@pytest.fixture
def world(tmp_path):
    """An Octop install with one assistant and a chat; a Bot app with its own user."""
    user_home = tmp_path / "home"
    source_root = user_home / ".octop"
    source_pool, source = _services(source_root)
    source.user_repo.create(username="guest", role="user")
    owner = source.user_repo.create(username="admin", role="admin")
    source.provider_repo.create(
        name="deepseek",
        kind="openai",
        base_url="https://api.deepseek.com/v1",
        api_key="sk-secret",
        models_json='[{"id": "deepseek-chat"}]',
    )
    workspace = source_root / "agents" / "A1"
    (workspace / ".octop").mkdir(parents=True)
    (workspace / "SOUL.md").write_text("I write.", encoding="utf-8")
    memory = sqlite3.connect(workspace / ".octop" / "memory.sqlite")
    memory.execute("PRAGMA journal_mode = WAL")
    memory.execute("CREATE TABLE checkpoints (thread_id TEXT)")
    memory.execute("INSERT INTO checkpoints VALUES ('thr_1')")
    memory.commit()  # left open: the row lives only in the -wal file
    source.agent_repo.create(
        agent_id="A1",
        user_id=owner,
        name="Writer",
        default_model="deepseek/deepseek-chat",
        config_json=json.dumps({"workspace_dir": str(workspace)}),
        skill_package_ids='["pkg"]',
    )
    source.agent_repo.create(agent_id="G1", user_id=1, name="Guest bot")
    with source_pool.transaction() as conn:
        conn.execute(
            "INSERT INTO threads(thread_id, agent_id, user_id, channel_type, session_key, "
            "title, last_active, created_at) VALUES ('thr_1', 'A1', ?, 'dashboard', "
            "'A1:dashboard:' || ? || ':dm', 'Draft', 5, 5)",
            (owner, owner),
        )
        conn.execute(
            "INSERT INTO thread_messages(thread_id, seq, message_id, role, message_json, "
            "created_at) VALUES ('thr_1', 1, 'm1', 'user', '{\"content\": \"hi\"}', 5)"
        )
        conn.execute(
            "INSERT INTO sessions(session_key, agent_id, user_id, channel_type, thread_id, "
            "updated_at) VALUES ('A1:dashboard:' || ? || ':dm', 'A1', ?, 'dashboard', "
            "'thr_1', 5)",
            (owner, owner),
        )
        conn.execute(
            "INSERT INTO channels(channel_id, agent_id, user_id, kind, name, config_json, "
            "enabled, created_at, updated_at) VALUES ('ch1', 'A1', ?, 'feishu', 'Feishu', "
            '\'{"app_id": "x", "enabled": true}\', 1, 5, 5)',
            (owner,),
        )
        conn.execute(
            "INSERT INTO cron_jobs(cron_id, agent_id, user_id, schedule_spec, prompt, "
            "session_key, enabled, created_at, updated_at) VALUES ('c1', 'A1', ?, "
            "'cron:0 9 * * *', 'daily', 'A1:dashboard:' || ? || ':dm', 1, 5, 5)",
            (owner, owner),
        )
    bot_pool, bot = _services(tmp_path / "bot")
    me = bot.user_repo.create(username="local", role="admin")
    bot.agent_repo.create(agent_id="B1", user_id=me, name="Writer")
    yield user_home, source_root, source, bot, me
    memory.close()


def test_finds_octop_only_when_installed_and_not_this_app(tmp_path, world):
    user_home, source_root, _, bot, _ = world
    assert octop_import.find_octop_home(bot.paths.root, user_home) == source_root
    assert octop_import.find_octop_home(source_root, user_home) is None
    assert octop_import.find_octop_home(bot.paths.root, tmp_path / "nobody") is None


def test_preview_lists_the_owners_assistants_and_new_providers(world):
    _, source_root, _, bot, _ = world
    found = octop_import.preview(bot, source_root)
    assert [(a.agent_id, a.name, a.threads, a.exists) for a in found.agents] == [
        ("A1", "Writer", 1, False)
    ]
    assert found.providers == ["deepseek"]


async def test_import_copies_assistant_chats_and_keys(world):
    _, source_root, source, bot, me = world
    registry = _Registry()
    report = await octop_import.import_octop(bot, registry, source_root, me)

    assert report.providers == ["deepseek"]
    assert [(a.agent_id, a.status, a.threads, a.channels, a.cron_jobs) for a in report.agents] == [
        ("A1", "imported", 1, 1, 1)
    ]
    assert registry.provider_changes == ["deepseek"]
    assert registry.started == ["A1"]

    # The key is readable here, sealed with this app's own key.
    provider = bot.provider_repo.get_by_name("deepseek")
    assert provider is not None and provider.api_key == "sk-secret"

    agent = bot.agent_repo.get("A1")
    assert agent is not None
    assert agent.user_id == me
    assert agent.name == "Writer (Octop)"  # this app already has a "Writer"
    assert agent.default_model == "deepseek/deepseek-chat"
    assert agent.skill_package_ids in (None, [], "")
    dest = bot.paths.agent_workspace("A1")
    assert json.loads(agent.config_json or "{}")["workspace_dir"] == str(dest)
    assert (dest / "SOUL.md").read_text(encoding="utf-8") == "I write."
    with sqlite3.connect(dest / ".octop" / "memory.sqlite") as copied:
        assert copied.execute("SELECT thread_id FROM checkpoints").fetchall() == [("thr_1",)]

    with bot.db.connect() as conn:
        thread = conn.execute("SELECT user_id, session_key, title FROM threads").fetchone()
        assert tuple(thread) == (me, f"A1:dashboard:{me}:dm", "Draft")
        assert conn.execute("SELECT COUNT(*) FROM thread_messages").fetchone()[0] == 1
        session = conn.execute("SELECT user_id, session_key FROM sessions").fetchone()
        assert tuple(session) == (me, f"A1:dashboard:{me}:dm")
        channel = conn.execute("SELECT enabled, config_json FROM channels").fetchone()
        assert channel[0] == 0 and json.loads(channel[1])["enabled"] is False
        cron = conn.execute("SELECT enabled, session_key FROM cron_jobs").fetchone()
        assert tuple(cron) == (0, f"A1:dashboard:{me}:dm")

    # Octop itself is left as it was.
    assert source.agent_repo.get("A1").name == "Writer"
    assert (source_root / "agents" / "A1" / "SOUL.md").is_file()


async def test_importing_again_adds_nothing_twice(world):
    _, source_root, _, bot, me = world
    await octop_import.import_octop(bot, _Registry(), source_root, me)
    registry = _Registry()
    again = await octop_import.import_octop(bot, registry, source_root, me)
    assert [(a.status, a.reason) for a in again.agents] == [("skipped", "exists")]
    assert again.providers == []
    assert registry.started == []
    assert octop_import.preview(bot, source_root).agents[0].exists is True
    with bot.db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0] == 1


async def test_a_failed_assistant_leaves_no_folder_behind(world, monkeypatch):
    _, source_root, _, bot, me = world

    def broken(*_args, **_kwargs):
        raise sqlite3.IntegrityError("boom")

    monkeypatch.setattr(octop_import, "_insert_chats", broken)
    report = await octop_import.import_octop(bot, _Registry(), source_root, me)
    assert [(a.status, a.reason) for a in report.agents] == [("failed", "error")]
    assert bot.agent_repo.get("A1") is None
    assert not bot.paths.agent_workspace("A1").exists()
