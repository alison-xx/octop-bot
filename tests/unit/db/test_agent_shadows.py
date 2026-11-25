"""Shadow Bots (a desktop Bot's stand-in that only owns a cloud computer) stay out of lists."""

from __future__ import annotations

from pathlib import Path

import pytest

from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.agents import SHADOW, AgentRepo
from octop.infra.db.repos.users import UserRepo


@pytest.fixture
def repo(tmp_path: Path) -> AgentRepo:
    pool = SqlitePool(tmp_path / "octop.db")
    run_migrations(pool)
    UserRepo(pool).create(username="u1", password_hash="h", role="user")
    agents = AgentRepo(pool)
    agents.create(agent_id="bot", user_id=1, name="Writer")
    agents.create(agent_id="sh", user_id=1, name="shadow:x:1", kind=SHADOW)
    return agents


def test_lists_and_counts_leave_shadows_out(repo: AgentRepo) -> None:
    assert [r.agent_id for r in repo.list_by_user(1)] == ["bot"]
    assert [r.agent_id for r in repo.list_all()] == ["bot"]
    assert [r.agent_id for r in repo.list_all(include_disabled=False)] == ["bot"]
    assert repo.count_by_user(1) == 1
    assert {r.agent_id for r in repo.list_by_user(1, include_shadows=True)} == {"bot", "sh"}
    assert [r.agent_id for r in repo.list_shadows(1)] == ["sh"]
    assert [r.agent_id for r in repo.list_shadows()] == ["sh"]


def test_a_shadow_is_still_found_by_id(repo: AgentRepo) -> None:
    row = repo.get("sh")
    assert row is not None and row.kind == SHADOW and row.user_id == 1
