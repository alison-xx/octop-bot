"""Tasks per conversation, kept in the settings table (a short list per thread)."""

from __future__ import annotations

import json
import logging
import threading
from typing import TYPE_CHECKING

from pydantic import ValidationError

from octop.infra.bot_tasks.model import Task

if TYPE_CHECKING:
    from octop.infra.db.repos.settings import SettingsRepo

logger = logging.getLogger(__name__)

# Older tasks of a conversation stay readable; the list does not grow without end.
KEEP_PER_THREAD = 20


class TaskStore:
    def __init__(self, settings: SettingsRepo) -> None:
        self._settings = settings
        self._guard = threading.Lock()

    @staticmethod
    def _key(thread_id: str) -> str:
        return f"octop_bot:tasks:{thread_id}"

    def tasks(self, thread_id: str) -> list[Task]:
        raw = self._settings.get(self._key(thread_id))
        if not raw:
            return []
        try:
            return [Task.model_validate(item) for item in json.loads(raw)]
        except (ValueError, ValidationError):
            logger.warning("unreadable task list for thread %s", thread_id, exc_info=True)
            return []

    def running(self, thread_id: str) -> Task | None:
        found = [t for t in self.tasks(thread_id) if t.status == "running"]
        return found[-1] if found else None

    def save(self, thread_id: str, task: Task) -> Task:
        """Insert or replace ``task`` (by id) in its conversation's list."""
        with self._guard:
            items = [t for t in self.tasks(thread_id) if t.id != task.id]
            items.append(task)
            items = items[-KEEP_PER_THREAD:]
            self._settings.set(
                self._key(thread_id),
                json.dumps([t.model_dump(mode="json") for t in items], ensure_ascii=False),
            )
        return task
