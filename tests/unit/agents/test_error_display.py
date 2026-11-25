"""Cloud tenants must not see unclassified startup exceptions."""

import logging

from octop.i18n.domains.agents import AGENT_START_TIMEOUT, agent_error_message
from octop.infra.agents.error_display import _log_unclassified, visible_agent_error


def test_visible_error_cloud_and_logging(monkeypatch, caplog) -> None:
    monkeypatch.setenv("OCTOP_BOT_CLOUD", "1")
    _log_unclassified.cache_clear()
    raw = "upstream failure at https://test-secret@example.invalid"
    with caplog.at_level(logging.WARNING):
        for _ in range(2):
            assert visible_agent_error("agent-test", raw, is_admin=False, locale="en") == (
                "The Bot could not start. Please try again later."
            )
    assert (
        sum(raw in record.message and "agent-test" in record.message for record in caplog.records)
        == 1
    )
    assert visible_agent_error("agent-test", raw, is_admin=True, locale="en") == raw
    assert visible_agent_error("agent-test", None, is_admin=False, locale="en") is None
    assert visible_agent_error("agent-test", AGENT_START_TIMEOUT, is_admin=False, locale="zh") == (
        agent_error_message(AGENT_START_TIMEOUT, "zh")
    )
    monkeypatch.delenv("OCTOP_BOT_CLOUD")
    assert visible_agent_error("agent-test", raw, is_admin=False, locale="en") == raw


def test_unknown_octop_key_is_not_exposed(monkeypatch) -> None:
    monkeypatch.setenv("OCTOP_BOT_CLOUD", "1")
    assert visible_agent_error(
        "agent-test", "octop:unknown-secret", is_admin=False, locale="zh"
    ) == ("Bot 启动失败，请稍后重试。")
