"""An account's reusable Bot photos. Each batch item commits independently."""

from __future__ import annotations

import time
from typing import Any, Literal

from octop.infra.db.pool import DatabasePool


class BotAvatarPhotoRepo:
    def __init__(self, db: DatabasePool) -> None:
        self._db = db

    def store(
        self, owner: int, digest: str, name: str, mime: str, content: bytes, *, capacity: int
    ) -> tuple[Literal["imported", "duplicate", "full"], str]:
        with self._db.transaction() as conn:
            # SQLite already takes an IMMEDIATE writer lock. Serialize this owner's
            # concurrent import/count/insert sequence on PostgreSQL as well.
            if self._db.dialect == "postgresql":
                conn.execute("SELECT id FROM users WHERE id=? FOR UPDATE", (owner,)).fetchone()
            existing = conn.execute(
                "SELECT name FROM bot_avatar_photos WHERE user_id=? AND photo_id=?", (owner, digest)
            ).fetchone()
            if existing:
                return "duplicate", str(existing["name"])
            count = conn.execute(
                "SELECT COUNT(*) FROM bot_avatar_photos WHERE user_id=?", (owner,)
            ).fetchone()
            if int(count[0]) >= capacity:
                return "full", name
            conn.execute(
                "INSERT INTO bot_avatar_photos(user_id,photo_id,name,mime,content,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (owner, digest, name, mime, content, time.time_ns() // 1_000_000),
            )
            return "imported", name

    def page(
        self, owner: int, offset: int, limit: int, *, with_content: bool
    ) -> tuple[int, list[dict[str, Any]]]:
        with self._db.connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM bot_avatar_photos WHERE user_id=?", (owner,)
            ).fetchone()
            projection = (
                "SELECT photo_id,name,mime,created_at,content "
                if with_content
                else "SELECT photo_id,name "
            )
            rows = conn.execute(
                projection + "FROM bot_avatar_photos "
                "WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
                (owner, limit, offset),
            ).fetchall()
        return int(count[0]), [dict(row) for row in rows]

    def content(self, owner: int, digest: str) -> bytes | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT content FROM bot_avatar_photos WHERE user_id=? AND photo_id=?",
                (owner, digest),
            ).fetchone()
        return bytes(row["content"]) if row is not None else None

    def delete(self, owner: int, digest: str) -> bool:
        with self._db.transaction() as conn:
            return bool(
                conn.execute(
                    "DELETE FROM bot_avatar_photos WHERE user_id=? AND photo_id=?", (owner, digest)
                ).rowcount
            )
