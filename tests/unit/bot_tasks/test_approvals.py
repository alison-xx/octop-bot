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

    def get_or_insert(self, key: str, value: str) -> str:
        return self.rows.setdefault(key, value)

    def replace_if_current(self, key: str, expected: str, value: str) -> bool:
        if self.rows.get(key) != expected:
            return False
        self.rows[key] = value
        return True


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
    tool, asked = _tool(monkeypatch, ["总是允许", *(["允许一次"] * 3), "启用规则并允许", "拒绝"])
    assert "observation started" in _ask(tool)
    for index in range(1, 4):
        assert _ask(tool).startswith("Approved.")
        question = asked[-1]["action_requests"][0]["args"]["questions"][0]
        assert f"{index}/3" in question["question"]
        assert [o["label"] for o in question["options"]] == ["允许一次", "拒绝"]
    assert "always" in _ask(tool)
    review = asked[-1]["action_requests"][0]["args"]["questions"][0]
    assert review["question"].count("UTC · 允许一次") == 3
    assert "always allows" in _ask(tool) and len(asked) == 5
    assert _ask(tool, "li@example.com").startswith("The user said no.")
    assert len(asked) == 6


def test_denial_during_observation_ends_the_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    tool, asked = _tool(monkeypatch, ["总是允许", "拒绝", "允许一次"])
    _ask(tool)
    assert _ask(tool).startswith("The user said no.")
    _ask(tool)
    assert "总是允许" in [
        o["label"] for o in asked[-1]["action_requests"][0]["args"]["questions"][0]["options"]
    ]


def test_rule_activated_elsewhere_cannot_answer_a_pending_graph_card() -> None:
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.func import entrypoint
    from langgraph.types import Command

    rules = approvals.ApprovalRules(_Settings())  # type: ignore[arg-type]

    @entrypoint(checkpointer=InMemorySaver())
    def flow(_: str) -> tuple[bool, str]:
        return approvals.ask(
            rules=rules,
            user_repo=_Users(),
            agent_id="bot",
            user_id=1,
            category="send",
            target="test",
            detail="fictional report",
        )

    config = {"configurable": {"thread_id": "sample"}}
    assert "__interrupt__" in flow.invoke("run", config)
    assert rules.update("bot", "send", "test", None, {"state": "active", "at": 5})
    resumed = flow.invoke(
        Command(resume={"decisions": [{"type": "respond", "message": "拒绝"}]}), config
    )
    assert resumed[0] is False


def test_anything_else_the_user_writes_is_a_no_with_their_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool, _asked = _tool(monkeypatch, ["先别发，等我改一下"])
    result = _ask(tool)
    assert result.startswith("The user said no (先别发，等我改一下).")
    assert "do not try another way" in result


@pytest.mark.parametrize(
    "reply", ["确认: 允许一次", "用户回答：允许一次", "用户回答：\n- 确认: 允许一次"]
)
def test_mobile_and_im_single_selections(monkeypatch: pytest.MonkeyPatch, reply: str) -> None:
    tool, _ = _tool(monkeypatch, [reply])
    assert _ask(tool).startswith("Approved.")
