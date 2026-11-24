"""What a cloud tenant's agent config may hold."""

from __future__ import annotations

from octop.api.routers.chat.turn import _own_session_key
from octop.infra.cloud.bot_cloud.tenant_config import strip_tenant_input


def test_allowlist_keeps_preferences_and_switches_only() -> None:
    kept = strip_tenant_input(
        {
            "persona": "INTJ",
            "octop_bot": {"private": True, "origin": "x:y", "hidden": True},
            "plugins": {"p": {"enabled": False, "tools": {"t": True, "u": "x"}, "url": "x"}},
            "mcp_servers": ["a"],
            "memory": {"memory_enabled": True, "db_path": "/x"},
            "unknown": 1,
        }
    )
    assert kept == {
        "persona": "INTJ",
        "octop_bot": {"private": True},
        "plugins": {"p": {"enabled": False, "tools": {"t": True}}},
        "memory": {"memory_enabled": True},
    }


def test_a_turn_uses_only_its_own_session_keys() -> None:
    own = "bot1:dashboard:7:dm"
    assert _own_session_key(own, agent_id="bot1", user_id=7) == own
    assert _own_session_key("bot1:dashboard:7:topic-2", agent_id="bot1", user_id=7) == (
        "bot1:dashboard:7:topic-2"
    )
    for other in ("bot1:dashboard:8:dm", "bot2:dashboard:7:dm", "bot1:wecom:7:dm", None, ""):
        assert _own_session_key(other, agent_id="bot1", user_id=7) == own
