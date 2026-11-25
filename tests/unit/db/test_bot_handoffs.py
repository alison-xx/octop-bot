from pathlib import Path
from typing import Any

import pytest

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.gateway.hitl.store import HitlPendingStore


@pytest.mark.parametrize("kind", ["approval", "local_device_wait"])
def test_pending_card_survives_restart_and_one_answer_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    from octop.infra.gateway.hitl import store as hitl

    now = 100_000.0
    monkeypatch.setattr(hitl.time, "time", lambda: now)
    db_path = tmp_path / "control.db"
    pool = SqlitePool(db_path)
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    user = repos.user_repo.create(username="test-owner", role="user")
    repos.agent_repo.create(agent_id="test-bot", user_id=user, name="Sample")
    store = HitlPendingStore(repo=repos.handoff_repo)
    params: dict[str, Any] = {
        "thread_id": "chat",
        "agent_id": "test-bot",
        "user_id": user,
        "session_key": "owner-chat",
        "channel_type": "dashboard",
        "action_requests": [{"name": "ask_user_question", "args": {kind: True}}],
        "review_configs": None,
    }
    card = store.register(**params)
    pool.close()
    now += 2 * 86400
    pool = SqlitePool(db_path)
    restored = HitlPendingStore(repo=RepoBundle.from_pool(pool).handoff_repo)
    assert restored.register(**params).pending_id == card.pending_id
    assert [r.pending_id for r in restored.pending_for_user(user)] == [card.pending_id]
    assert restored.mark_resolved(card.pending_id, "rejected")
    assert not restored.mark_resolved(card.pending_id, "approved")
    assert restored.pending_for_user(user) == []
    background = restored.register(**params, origin="cron:daily", ttl_seconds=86400)
    previous = restored.get(card.pending_id)
    assert previous and previous.status == "rejected"
    assert {r.pending_id for r in restored.pending_for_user(user)} == {background.pending_id}
    now += 86399
    assert restored.pending_with_origin("cron:daily") == background
    now += 1
    assert restored.pending_with_origin("cron:daily") is None
    assert not restored.mark_resolved(background.pending_id, "approved")
    pool.close()


async def test_expired_scheduled_card_reaches_its_checkpoint_once_after_slot_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock, Mock

    from octop.infra.cron import delivery

    now = 100_000.0
    monkeypatch.setattr(delivery.time, "time", lambda: now)
    pool = SqlitePool(tmp_path / "deadlines.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    user = repos.user_repo.create(username="tester", role="user")
    agent, thread, session, cron = "sample", "chat", "session", "daily"
    repos.agent_repo.create(agent_id=agent, user_id=user, name="Sample")
    repos.thread_repo.insert(
        thread_id=thread,
        user_id=user,
        agent_id=agent,
        channel_type="dashboard",
        session_key=session,
    )
    repos.cron_repo.create(
        cron_id=cron,
        agent_id=agent,
        user_id=user,
        trigger="interval:3600",
        prompt="review",
        session_key=session,
    )
    repos.cron_repo.set_run_status(cron, ts=int(now), status="waiting")
    store = HitlPendingStore(repo=repos.handoff_repo)
    params = {
        "agent_id": agent,
        "thread_id": thread,
        "session_key": session,
        "user_id": user,
        "channel_type": "dashboard",
        "review_configs": None,
        "origin": "cron:daily",
        "ttl_seconds": 86400,
    }
    initial = store.register(
        **params, action_requests=[{"name": "ask_user_question", "args": {"approval": True}}]
    )
    now += 86400
    # A new run can reuse the thread before the reconciliation tick.
    later = store.register(
        **params, action_requests=[{"name": "ask_user_question", "args": {"approval": True}}]
    )
    assert later.pending_id != initial.pending_id

    harness = Mock()
    harness.aappend_messages = AsyncMock(side_effect=lambda _, messages: messages)
    manager = Mock()
    manager.get_agent.return_value = harness
    service = delivery.CronDeliveryService(gateway=Mock(), agent_manager=manager, repos=repos)
    await service.publish_expirations()
    await service.publish_expirations()
    harness.aappend_messages.assert_awaited_once()
    restored_thread, messages = harness.aappend_messages.await_args.args
    assert restored_thread == thread and messages[0].id == "handoff-timeout:" + initial.pending_id
    assert messages[0].additional_kwargs["octop_task_outcome"] == "expired"
    assert repos.cron_repo.get(cron).last_status == "waiting"
    assert store.get(later.pending_id).status == "pending"
    assert store.mark_resolved(later.pending_id, "approved")
    now += 86400
    assert repos.handoff_repo.claim_deadline(now) is None
    final = store.register(
        **params, action_requests=[{"name": "ask_user_question", "args": {"approval": True}}]
    )
    now += 86400
    await service.publish_expirations()
    assert repos.cron_repo.get(cron).last_status == "expired"
    assert (
        harness.aappend_messages.await_args.args[1][0].id == "handoff-timeout:" + final.pending_id
    )
    pool.close()


async def test_im_timeout_retries_offline_checkpoint_without_running_a_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock, Mock

    from octop.infra.cron import delivery

    now = 100_000.0
    monkeypatch.setattr(delivery.time, "time", lambda: now)
    pool = SqlitePool(tmp_path / "im.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    user = repos.user_repo.create(username="owner", role="user")
    repos.agent_repo.create(agent_id="sample", user_id=user, name="Sample")
    repos.thread_repo.insert(
        thread_id="im", user_id=user, agent_id="sample", channel_type="telegram", session_key="chat"
    )
    card = HitlPendingStore(repo=repos.handoff_repo).register(
        thread_id="im",
        agent_id="sample",
        user_id=user,
        session_key="chat",
        channel_type="telegram",
        action_requests=[{"name": "ask_user_question"}],
        review_configs=None,
    )
    harness = Mock()
    harness.aappend_messages = AsyncMock(side_effect=lambda _, messages: messages)
    manager = Mock()
    manager.get_agent.side_effect = [RuntimeError("offline"), harness]
    service = delivery.CronDeliveryService(gateway=Mock(), agent_manager=manager, repos=repos)
    now += 86400
    await service.publish_expirations()
    await service.publish_expirations()
    assert manager.get_agent.call_count == 1
    now += 300
    await service.publish_expirations()
    await service.publish_expirations()
    harness.aappend_messages.assert_awaited_once()
    thread_id, messages = harness.aappend_messages.await_args.args
    assert thread_id == "im"
    assert messages[0].id == "handoff-timeout:" + card.pending_id
    assert repos.handoff_repo.claim_deadline(now) is None
    pool.close()


def test_session_schema_upgrades_to_handoffs_without_changing_login_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from octop.infra.db import migrate

    migrations = migrate._discover()
    pool = SqlitePool(tmp_path / "upgrade.db")
    with monkeypatch.context() as before_handoffs:
        before_handoffs.setattr(
            migrate, "_discover", lambda *args: [(n, p) for n, p in migrations if n <= 28]
        )
        run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    owner = repos.user_repo.create(username="upgrade-owner", role="user")
    with pool.connect() as conn:
        assert conn.execute("SELECT version FROM _schema_version").fetchone()[0] == 28
        conn.execute("UPDATE users SET session_version = 3 WHERE id = ?", (owner,))
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='bot_handoffs'").fetchone()
    run_migrations(pool)
    run_migrations(pool)
    with pool.connect() as conn:
        assert (
            conn.execute("SELECT session_version FROM users WHERE id = ?", (owner,)).fetchone()[0]
            == 3
        )
        assert conn.execute("SELECT COUNT(*) FROM bot_handoffs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM bot_handoff_deadlines").fetchone()[0] == 0
    pool.close()


def test_handoff_tables_repair_a_restored_database_at_current_version(tmp_path: Path) -> None:
    pool = SqlitePool(tmp_path / "restored.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    owner = repos.user_repo.create(username="restore-owner", role="user")
    with pool.connect() as conn:
        conn.execute("DROP TABLE bot_handoff_deadlines")
        conn.execute("UPDATE users SET session_version = 4 WHERE id = ?", (owner,))
    run_migrations(pool)
    with pool.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM bot_handoff_deadlines").fetchone()[0] == 0
        assert (
            conn.execute("SELECT session_version FROM users WHERE id = ?", (owner,)).fetchone()[0]
            == 4
        )
    pool.close()
