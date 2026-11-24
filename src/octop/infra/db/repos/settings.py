"""Settings KV store — lightweight key/value pairs backed by SQLite."""

from __future__ import annotations

from octop.infra.db.pool import DatabasePool


class SettingsRepo:
    _KEY_ACTIVE_MODEL = "active_model"

    def __init__(self, db: DatabasePool):
        self._db = db

    def get(self, key: str) -> str | None:
        with self._db.connect() as conn:
            r = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return r["value"] if r else None

    def set(self, key: str, value: str) -> None:
        self.set_many({key: value})

    def set_many(self, values: dict[str, str]) -> None:
        with self._db.transaction() as conn:
            conn.executemany(
                "INSERT INTO settings(key, value) VALUES(?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                list(values.items()),
            )

    def delete(self, key: str) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))

    def replace_if_current(self, key: str, expected: str, value: str) -> bool:
        with self._db.transaction() as conn:
            return bool(
                conn.execute(
                    "UPDATE settings SET value = ? WHERE key = ? AND value = ?",
                    (value, key, expected),
                ).rowcount
                == 1
            )

    def with_prefix(self, prefix: str) -> dict[str, str]:
        escaped = prefix.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT key,value FROM settings WHERE key LIKE ? ESCAPE '!'", (escaped + "%",)
            ).fetchall()
        return {row["key"]: row["value"] for row in rows}

    def get_or_insert(self, key: str, value: str) -> str:
        """Claim a stable value across concurrent initializations."""
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO NOTHING",
                (key, value),
            )
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            assert row is not None
            return str(row["value"])

    def get_active_model(self) -> tuple[str, str]:
        """Return (provider_name, model_id); empty strings if not set."""
        raw = self.get(self._KEY_ACTIVE_MODEL) or ""
        name, _, model = raw.partition("/")
        return name, model

    def set_active_model(self, provider_name: str, model_id: str) -> None:
        self.set(self._KEY_ACTIVE_MODEL, f"{provider_name}/{model_id}")
