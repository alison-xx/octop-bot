"""Projection rows used by the dashboard history API."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from octop.infra.db.pool import DatabasePool
from octop.infra.db.repos._base import DbRow, now_ts


@dataclass(frozen=True)
class ThreadMessageInput:
    message_id: str | None
    role: str
    message_json: str
    created_at: int


@dataclass(frozen=True)
class ThreadMessageRow:
    seq: int
    message_id: str | None
    role: str
    message_json: str
    created_at: int

    @classmethod
    def from_row(cls, row: DbRow) -> ThreadMessageRow:
        return cls(
            seq=int(row["seq"]),
            message_id=str(row["message_id"]) if row["message_id"] else None,
            role=str(row["role"]),
            message_json=str(row["message_json"]),
            created_at=int(row["created_at"]),
        )


@dataclass(frozen=True)
class ThreadProjectionCandidate:
    thread_id: str
    status: str


@dataclass(frozen=True)
class ThreadProjectionSummary:
    pending: int = 0
    queued: int = 0
    running: int = 0
    failed: int = 0

    @property
    def remaining(self) -> int:
        return self.pending + self.queued + self.running + self.failed


class ThreadMessageRepo:
    """Keep checkpoint-sized data out of normal dashboard history reads."""

    def __init__(self, db: DatabasePool) -> None:
        self._db = db

    def head(self, thread_id: str) -> int:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq),0) FROM thread_messages WHERE thread_id=?", (thread_id,)
            ).fetchone()
        return int(row[0])

    def search_owned(
        self, user_id: int, query: str, *, thread_id: str | None = None
    ) -> Iterator[tuple[str, str, str, ThreadMessageRow, int]]:
        """Yield candidate messages from the user's own personal conversations."""

        def pattern(value: str) -> str:
            escaped = value.lower().replace("!", "!!").replace("%", "!%").replace("_", "!_")
            return f"%{escaped}%"

        # Older/imported transcripts can serialize non-ASCII text as JSON escapes.
        plain_wire = json.dumps(query, ensure_ascii=False)[1:-1]
        escaped_wire = json.dumps(query, ensure_ascii=True)[1:-1]
        with self._db.connect() as conn:
            cursor = conn.execute(
                "SELECT t.agent_id,t.thread_id,t.title,m.seq,m.message_id,m.role,m.message_json,m.created_at,"
                "1+(SELECT COUNT(*) FROM thread_compaction_boundaries b "
                "JOIN thread_messages cut ON cut.thread_id=b.thread_id AND cut.message_id=b.message_id "
                "WHERE b.thread_id=m.thread_id AND cut.seq<=m.seq) AS part FROM threads t "
                "JOIN agents a ON a.agent_id=t.agent_id "
                "JOIN thread_messages m ON m.thread_id=t.thread_id "
                "WHERE t.user_id=? AND a.user_id=? AND a.kind<>'team' "
                "AND t.channel_type='dashboard' AND m.role IN ('human','ai','user','assistant') "
                "AND (?='' OR t.thread_id=?) "
                "AND (LOWER(COALESCE(t.title,'')) LIKE ? ESCAPE '!' "
                "OR LOWER(m.message_json) LIKE ? ESCAPE '!' "
                "OR LOWER(m.message_json) LIKE ? ESCAPE '!') "
                "ORDER BY t.last_active DESC,t.thread_id,m.seq DESC",
                (
                    user_id,
                    user_id,
                    thread_id or "",
                    thread_id or "",
                    pattern(query),
                    pattern(plain_wire),
                    pattern(escaped_wire),
                ),
            )
            while rows := cursor.fetchmany(64):
                for r in rows:
                    yield (
                        r["agent_id"],
                        r["thread_id"],
                        r["title"] or "",
                        ThreadMessageRow.from_row(r),
                        int(r["part"]),
                    )

    def anchored_message(
        self, thread_id: str, seq: int | None, message_id: str | None
    ) -> ThreadMessageRow | None:
        """Message IDs survive a legacy projection rebuild. Imported messages may only have a sequence."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT seq,message_id,role,message_json,created_at FROM thread_messages WHERE thread_id=? "
                "AND ((?<>'' AND message_id=?) OR (?='' AND seq=?))",
                (thread_id, message_id or "", message_id, message_id or "", seq),
            ).fetchone()
        return ThreadMessageRow.from_row(row) if row else None

    def record_compaction_boundaries(self, thread_id: str, message_ids: set[str]) -> None:
        with self._db.transaction() as conn:
            for message_id in message_ids:
                conn.execute(
                    "INSERT INTO thread_compaction_boundaries(thread_id,message_id) "
                    "SELECT t.thread_id,? FROM threads t WHERE t.thread_id=? AND t.channel_type='dashboard' "
                    "ON CONFLICT(thread_id,message_id) DO NOTHING",
                    (message_id, thread_id),
                )

    def latest_human_activity(self, agent_id: str) -> int | None:
        """Latest real human message timestamp (unix seconds) for *agent_id*.

        Excludes synthetic cron prompts (``cron:%``) so scheduled runs and
        proactive care messages do not distort the user-idle clock.
        """
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT MAX(tm.created_at) "
                "FROM thread_messages tm "
                "JOIN threads t ON t.thread_id = tm.thread_id "
                "WHERE t.agent_id = ? "
                "AND tm.role IN ('human', 'user') "
                "AND (tm.message_id IS NULL OR tm.message_id NOT LIKE 'cron:%')",
                (agent_id,),
            ).fetchone()
        if row is None or row[0] is None:
            return None
        ts = int(row[0])
        return ts if ts > 0 else None

    def threads_with_messages(self, thread_ids: Sequence[str]) -> set[str]:
        """Which of *thread_ids* actually have projected messages.

        The dashboard used to infer this from ``title`` / ``last_active``,
        which marks threads that were created and named but never received a
        turn as "has messages" — clicking them opened an empty conversation.
        """
        ids = [tid for tid in thread_ids if tid]
        if not ids:
            return set()
        placeholders = ",".join("?" for _ in ids)
        with self._db.connect() as conn:
            rows = conn.execute(
                f"SELECT DISTINCT thread_id FROM thread_messages "  # noqa: S608 - placeholders only
                f"WHERE thread_id IN ({placeholders})",
                tuple(ids),
            ).fetchall()
        return {str(row[0]) for row in rows}

    def range_rows(self, thread_id: str, start: int, end: int) -> list[ThreadMessageRow]:
        """Read an immutable legacy interval without triggering projection backfill."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT seq,message_id,role,message_json,created_at FROM thread_messages "
                "WHERE thread_id=? AND seq>? AND seq<=? ORDER BY seq",
                (thread_id, start, end),
            ).fetchall()
        return [ThreadMessageRow.from_row(row) for row in rows]

    def timestamp_base(self, thread_id: str, through: int, fallback: int) -> int:
        """Anchor ordered millisecond timestamps across overlapping pages of second-resolution history."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT MAX(CAST(CASE WHEN created_at>0 THEN created_at ELSE ? END AS BIGINT)*1000-seq) "
                "FROM thread_messages "
                "WHERE thread_id=? AND seq<=?",
                (fallback, thread_id, through),
            ).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def projection_status(self, thread_id: str) -> str:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT status FROM thread_history_projection WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
        return str(row["status"]) if row else "pending"

    def mark_projection(
        self,
        thread_id: str,
        status: str,
        *,
        error: str | None = None,
    ) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO thread_history_projection(thread_id, status, updated_at, error) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(thread_id) DO UPDATE SET "
                "status = excluded.status, updated_at = excluded.updated_at, error = excluded.error",
                (thread_id, status, now_ts(), error),
            )

    def migration_summary(self, *, agent_id: str, user_id: int) -> ThreadProjectionSummary:
        """Count legacy threads that still need a history projection."""
        counts = {"pending": 0, "queued": 0, "running": 0, "failed": 0}
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT COALESCE(p.status, 'pending') AS status, COUNT(*) AS total "
                "FROM threads t LEFT JOIN thread_history_projection p "
                "ON p.thread_id = t.thread_id "
                "WHERE t.agent_id = ? AND t.user_id = ? "
                "AND COALESCE(p.status, 'pending') != 'ready' "
                "GROUP BY COALESCE(p.status, 'pending')",
                (agent_id, user_id),
            ).fetchall()
        for row in rows:
            status = str(row["status"])
            if status in counts:
                counts[status] = int(row["total"])
            else:
                counts["pending"] += int(row["total"])
        return ThreadProjectionSummary(**counts)

    def migration_candidates(
        self,
        *,
        agent_id: str,
        user_id: int,
        limit: int,
        pending_dashboard_only: bool = False,
    ) -> list[ThreadProjectionCandidate]:
        """Return recent legacy threads first without reading checkpoint blobs."""
        if limit <= 0:
            return []
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT t.thread_id, COALESCE(p.status, 'pending') AS status "
                "FROM threads t LEFT JOIN thread_history_projection p "
                "ON p.thread_id = t.thread_id "
                "WHERE t.agent_id = ? AND t.user_id = ? "
                "AND COALESCE(p.status, 'pending') != 'ready' "
                "AND (?=0 OR (t.channel_type='dashboard' AND COALESCE(p.status,'pending')<>'failed')) "
                "ORDER BY t.last_active DESC, t.thread_id DESC LIMIT ?",
                (agent_id, user_id, int(pending_dashboard_only), limit),
            ).fetchall()
        return [
            ThreadProjectionCandidate(thread_id=str(row["thread_id"]), status=str(row["status"]))
            for row in rows
        ]

    def migration_active_thread_ids(self, *, agent_id: str, user_id: int) -> list[str]:
        """Persisted queued/running IDs, used to distinguish live work from restart residue."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT t.thread_id FROM threads t "
                "JOIN thread_history_projection p ON p.thread_id = t.thread_id "
                "WHERE t.agent_id = ? AND t.user_id = ? "
                "AND p.status IN ('queued', 'running')",
                (agent_id, user_id),
            ).fetchall()
        return [str(row["thread_id"]) for row in rows]

    def page(
        self,
        thread_id: str,
        *,
        limit: int,
        offset: int = 0,
    ) -> tuple[list[ThreadMessageRow], bool]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT seq, message_id, role, message_json, created_at "
                "FROM thread_messages WHERE thread_id = ? "
                "ORDER BY seq DESC LIMIT ? OFFSET ?",
                (thread_id, limit + 1, max(0, offset)),
            ).fetchall()
        has_more = len(rows) > limit
        page = [ThreadMessageRow.from_row(row) for row in rows[:limit]]
        page.reverse()
        return page, has_more

    def append_if_ready(
        self,
        thread_id: str,
        messages: Sequence[ThreadMessageInput],
    ) -> int:
        """Append one completed turn. Pending legacy threads wait for backfill."""
        if not messages:
            return 0
        inserted = 0
        with self._db.transaction() as conn:
            state = conn.execute(
                "SELECT status FROM thread_history_projection WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            if state is None or str(state["status"]) != "ready":
                return 0
            if self._db.dialect == "postgresql":
                conn.execute(
                    "SELECT thread_id FROM threads WHERE thread_id = ? FOR UPDATE",
                    (thread_id,),
                ).fetchone()
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM thread_messages WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            seq = int(row["max_seq"]) if row else 0
            for message in messages:
                if message.message_id:
                    duplicate = conn.execute(
                        "SELECT 1 FROM thread_messages WHERE thread_id = ? AND message_id = ?",
                        (thread_id, message.message_id),
                    ).fetchone()
                    if duplicate is not None:
                        continue
                seq += 1
                conn.execute(
                    "INSERT INTO thread_messages("
                    "thread_id, seq, message_id, role, message_json, created_at"
                    ") VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        thread_id,
                        seq,
                        message.message_id,
                        message.role,
                        message.message_json,
                        message.created_at,
                    ),
                )
                inserted += 1
        return inserted

    def replace_all(
        self,
        thread_id: str,
        messages: Sequence[ThreadMessageInput],
    ) -> int:
        """Publish a decoded legacy checkpoint using short write batches.

        Readers are gated by ``status != ready``, so the batches stay invisible
        without holding SQLite's writer lock for the entire transcript.
        """
        with self._db.transaction() as conn:
            if self._db.dialect == "postgresql":
                conn.execute(
                    "SELECT thread_id FROM threads WHERE thread_id = ? FOR UPDATE",
                    (thread_id,),
                ).fetchone()
            conn.execute("DELETE FROM thread_messages WHERE thread_id = ?", (thread_id,))
        batch_size = 200
        for start in range(0, len(messages), batch_size):
            with self._db.transaction() as conn:
                for index, message in enumerate(messages[start : start + batch_size], start=start):
                    conn.execute(
                        "INSERT INTO thread_messages("
                        "thread_id, seq, message_id, role, message_json, created_at"
                        ") VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            thread_id,
                            index + 1,
                            message.message_id,
                            message.role,
                            message.message_json,
                            message.created_at,
                        ),
                    )
        self.mark_projection(thread_id, "ready")
        return len(messages)
