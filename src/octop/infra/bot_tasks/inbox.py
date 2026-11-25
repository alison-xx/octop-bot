"""What is waiting for the user across their Bots: questions, approvals, takeovers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from octop_harness.builtin.tools.ask_user import ASK_USER_TOOL_NAME

if TYPE_CHECKING:
    from octop.infra.gateway.hitl.store import HitlPendingRecord, HitlPendingStore

Kind = Literal["question", "approval", "takeover", "tool"]


@dataclass(frozen=True)
class InboxItem:
    pending_id: str
    agent_id: str
    thread_id: str
    kind: Kind
    text: str
    created_at: float
    scheduled: bool


def classify_handoff(record: HitlPendingRecord) -> tuple[Kind, str]:
    first: dict[str, Any] = record.action_requests[0] if record.action_requests else {}
    raw = first.get("args")
    args: dict[str, Any] = raw if isinstance(raw, dict) else {}
    if first.get("name") != ASK_USER_TOOL_NAME:
        return "tool", str(first.get("description") or first.get("name") or "")[:300]
    questions = args.get("questions")
    text = ""
    if isinstance(questions, list) and questions and isinstance(questions[0], dict):
        text = str(questions[0].get("question") or "")
    if args.get("approval"):
        return "approval", text[:300]
    if args.get("cloud_computer"):
        return "takeover", text[:300]
    return "question", text[:300]


def inbox(store: HitlPendingStore, user_id: int) -> list[InboxItem]:
    items: list[InboxItem] = []
    for record in store.pending_for_user(user_id):
        kind, text = classify_handoff(record)
        items.append(
            InboxItem(
                pending_id=record.pending_id,
                agent_id=record.agent_id,
                thread_id=record.thread_id,
                kind=kind,
                text=text,
                created_at=record.created_at,
                scheduled=bool(record.origin and record.origin.startswith("cron:")),
            )
        )
    return items
