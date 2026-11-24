"""Persistence of Bot rooms, their public timeline, and retryable turns."""

from __future__ import annotations

import json
from typing import Any

from octop.infra.db.pool import DatabasePool
from octop.infra.db.repos._base import now_ts
from octop.infra.utils.ulid import new_ulid


def _read_key(user_id: int, group_id: str) -> str:
    return f"bot-room-read:{user_id}:{group_id}"


class BotGroupRepo:
    LEASE_SECONDS = 120

    def __init__(self, db: DatabasePool) -> None:
        self._db = db

    def list_by_owner(self, user_id: int) -> list[dict[str, Any]]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM bot_groups WHERE user_id=? ORDER BY id", (user_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, group_id: str, user_id: int) -> dict[str, Any] | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM bot_groups WHERE group_id=? AND user_id=?", (group_id, user_id)
            ).fetchone()
        return dict(row) if row else None

    def create(self, user_id: int, name: str, admin: str, members: list[str], mode: str) -> str:
        group_id = new_ulid()
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO bot_groups(group_id,user_id,name,admin_id,member_ids,reply_mode,"
                "created_at) VALUES(?,?,?,?,?,?,?)",
                (group_id, user_id, name, admin, json.dumps(members), mode, now_ts()),
            )
            # Groups without a cursor predate read tracking; activity() starts them
            # at their latest message.
            conn.execute(
                "INSERT INTO settings(key,value) VALUES(?,'0') ON CONFLICT(key) DO NOTHING",
                (_read_key(user_id, group_id),),
            )
        return group_id

    def activity(self, user_id: int) -> list[dict[str, Any]]:
        """Replies after the owner's read cursor and the latest visible message, per group."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT g.group_id, r.value IS NULL AS no_cursor, "
                "(SELECT COUNT(*) FROM bot_group_messages m "
                "WHERE m.group_id=g.group_id AND m.role IN ('assistant','error') "
                "AND m.id>CAST(r.value AS INTEGER)) AS unread_count, "
                "(SELECT MAX(m.id) FROM bot_group_messages m WHERE m.group_id=g.group_id "
                "AND m.role!='pass') AS last_pk "
                "FROM bot_groups g LEFT JOIN settings r ON r.key=? || g.group_id "
                "WHERE g.user_id=? ORDER BY g.id",
                (_read_key(user_id, ""), user_id),
            ).fetchall()
            groups = [dict(row) for row in rows]
            last_ids = [g["last_pk"] for g in groups if g["last_pk"] is not None]
            latest: dict[int, dict[str, Any]] = {}
            if last_ids:
                marks = ",".join("?" for _ in last_ids)
                latest = {
                    int(row["id"]): dict(row)
                    for row in conn.execute(
                        "SELECT id,message_id,group_id,request_id,slot,role,agent_id,text,"
                        f"thread_id,created_at FROM bot_group_messages WHERE id IN ({marks})",
                        tuple(last_ids),
                    ).fetchall()
                }
        # Groups from before read tracking start reading at their latest message,
        # so history stays read and later replies count.
        for group in groups:
            if group.pop("no_cursor"):
                self.mark_read(group["group_id"], user_id)
        for group in groups:
            pk = group.pop("last_pk")
            group["unread_count"] = int(group["unread_count"] or 0)
            group["last_message"] = latest.get(int(pk)) if pk is not None else None
        return groups

    def mark_read(self, group_id: str, user_id: int) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO settings(key,value) SELECT ?, CAST(COALESCE(MAX(m.id),0) AS TEXT) "
                "FROM bot_groups g LEFT JOIN bot_group_messages m ON m.group_id=g.group_id "
                "WHERE g.group_id=? AND g.user_id=? GROUP BY g.group_id "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (_read_key(user_id, group_id), group_id, user_id),
            )

    def update(
        self, group_id: str, user_id: int, name: str, admin: str, members: list[str], mode: str
    ) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE bot_groups SET name=?,admin_id=?,member_ids=?,reply_mode=? "
                "WHERE group_id=? AND user_id=?",
                (name, admin, json.dumps(members), mode, group_id, user_id),
            )

    def delete(self, group_id: str, user_id: int) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "DELETE FROM settings WHERE (key LIKE ? OR key LIKE ?) AND value = ? AND EXISTS "
                "(SELECT 1 FROM bot_groups WHERE group_id = ? AND user_id = ?)",
                (
                    f"bot-room-im:{user_id}:%",
                    f"bot-room-im-sent:{user_id}:%",
                    group_id,
                    group_id,
                    user_id,
                ),
            )
            conn.execute(
                "DELETE FROM settings WHERE key=? AND EXISTS "
                "(SELECT 1 FROM bot_groups WHERE group_id=? AND user_id=?)",
                (_read_key(user_id, group_id), group_id, user_id),
            )
            conn.execute(
                "DELETE FROM bot_groups WHERE group_id=? AND user_id=?", (group_id, user_id)
            )

    def im_sessions(self, user_id: int) -> list[dict[str, Any]]:
        """External conversations seen on the user's own channel instances."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT s.session_key, s.channel_subject_id, s.channel_chat_type, "
                "c.channel_id, c.kind, c.name FROM sessions s "
                "JOIN channels c ON c.channel_id=s.channel_id AND c.agent_id=s.agent_id "
                "JOIN agents a ON a.agent_id=c.agent_id "
                "WHERE s.user_id=? AND c.user_id=? AND a.user_id=? AND c.kind=s.channel_type "
                "AND s.channel_subject_id IS NOT NULL ORDER BY s.updated_at DESC",
                (user_id, user_id, user_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def unlink_im(self, key: str, group_id: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM settings WHERE key=? AND value=?", (key, group_id))

    def claim_im_reply(self, owner: int, binding: str, group_id: str, request_id: str) -> bool:
        """Only a finished turn on the still-linked conversation may emit a reply once."""
        with self._db.transaction() as conn:
            return bool(
                conn.execute(
                    "INSERT INTO settings(key,value) SELECT ?, t.group_id FROM bot_group_turns t "
                    "JOIN settings b ON b.key=? AND b.value=t.group_id "
                    "WHERE t.group_id=? AND t.request_id=? AND t.finished=1 "
                    "ON CONFLICT(key) DO NOTHING",
                    (
                        f"bot-room-im-sent:{owner}:{group_id}:{request_id}",
                        binding,
                        group_id,
                        request_id,
                    ),
                ).rowcount
            )

    def set_memory(self, group_id: str, user_id: int, memory: str) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE bot_groups SET memory=? WHERE group_id=? AND user_id=?",
                (memory, group_id, user_id),
            )

    def set_goal(self, group_id: str, user_id: int, goal: str, previous: str | None) -> bool:
        with self._db.transaction() as conn:
            return bool(
                conn.execute(
                    "UPDATE bot_groups SET goal=? WHERE group_id=? AND user_id=? "
                    "AND COALESCE(goal,'')=?",
                    (goal, group_id, user_id, previous or ""),
                ).rowcount
            )

    def messages(
        self,
        group_id: str,
        *,
        after_id: str | None = None,
        request_id: str | None = None,
        recent: int | None = None,
        internal: bool = False,
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT m.*, (SELECT t.input_json FROM bot_group_turns t WHERE m.role='user' "
            "AND t.group_id=m.group_id AND t.request_id=m.request_id) AS turn_input "
            "FROM bot_group_messages m WHERE group_id=?"
        )
        params: list[Any] = [group_id]
        if not internal:
            sql += " AND role!='pass'"
        if after_id:
            sql += " AND id>(SELECT id FROM bot_group_messages WHERE message_id=? AND group_id=?)"
            params.extend((after_id, group_id))
        if request_id:
            sql += " AND request_id=?"
            params.append(request_id)
        if recent:
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(recent)
        else:
            sql += " ORDER BY id"
        with self._db.connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        result = []
        for row in reversed(rows) if recent else rows:
            entry = dict(row)
            raw = entry.pop("turn_input")
            inputs = json.loads(raw) if raw else []
            entry["attachment_paths"] = inputs[3] if len(inputs) > 3 else []
            result.append(entry)
        return result

    def import_messages(self, group_id: str, messages: list[dict[str, Any]]) -> None:
        """Add a finished timeline moved from another server, keeping its turns and times.

        Each message carries ``request_id``, ``slot``, ``role``, ``agent_id``, ``text`` and
        ``created_at``. A request already present is skipped, so a retried move adds nothing.
        """
        with self._db.transaction() as conn:
            for message in messages:
                conn.execute(
                    "INSERT INTO bot_group_turns(group_id,request_id,input_json,lease_until,"
                    "finished) VALUES(?,?,'[]',0,1) ON CONFLICT(group_id,request_id) DO NOTHING",
                    (group_id, message["request_id"]),
                )
                conn.execute(
                    "INSERT INTO bot_group_messages(message_id,group_id,request_id,slot,role,"
                    "agent_id,text,created_at) VALUES(?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(group_id,request_id,slot) DO NOTHING",
                    (
                        new_ulid(),
                        group_id,
                        message["request_id"],
                        message["slot"],
                        message["role"],
                        message["agent_id"],
                        message["text"],
                        message["created_at"],
                    ),
                )

    def has_turn(self, group_id: str, request_id: str) -> bool:
        with self._db.connect() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM bot_group_turns WHERE group_id=? AND request_id=?",
                    (group_id, request_id),
                ).fetchone()
                is not None
            )

    def claim(self, group_id: str, request_id: str, input_json: str, text: str, token: str) -> str:
        ts = now_ts()
        deadline = ts + self.LEASE_SECONDS
        with self._db.transaction() as conn:
            created = conn.execute(
                "INSERT INTO bot_group_turns(group_id,request_id,input_json,lease_token,lease_until)"
                " VALUES(?,?,?,?,?) ON CONFLICT(group_id,request_id) DO NOTHING",
                (group_id, request_id, input_json, token, deadline),
            ).rowcount
            if created:
                conn.execute(
                    "INSERT INTO bot_group_messages(message_id,group_id,request_id,slot,role,text,"
                    "created_at) VALUES(?,?,?,'user','user',?,?)",
                    (new_ulid(), group_id, request_id, text, ts),
                )
                return "acquired"
            row = conn.execute(
                "SELECT input_json,finished FROM bot_group_turns WHERE group_id=? AND request_id=?",
                (group_id, request_id),
            ).fetchone()
            if row["input_json"] != input_json:
                return "conflict"
            if row["finished"]:
                return "finished"
            resumed = conn.execute(
                "UPDATE bot_group_turns SET lease_token=?,lease_until=? WHERE group_id=? AND "
                "request_id=? AND finished=0 AND lease_until<=?",
                (token, deadline, group_id, request_id, ts),
            ).rowcount
        return "acquired" if resumed else "busy"

    def unfinished(self) -> list[dict[str, Any]]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT t.*,g.user_id FROM bot_group_turns t JOIN bot_groups g "
                "ON g.group_id=t.group_id WHERE t.finished=0 ORDER BY t.lease_until"
            ).fetchall()
        return [dict(row) for row in rows]

    def begin_reply(
        self, group_id: str, request_id: str, token: str, slot: str, agent_id: str
    ) -> bool:
        with self._db.transaction() as conn:
            return bool(
                conn.execute(
                    "INSERT INTO bot_group_drafts(group_id,request_id,slot,agent_id,text) "
                    "SELECT group_id,request_id,?,?,' ' FROM bot_group_turns WHERE group_id=? "
                    "AND request_id=? AND lease_token=? AND finished=0 ON CONFLICT(group_id,request_id,slot) "
                    "DO NOTHING",
                    (slot, agent_id, group_id, request_id, token),
                ).rowcount
            )

    def lease(
        self,
        group_id: str,
        request_id: str,
        token: str,
        *,
        close: bool = False,
        finished: bool = False,
    ) -> bool:
        with self._db.transaction() as conn:
            return bool(
                conn.execute(
                    "UPDATE bot_group_turns SET lease_until=?,finished=? "
                    "WHERE group_id=? AND request_id=? AND lease_token=? AND finished=0",
                    (
                        0 if close else now_ts() + self.LEASE_SECONDS,
                        int(finished),
                        group_id,
                        request_id,
                        token,
                    ),
                ).rowcount
            )

    def draft(
        self, group_id: str, request_id: str, token: str, slot: str, agent_id: str, text: str
    ) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO bot_group_drafts(group_id,request_id,slot,agent_id,text) "
                "SELECT group_id,request_id,?,?,? FROM bot_group_turns WHERE group_id=? "
                "AND request_id=? AND lease_token=? AND finished=0 ON CONFLICT(group_id,request_id,slot) "
                "DO UPDATE SET text=excluded.text",
                (slot, agent_id, text, group_id, request_id, token),
            )

    def drafts(self, group_id: str, user_id: int) -> list[dict[str, Any]]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT d.agent_id,d.request_id,d.text FROM bot_group_drafts d JOIN bot_group_turns t "
                "ON t.group_id=d.group_id AND t.request_id=d.request_id JOIN bot_groups g ON g.group_id=d.group_id "
                "WHERE g.group_id=? AND g.user_id=? AND t.lease_until>? AND t.finished=0 ORDER BY d.agent_id",
                (group_id, user_id, now_ts()),
            ).fetchall()
        return [dict(r) for r in rows]

    def reply(
        self,
        group_id: str,
        request_id: str,
        token: str,
        slot: str,
        role: str,
        agent_id: str,
        text: str,
        thread_id: str | None,
    ) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO bot_group_messages(message_id,group_id,request_id,slot,role,agent_id,"
                "text,thread_id,created_at) SELECT ?,group_id,request_id,?,?,?,?,?,? FROM "
                "bot_group_turns WHERE group_id=? AND request_id=? AND lease_token=? AND finished=0"
                " ON CONFLICT(group_id,request_id,slot) DO NOTHING",
                (
                    new_ulid(),
                    slot,
                    role,
                    agent_id,
                    text,
                    thread_id,
                    now_ts(),
                    group_id,
                    request_id,
                    token,
                ),
            )
            conn.execute(
                "DELETE FROM bot_group_drafts WHERE group_id=? AND request_id=? AND slot=? AND EXISTS "
                "(SELECT 1 FROM bot_group_turns WHERE group_id=? AND request_id=? AND lease_token=?)",
                (group_id, request_id, slot, group_id, request_id, token),
            )
