"""One active handoff slot per user, conversation and optional team member."""

from __future__ import annotations

from dataclasses import astuple, dataclass
from typing import Literal

from octop.infra.db.pool import DatabasePool

Lookup = Literal["slot", "pending_id", "agent_id", "thread_id", "session_key", "user_id", "origin"]
_FILTERS = {
    "slot": "slot = ?",
    "pending_id": "pending_id = ?",
    "user_id": "user_id = ?",
    "thread_id": "(thread_id = ? OR resume_thread_id = ?)",
    "agent_id": "(agent_id = ? OR resume_agent_id = ?)",
    "session_key": "session_key = ?",
    "origin": "origin = ?",
}


@dataclass(frozen=True)
class HandoffRow:
    slot: str
    pending_id: str
    user_id: int
    agent_id: str
    thread_id: str
    session_key: str
    resume_agent_id: str | None
    resume_thread_id: str | None
    origin: str | None
    expires_at: float | None
    payload: str


@dataclass(frozen=True)
class HandoffDeadline:
    pending_id: str
    agent_id: str
    user_id: int
    thread_id: str
    origin: str | None
    expires_at: float


class HandoffRepo:
    def __init__(self, db: DatabasePool) -> None:
        self._db = db

    def find(self, field: Lookup, value: str | int) -> list[str]:
        predicate = _FILTERS[field]
        params = (value, value) if field in {"agent_id", "thread_id"} else (value,)
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM bot_handoffs WHERE " + predicate, params
            ).fetchall()
        return [str(row["payload"]) for row in rows]

    def save(
        self,
        row: HandoffRow,
        expected: str | None,
        *,
        previous_id: str | None,
        history: HandoffRow | None,
        notify_on_expiry: bool,
        now: float,
    ) -> bool:
        insert = (
            "INSERT INTO bot_handoffs(slot,pending_id,user_id,agent_id,thread_id,session_key,"
            "resume_agent_id,resume_thread_id,origin,expires_at,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?)"
        )
        values = astuple(row)
        with self._db.transaction() as conn:
            if expected is None:
                changed = conn.execute(insert + " ON CONFLICT DO NOTHING", values)
            else:
                changed = conn.execute(
                    "UPDATE bot_handoffs SET pending_id=?,user_id=?,agent_id=?,thread_id=?,session_key=?,"
                    "resume_agent_id=?,resume_thread_id=?,origin=?,expires_at=?,payload=? "
                    "WHERE slot=? AND payload=?",
                    (*values[1:], row.slot, expected),
                )
            if changed.rowcount != 1:
                return False
            if history is not None:
                # Only the active row owns the slot. Keep the former ID and its decision
                # available to concurrent readers until the normal retention sweep.
                conn.execute(insert, astuple(history))
            if previous_id is not None:
                # Once due, an outcome survives slot reuse until the Bot has received it.
                conn.execute(
                    "DELETE FROM bot_handoff_deadlines WHERE pending_id=? AND (expires_at>? OR ?=pending_id)",
                    (previous_id, now, row.pending_id),
                )
            if notify_on_expiry and row.expires_at is not None:
                conn.execute(
                    "INSERT INTO bot_handoff_deadlines(pending_id,user_id,agent_id,thread_id,origin,expires_at,next_attempt) "
                    "VALUES(?,?,?,?,?,?,?) ON CONFLICT(pending_id) DO NOTHING",
                    (
                        row.pending_id,
                        row.user_id,
                        row.agent_id,
                        row.thread_id,
                        row.origin,
                        row.expires_at,
                        row.expires_at,
                    ),
                )
            return True

    def discard_older_than(self, cutoff: float) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM bot_handoffs WHERE expires_at <= ?", (cutoff,))

    def claim_deadline(self, now: float) -> HandoffDeadline | None:
        """Lease a due notification. A crashed worker leaves it available for retry."""
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT pending_id,agent_id,user_id,thread_id,origin,expires_at FROM bot_handoff_deadlines "
                "WHERE next_attempt<=? ORDER BY next_attempt,pending_id LIMIT 1",
                (now,),
            ).fetchone()
            if row is None:
                return None
            changed = conn.execute(
                "UPDATE bot_handoff_deadlines SET next_attempt=? WHERE pending_id=? AND next_attempt<=?",
                (now + 300, row["pending_id"], now),
            )
            return HandoffDeadline(**dict(row)) if changed.rowcount == 1 else None

    def finish_deadline(self, pending_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM bot_handoff_deadlines WHERE pending_id=?", (pending_id,))
