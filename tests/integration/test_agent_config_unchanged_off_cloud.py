"""Outside a cloud server, and for the operator on one, agent configs keep every setting."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from octop.infra.agents.manager import AgentCreateSpec
from octop.infra.users.identity import Role
from tests.support.app import octop_client

SETTINGS = {"acp": {"tool_enabled": True}, "security": {"enabled": True}, "persona": "INTJ"}


async def _stored(srv, user_id: int, workspace: Path) -> dict:
    row = await srv.app_runtime.agent_registry.create(
        AgentCreateSpec(
            user_id=user_id,
            name="Kept",
            config={**SETTINGS, "workspace_dir": str(workspace)},
        ),
        defer_bootstrap=True,
    )
    return json.loads(srv.services.agent_repo.get(row.agent_id).config_json)


async def test_self_hosted_users_keep_their_settings(tmp_octop_home: Path, tmp_path: Path) -> None:
    async with octop_client(tmp_octop_home) as (_client, srv):
        user = await srv.user_manager.create(
            username="member", password="Member-pass1!", role=Role.USER
        )
        stored = await _stored(srv, user.id, tmp_path / "ws")
        assert stored["acp"] == {"tool_enabled": True}
        assert stored["security"] == {"enabled": True}
        assert stored["workspace_dir"] == str(tmp_path / "ws")


async def test_the_operator_on_a_cloud_server_keeps_them_too(
    tmp_octop_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOP_BOT_CLOUD", "1")
    async with octop_client(tmp_octop_home) as (_client, srv):
        admin = await srv.user_manager.create(
            username="operator", password="Operator-pass1!", role=Role.ADMIN
        )
        stored = await _stored(srv, admin.id, tmp_path / "ops")
        assert stored["acp"] == {"tool_enabled": True}
        assert stored["workspace_dir"] == str(tmp_path / "ops")
