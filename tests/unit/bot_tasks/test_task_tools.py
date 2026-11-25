"""The task contract: plan, evidence per criterion, and a finish gate that cannot be talked past."""

from __future__ import annotations

import json
from typing import Any

import pytest

from octop.infra.bot_tasks import tools as task_module
from octop.infra.bot_tasks.model import STALE_SECONDS
from octop.infra.bot_tasks.store import KEEP_PER_THREAD, TaskStore


class _Settings:
    def __init__(self) -> None:
        self.rows: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.rows.get(key)

    def set(self, key: str, value: str) -> None:
        self.rows[key] = value


@pytest.fixture
def kit(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], TaskStore]:
    monkeypatch.setattr(task_module, "_thread_id", lambda: "thr1")
    store = TaskStore(_Settings())  # type: ignore[arg-type]
    return {t.name: t for t in task_module.task_tools(store)}, store


def _task(result: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(result)
    return payload["task"]


def test_a_task_cannot_be_called_done_without_a_verdict_on_every_criterion(kit: Any) -> None:
    tools, store = kit
    planned = _task(
        tools["task_plan"].invoke(
            {
                "goal": "Q3 竞品价格表",
                "criteria": ["三家公司都有 Q3 价格", "币种统一为人民币"],
                "assumptions": ["价格取官网标价"],
            }
        )
    )
    assert planned["status"] == "running" and planned["budget"] == {"steps": 60, "minutes": 30}
    refused = tools["task_finish"].invoke({"summary": "做完了"})
    assert refused.startswith("Refused: criteria 1, 2 have no verdict")
    assert (
        tools["task_check"]
        .invoke({"criterion": 1, "status": "passed", "evidence": " "})
        .startswith("Refused: give the evidence")
    )
    assert (
        tools["task_check"]
        .invoke({"criterion": 3, "status": "passed", "evidence": "x"})
        .startswith("Refused: criterion must be 1 to 2")
    )
    tools["task_check"].invoke({"criterion": 1, "status": "passed", "evidence": "表格 42 行"})
    tools["task_check"].invoke({"criterion": 2, "status": "passed", "evidence": "汇率见说明表"})
    finished = json.loads(tools["task_finish"].invoke({"summary": "表格已交付"}))
    assert finished["task"]["status"] == "done"
    assert "do not repeat the checklist" in finished["note"]
    assert store.running("thr1") is None


def test_a_failed_or_skipped_criterion_finishes_as_partial(kit: Any) -> None:
    tools, _store = kit
    tools["task_plan"].invoke({"goal": "报告", "criteria": ["有折扣政策", "有来源链接"]})
    tools["task_check"].invoke({"criterion": 1, "status": "skipped", "evidence": "C 家没有公开"})
    tools["task_check"].invoke({"criterion": 2, "status": "passed", "evidence": "来源表 9 条"})
    finished = json.loads(
        tools["task_finish"].invoke({"summary": "部分完成", "open_issues": ["C 家折扣"]})
    )
    assert finished["task"]["status"] == "partial"
    assert finished["task"]["open_issues"] == ["C 家折扣"]
    assert "do not call it done" in finished["note"]


def test_revising_a_running_task_keeps_unchanged_verdicts(kit: Any) -> None:
    tools, store = kit
    first = _task(tools["task_plan"].invoke({"goal": "表", "criteria": ["A", "B"]}))
    tools["task_check"].invoke({"criterion": 1, "status": "passed", "evidence": "ok"})
    revised = _task(
        tools["task_plan"].invoke({"goal": "表", "criteria": ["A", "C"], "tier": "deep"})
    )
    assert revised["id"] == first["id"]
    assert [c["status"] for c in revised["criteria"]] == ["passed", "pending"]
    assert revised["budget"] == {"steps": 150, "minutes": 90}


def test_an_abandoned_task_is_stopped_by_the_next_plan(kit: Any) -> None:
    tools, store = kit
    old = _task(tools["task_plan"].invoke({"goal": "旧任务", "criteria": ["A"]}))
    stale = store.running("thr1")
    stale.updated_at -= STALE_SECONDS + 1
    store.save("thr1", stale)
    new = _task(tools["task_plan"].invoke({"goal": "新任务", "criteria": ["B"]}))
    assert new["id"] != old["id"]
    statuses = {t.goal: t.status for t in store.tasks("thr1")}
    assert statuses == {"旧任务": "stopped", "新任务": "running"}


def test_checks_need_a_running_task_and_bad_plans_are_refused(kit: Any) -> None:
    tools, store = kit
    assert "call task_plan first" in tools["task_check"].invoke(
        {"criterion": 1, "status": "passed", "evidence": "x"}
    )
    assert tools["task_plan"].invoke({"goal": "x", "criteria": [" "]}).startswith("Refused")
    assert store.tasks("thr1") == []


def test_a_conversation_keeps_only_its_latest_tasks() -> None:
    from octop.infra.bot_tasks.model import Budget, Task

    store = TaskStore(_Settings())  # type: ignore[arg-type]
    for i in range(KEEP_PER_THREAD + 3):
        store.save("t", Task(goal=f"g{i}", budget=Budget(steps=1, minutes=1), status="done"))
    goals = [t.goal for t in store.tasks("t")]
    assert len(goals) == KEEP_PER_THREAD and goals[-1] == f"g{KEEP_PER_THREAD + 2}"


def test_a_deep_task_waits_for_an_independent_review_after_its_latest_verdicts(
    kit: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools, store = kit
    clock = iter(range(1_000, 2_000))
    monkeypatch.setattr(task_module.time, "time", lambda: float(next(clock)))
    tools["task_plan"].invoke({"goal": "上线方案", "criteria": ["A"], "tier": "deep"})
    tools["task_check"].invoke({"criterion": 1, "status": "passed", "evidence": "ok"})
    refused = tools["task_finish"].invoke({"summary": "done"})
    assert refused.startswith("Refused: this is a deep task") and '"Review:"' in refused

    def review() -> None:
        task = store.running("thr1")
        task.reviews += 1
        task.reviewed_at = float(next(clock))
        store.save("thr1", task)

    review()
    # A verdict changed after the review: it must be reviewed again (second and last time).
    tools["task_check"].invoke({"criterion": 1, "status": "failed", "evidence": "差一项"})
    assert tools["task_finish"].invoke({"summary": "x"}).startswith("Refused: this is a deep")
    review()
    tools["task_check"].invoke({"criterion": 1, "status": "passed", "evidence": "补上了"})
    # Two reviews done: it may finish even though the last verdict came after them.
    finished = json.loads(tools["task_finish"].invoke({"summary": "完成"}))
    assert finished["task"]["status"] == "done" and finished["task"]["reviews"] == 2


def test_a_standard_task_needs_no_review(kit: Any) -> None:
    tools, _store = kit
    tools["task_plan"].invoke({"goal": "表", "criteria": ["A"]})
    tools["task_check"].invoke({"criterion": 1, "status": "passed", "evidence": "ok"})
    assert json.loads(tools["task_finish"].invoke({"summary": "ok"}))["task"]["status"] == "done"


def test_checks_sent_together_keep_every_verdict(kit: Any) -> None:
    """A model sent three task_check at once; each must land (no last-save-wins)."""
    import threading
    import time as real_time

    tools, store = kit
    tools["task_plan"].invoke({"goal": "表", "criteria": ["A", "B", "C"]})
    original = store.save

    def slow_save(thread: str, task: Any) -> Any:
        real_time.sleep(0.05)  # widen the read-modify-write window
        return original(thread, task)

    store.save = slow_save  # type: ignore[method-assign]
    workers = [
        threading.Thread(
            target=tools["task_check"].invoke,
            args=({"criterion": n, "status": "passed", "evidence": f"ok {n}"},),
        )
        for n in (1, 2, 3)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert [c.status for c in store.running("thr1").criteria] == ["passed"] * 3


def test_finish_preserves_an_unverified_delivery_as_partial(kit: Any) -> None:
    tools, _store = kit
    tools["task_plan"].invoke({"goal": "Send a report", "criteria": ["PDF opens"]})
    tools["task_check"].invoke({"criterion": 1, "status": "passed", "evidence": "Two pages"})
    task = _task(
        tools["task_finish"].invoke(
            {"summary": "Draft ready", "open_issues": ["Recipient confirmation pending"]}
        )
    )
    assert task["status"] == "partial"


def test_budget_change_needs_a_decision_and_uses_absolute_totals(
    kit: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from octop.infra.bot_tasks import approvals, budget

    tools, store = kit
    initial = _task(tools["task_plan"].invoke({"goal": "Chart", "criteria": ["Title present"]}))
    cfg = {"thread_id": "thr1"}
    monkeypatch.setattr(budget, "get_config", lambda: {"configurable": cfg})
    settings = _Settings()
    from unittest.mock import Mock

    users = Mock()
    users.get.return_value.locale = "en"
    tool = budget.task_budget_tool(store, approvals.ApprovalRules(settings), users, "bot1", 7)
    request = {"task_id": initial["id"], "steps": 70, "minutes": 30}
    task = store.running("thr1")
    task.steps_used = task.budget.steps
    store.save("thr1", task)
    choices = iter(["Deny", "Allow once"])
    cards = []

    def respond(payload: dict) -> dict:
        cards.append(payload)
        return {"decisions": [{"type": "respond", "message": next(choices)}]}

    monkeypatch.setattr(approvals, "interrupt", respond)
    cfg["octop_scheduled_turn"] = True
    assert "scheduled" in tool.invoke(request)
    assert not cards
    del cfg["octop_scheduled_turn"]
    assert "said no" in tool.invoke(request)
    assert store.running("thr1").budget.steps == 60
    assert _task(tool.invoke(request))["budget"] == {"steps": 70, "minutes": 30}
    assert _task(tool.invoke(request))["budget"]["steps"] == 70
    assert len(cards) == 2
    question = cards[-1]["action_requests"][0]["args"]["questions"][0]
    assert "60" in question["question"] and "70" in question["question"]
    assert [option["label"] for option in question["options"]] == ["Allow once", "Deny"]


def test_finishing_with_declared_issues_is_partial(kit: Any) -> None:
    tools, _ = kit
    tools["task_plan"].invoke({"goal": "Prepare the table", "criteria": ["Rows verified"]})
    tools["task_check"].invoke({"criterion": 1, "status": "passed", "evidence": "Two rows"})
    result = tools["task_finish"].invoke(
        {"summary": "Table checked", "open_issues": ["Delivery pending"]}
    )
    assert json.loads(result)["task"]["status"] == "partial"


def test_new_evidence_after_last_review_requires_a_partial_report(kit: Any) -> None:
    tools, store = kit
    tools["task_plan"].invoke(
        {"goal": "Check the table", "tier": "deep", "criteria": ["Rows checked"]}
    )
    tools["task_check"].invoke({"criterion": 1, "status": "passed", "evidence": "Two rows"})
    task = store.running("thr1")
    task.reviews = 2
    task.review_status = "passed"
    task.reviewed_at = task.checked_at
    store.save("thr1", task)
    tools["task_check"].invoke(
        {"criterion": 1, "status": "passed", "evidence": "Updated table, three rows"}
    )
    result = json.loads(tools["task_finish"].invoke({"summary": "Updated table checked"}))["task"]
    assert result["status"] == "partial" and result["review_status"] == "unverified"
    assert result["reviews"] == 2
