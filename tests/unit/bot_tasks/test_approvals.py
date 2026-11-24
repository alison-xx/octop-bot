"""Asking before consequential actions: allow once, always allow, deny."""

from __future__ import annotations

from typing import Any

import pytest

from octop.infra.bot_tasks import approvals


class _Settings:
    def __init__(self) -> None:
        self.rows: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.rows.get(key)

    def set(self, key: str, value: str) -> None:
        self.rows[key] = value


class _Users:
    def get(self, user_id: int) -> Any:
        return type("Row", (), {"locale": "zh"})()


def _tool(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> tuple[Any, list[Any]]:
    asked: list[Any] = []

    def fake_interrupt(payload: Any) -> Any:
        asked.append(payload)
        return {"decisions": [{"type": "respond", "message": answers.pop(0)}]}

    monkeypatch.setattr(approvals, "interrupt", fake_interrupt)
    rules = approvals.ApprovalRules(_Settings())  # type: ignore[arg-type]
    return approvals.request_approval_tool(rules, _Users(), "bot1", 7), asked


def _ask(tool: Any, target: str = "zhang@example.com") -> str:
    return str(
        tool.invoke(
            {"category": "send", "target": target, "detail": "周报已附上", "irreversible": True}
        )
    )


def test_the_card_names_the_action_and_target_and_offers_three_choices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool, asked = _tool(monkeypatch, ["允许一次"])
    assert _ask(tool).startswith("Approved.")
    request = asked[0]["action_requests"][0]
    question = request["args"]["questions"][0]
    assert "发送：zhang@example.com" in question["question"]
    assert "周报已附上" in question["question"] and "无法撤销" in question["question"]
    assert [o["label"] for o in question["options"]] == ["允许一次", "总是允许", "拒绝"]
    assert request["args"]["approval"] == {
        "category": "send",
        "target": "zhang@example.com",
        "irreversible": True,
    }


def test_always_allow_is_remembered_for_that_kind_and_target_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool, asked = _tool(monkeypatch, ["总是允许", "拒绝"])
    assert "always" in _ask(tool)
    # Same kind, same target: no card this time.
    assert "always allows" in _ask(tool) and len(asked) == 1
    # Another address is asked again; "deny" is a no.
    assert _ask(tool, "li@example.com").startswith("The user said no.")
    assert len(asked) == 2


def test_anything_else_the_user_writes_is_a_no_with_their_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool, _asked = _tool(monkeypatch, ["先别发，等我改一下"])
    result = _ask(tool)
    assert result.startswith("The user said no (先别发，等我改一下).")
    assert "do not try another way" in result
