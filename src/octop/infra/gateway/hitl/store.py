"""Pending human decisions for interactive and background turns."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal

from octop.infra.db.repos.handoffs import HandoffRepo, HandoffRow, Lookup

HitlPendingStatus = Literal["pending", "approved", "rejected", "expired"]

_DEFAULT_TTL_SECONDS = 30 * 60


def _same_pause_slot(
    existing: HitlPendingRecord,
    *,
    session_key: str,
    thread_id: str,
    resume_agent_id: str | None,
) -> bool:
    """True when *existing* occupies the slot a new pause would replace.

    Dashboard chats for one user and agent share a ``session_key``. The slot
    is that key plus the thread, so a pause in chat B does not expire chat A.
    Team members that share a room thread stay distinct via ``resume_agent_id``.
    """
    if existing.session_key != session_key or existing.status != "pending":
        return False
    if (existing.thread_id or "") != (thread_id or ""):
        return False
    if resume_agent_id:
        return existing.resume_agent_id == resume_agent_id
    return not existing.resume_agent_id


def _actions_equivalent(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
) -> bool:
    return json.dumps(left, sort_keys=True, default=str) == json.dumps(
        right, sort_keys=True, default=str
    )


@dataclass
class HitlPendingRecord:
    pending_id: str
    thread_id: str
    agent_id: str
    user_id: int
    session_key: str
    channel_type: str
    action_requests: list[dict[str, Any]]
    review_configs: list[dict[str, Any]] | None
    created_at: float
    status: HitlPendingStatus = "pending"
    ask_question_index: int = 0
    ask_answers: list[str] = field(default_factory=list)
    # Team member pauses are stored on the room thread the user is viewing.
    # Resume still targets the member agent and ``room~member`` thread.
    resume_agent_id: str | None = None
    resume_thread_id: str | None = None
    # Who opened the pause when no one was chatting (``cron:<id>``), and how long it may wait
    # for an answer instead of the store's default.
    origin: str | None = None
    ttl_seconds: float | None = None


@dataclass
class HitlPendingStore:
    """Thread-scoped pending actions. The running gateway persists them in the control DB."""

    ttl_seconds: float = _DEFAULT_TTL_SECONDS
    _records: dict[str, HitlPendingRecord] = field(default_factory=dict)
    repo: HandoffRepo | None = None
    _last_prune: float = 0

    def _find(self, field: Lookup, value: str | int) -> list[HitlPendingRecord]:
        if self.repo is None:
            return list(self._records.values())
        return [HitlPendingRecord(**json.loads(raw)) for raw in self.repo.find(field, value)]

    def _by_id(self, pending_id: str) -> HitlPendingRecord | None:
        if self.repo is None:
            return self._records.get(pending_id)
        return next(iter(self._find("pending_id", pending_id)), None)

    @staticmethod
    def _slot(record: HitlPendingRecord) -> str:
        values = [
            record.user_id,
            record.agent_id,
            record.thread_id,
            record.session_key,
            record.resume_agent_id,
        ]
        return hashlib.sha256(json.dumps(values).encode()).hexdigest()

    def _row(self, record: HitlPendingRecord, slot: str, now: float) -> HandoffRow:
        ttl = self._ttl(record)
        expires = record.created_at + ttl if ttl is not None else None
        return HandoffRow(
            slot,
            record.pending_id,
            record.user_id,
            record.agent_id,
            record.thread_id,
            record.session_key,
            record.resume_agent_id,
            record.resume_thread_id,
            record.origin,
            expires if record.status == "pending" else now,
            json.dumps(asdict(record)),
        )

    def _save(self, record: HitlPendingRecord, previous: HitlPendingRecord | None) -> bool:
        if self.repo is None:
            self._records[record.pending_id] = record
            return True
        now = time.time()
        row = self._row(record, self._slot(record), now)
        history = None
        if previous and previous.pending_id != record.pending_id:
            closed = (
                replace(previous, status="expired") if previous.status == "pending" else previous
            )
            history = self._row(closed, f"closed:{closed.pending_id}", now)
        return self.repo.save(
            row,
            json.dumps(asdict(previous)) if previous else None,
            previous_id=previous.pending_id if previous else None,
            history=history,
            notify_on_expiry=record.status == "pending"
            and (record.channel_type != "dashboard" or record.origin is not None),
            now=now,
        )

    def register(
        self,
        *,
        thread_id: str,
        agent_id: str,
        user_id: int,
        session_key: str,
        channel_type: str,
        action_requests: list[dict[str, Any]],
        review_configs: list[dict[str, Any]] | None,
        resume_agent_id: str | None = None,
        resume_thread_id: str | None = None,
        origin: str | None = None,
        ttl_seconds: float | None = None,
    ) -> HitlPendingRecord:
        self._gc()
        # A new pause replaces only the same slot. Two team members share the
        # room session, so one member's card must not expire the other's.
        # Dashboard threads also share a session key; thread_id keeps them apart.
        # The same interrupt is often projected twice; reuse that pending id
        # so an automatic resume of the first frame is not already expired.
        for existing in list(self._records.values()):
            if not _same_pause_slot(
                existing,
                session_key=session_key,
                thread_id=thread_id,
                resume_agent_id=resume_agent_id,
            ):
                continue
            if _actions_equivalent(existing.action_requests, action_requests):
                return existing
        for existing in list(self._records.values()):
            if not _same_pause_slot(
                existing,
                session_key=session_key,
                thread_id=thread_id,
                resume_agent_id=resume_agent_id,
            ):
                continue
            existing.status = "expired"
        pending_id = secrets.token_hex(2)
        while pending_id in self._records:
            pending_id = secrets.token_hex(2)
        record = HitlPendingRecord(
            pending_id=pending_id,
            thread_id=thread_id,
            agent_id=agent_id,
            user_id=user_id,
            session_key=session_key,
            channel_type=channel_type,
            action_requests=list(action_requests),
            review_configs=list(review_configs) if review_configs else None,
            created_at=time.time(),
            resume_agent_id=resume_agent_id,
            resume_thread_id=resume_thread_id,
            origin=origin,
            ttl_seconds=ttl_seconds,
        )
        if self.repo is not None:
            slot = self._slot(record)
            while True:
                previous = next(iter(self._find("slot", slot)), None)
                if (
                    previous
                    and previous.status == "pending"
                    and not self._stale(previous, time.time())
                    and _actions_equivalent(previous.action_requests, action_requests)
                ):
                    return previous
                record.pending_id = secrets.token_hex(8)
                if self._save(record, previous):
                    return record
        self._records[pending_id] = record
        return record

    def get(self, pending_id: str) -> HitlPendingRecord | None:
        self._gc()
        record = self._by_id(pending_id)
        if record is None:
            return None
        if record.status != "pending":
            return record
        if self._stale(record, time.time()):
            record.status = "expired"
            return record
        return record

    def get_pending(
        self,
        pending_id: str,
        *,
        session_key: str,
        agent_id: str,
    ) -> HitlPendingRecord | None:
        record = self.get(pending_id)
        if record is None or record.status != "pending":
            return None
        if record.session_key != session_key or record.agent_id != agent_id:
            return None
        return record

    def resolve_for_session(
        self,
        session_key: str,
        pending_id: str | None = None,
        *,
        agent_id: str | None = None,
    ) -> HitlPendingRecord | None:
        self._gc()
        if pending_id:
            record = self.get(pending_id)
            if record is None or record.session_key != session_key:
                return None
            if agent_id is not None and record.agent_id != agent_id:
                return None
            return record if record.status == "pending" else None
        latest: HitlPendingRecord | None = None
        for record in self._find("session_key", session_key):
            if record.session_key != session_key or record.status != "pending":
                continue
            if agent_id is not None and record.agent_id != agent_id:
                continue
            if self._stale(record, time.time()):
                record.status = "expired"
                continue
            if latest is None or record.created_at > latest.created_at:
                latest = record
        return latest

    def resolve_pending_for_thread(
        self,
        thread_id: str,
        *,
        agent_id: str,
        user_id: int | None = None,
        pending_id: str | None = None,
    ) -> HitlPendingRecord | None:
        """Return a pending approval for a dashboard thread, if any.

        ``pending_id`` selects that card. Without it, the newest pending card
        on the thread is returned.
        """
        self._gc()
        if pending_id:
            record = self._by_id(pending_id)
            if record is None or record.status != "pending":
                return None
            if not self._thread_pending_match(
                record,
                thread_id=thread_id,
                agent_id=agent_id,
                user_id=user_id,
            ):
                return None
            return record
        latest: HitlPendingRecord | None = None
        for record in self._find("thread_id", thread_id):
            if record.status != "pending":
                continue
            if not self._thread_pending_match(
                record,
                thread_id=thread_id,
                agent_id=agent_id,
                user_id=user_id,
            ):
                continue
            if latest is None or record.created_at > latest.created_at:
                latest = record
        return latest

    def _thread_pending_match(
        self,
        record: HitlPendingRecord,
        *,
        thread_id: str,
        agent_id: str,
        user_id: int | None,
    ) -> bool:
        if record.status != "pending":
            return False
        room_match = record.thread_id == thread_id and record.agent_id == agent_id
        member_match = bool(
            record.resume_thread_id
            and record.resume_thread_id == thread_id
            and record.resume_agent_id == agent_id
        )
        if not room_match and not member_match:
            return False
        if user_id is not None and record.user_id != user_id:
            return False
        if self._stale(record, time.time()):
            record.status = "expired"
            return False
        return True

    def list_pending_for_session(
        self,
        session_key: str,
        *,
        agent_id: str | None = None,
    ) -> list[HitlPendingRecord]:
        self._gc()
        rows = [
            r
            for r in self._find("session_key", session_key)
            if r.session_key == session_key
            and r.status == "pending"
            and not self._stale(r, time.time())
            and (agent_id is None or r.agent_id == agent_id)
        ]
        rows.sort(key=lambda r: r.created_at, reverse=True)
        return rows

    def pending_thread_ids(
        self,
        *,
        agent_id: str,
        user_id: int,
        any_user: bool = False,
    ) -> frozenset[str]:
        """Thread ids with a still-pending HITL pause for this agent.

        ``any_user`` includes pauses opened by someone else. Callers use that
        only for conversations that were shared with the current user.
        """
        self._gc()
        now = time.time()
        out: set[str] = set()
        for record in self._find("agent_id", agent_id):
            if record.status != "pending":
                continue
            if not any_user and record.user_id != user_id:
                continue
            if self._stale(record, now):
                continue
            if record.agent_id == agent_id:
                tid = (record.thread_id or "").strip()
            elif record.resume_agent_id == agent_id:
                tid = (record.resume_thread_id or "").strip()
            else:
                continue
            if tid:
                out.add(tid)
        return frozenset(out)

    def has_pending_for_agent(self, agent_id: str) -> bool:
        """Whether *agent_id* has any live pending HITL pause across all users."""
        self._gc()
        now = time.time()
        for record in self._find("agent_id", agent_id):
            if record.status != "pending":
                continue
            if self._stale(record, now):
                continue
            if record.agent_id == agent_id or record.resume_agent_id == agent_id:
                return True
        return False

    def expire_pending_for_thread(
        self,
        thread_id: str,
        *,
        agent_id: str,
        user_id: int | None = None,
    ) -> None:
        """Drop leftover dashboard pauses so history reload cannot reinject them."""
        self._gc()
        for record in self._find("thread_id", thread_id):
            if record.thread_id != thread_id or record.status != "pending":
                continue
            if record.agent_id != agent_id:
                continue
            if user_id is not None and record.user_id != user_id:
                continue
            self.mark_resolved(record.pending_id, "expired")

    def mark_resolved(
        self,
        pending_id: str,
        status: Literal["approved", "rejected", "expired"],
    ) -> bool:
        record = self._by_id(pending_id)
        if record is None or (
            status != "expired" and (record.status != "pending" or self._stale(record, time.time()))
        ):
            return False
        if self.repo is None:
            record.status = status
            return True
        return self._save(replace(record, status=status), record)

    def restore_unstarted(self, pending_id: str, expected: HitlPendingStatus) -> None:
        """Undo this claim when the resume call failed before producing any event."""
        record = self._by_id(pending_id)
        if record is None or record.status != expected or self._stale(record, time.time()):
            return
        if self.repo is None:
            record.status = "pending"
        else:
            self._save(replace(record, status="pending"), record)

    def append_ask_answer(self, pending_id: str, answer: str) -> HitlPendingRecord | None:
        """Record one IM answer and advance to the next question."""
        record = self.get(pending_id)
        if record is None or record.status != "pending":
            return None
        if self.repo is not None:
            updated = replace(
                record,
                ask_answers=[*record.ask_answers, answer],
                ask_question_index=record.ask_question_index + 1,
            )
            return updated if self._save(updated, record) else None
        record.ask_answers.append(answer)
        record.ask_question_index += 1
        return record

    def _stale(self, record: HitlPendingRecord, now: float) -> bool:
        ttl = self._ttl(record)
        return ttl is not None and now - record.created_at >= ttl

    def _ttl(self, record: HitlPendingRecord) -> float | None:
        if record.ttl_seconds is not None:
            return record.ttl_seconds
        if record.origin or record.channel_type != "dashboard":
            return 24 * 3600 if self.repo is not None else self.ttl_seconds
        if any(
            isinstance(action.get("args"), dict)
            and any(
                action["args"].get(key)
                for key in ("approval", "cloud_computer", "local_device_wait")
            )
            for action in record.action_requests
        ):
            return None
        return self.ttl_seconds

    def pending_for_user(self, user_id: int) -> list[HitlPendingRecord]:
        """Every pause still waiting for this user, newest first (the Bot client's inbox)."""
        self._gc()
        now = time.time()
        rows = [
            r
            for r in self._find("user_id", user_id)
            if r.user_id == user_id and r.status == "pending" and not self._stale(r, now)
        ]
        rows.sort(key=lambda r: r.created_at, reverse=True)
        return rows

    def pending_with_origin(self, origin: str) -> HitlPendingRecord | None:
        """The pause a background run (``cron:<id>``) left waiting for the user, if any."""
        self._gc()
        for record in self._find("origin", origin):
            if (
                record.origin == origin
                and record.status == "pending"
                and not self._stale(record, time.time())
            ):
                return record
        return None

    def _gc(self) -> None:
        now = time.time()
        if self.repo is not None:
            if now - self._last_prune >= 3600:
                self.repo.discard_older_than(now - 24 * 3600)
                self._last_prune = now
            return
        stale_ids: list[str] = []
        for pending_id, record in self._records.items():
            if record.status == "pending" and self._stale(record, now):
                record.status = "expired"
            if record.status != "pending" and now - record.created_at > self.ttl_seconds:
                stale_ids.append(pending_id)
        for pending_id in stale_ids:
            del self._records[pending_id]
