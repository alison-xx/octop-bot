"""Mirror a private task and its completed deep steps in the owner's workspace."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from langgraph.types import Command

from octop.i18n import tr
from octop.infra.bot_tasks.model import MAX_TASK_STEPS, Task, TaskStep
from octop.infra.utils.ulid import new_ulid

if TYPE_CHECKING:
    from octop_harness.backends.workspace import BackendWorkspace

    from octop.infra.bot_tasks.store import TaskStore
    from octop.infra.db.services import RepoBundle

logger = logging.getLogger(__name__)
_TASK_ID = re.compile(r"[0-9A-HJKMNP-TV-Z]{26}")


def render_record(task: Task, locale: str) -> str:
    lines = [f"# {task.goal}", "", f"## {tr('botTaskArchive.criteria', locale)}"]
    for criterion in task.criteria:
        mark = {"passed": "✓", "failed": "×", "skipped": "—", "pending": "○"}[criterion.status]
        lines.append(f"- {mark} {criterion.text}")
        if criterion.evidence:
            lines.append(f"  {criterion.evidence}")
    for key, items in [
        (
            "steps",
            [
                f"[{'x' if step.status == 'completed' else ' '}] {step.content}"
                for step in task.steps
            ],
        ),
        ("assumptions", task.assumptions),
        ("files", [item.name for item in task.deliverables]),
        ("issues", task.open_issues),
    ]:
        if items:
            lines.extend(
                ("", f"## {tr('botTaskArchive.' + key, locale)}", *(f"- {s}" for s in items))
            )
    if task.summary:
        lines.extend(("", task.summary))
    return "\n".join(lines) + "\n"


class TaskArchive:
    def __init__(
        self, workspace: BackendWorkspace, repos: RepoBundle, agent: str, owner: int, locale: str
    ) -> None:
        self.workspace = workspace
        self.repos = repos
        self.agent = agent
        self.owner = owner
        self.locale = locale

    def _private_thread(self, thread: str) -> bool:
        row = self.repos.thread_repo.get(thread) if thread else None
        if not row or row.agent_id != self.agent or row.user_id != self.owner:
            return False
        session = self.repos.session_repo.get(row.session_key)
        return bool(
            session
            and session.chat_type == "dm"
            and session.user_id == self.owner
            and session.agent_id == self.agent
        )

    def read_tool(self, store: TaskStore) -> StructuredTool:
        def task_read_step(checkpoint: str, config: RunnableConfig) -> str:
            """Read the saved step named by its checkpoint in this private conversation."""
            thread = str((config.get("configurable") or {}).get("thread_id") or "")
            if _TASK_ID.fullmatch(checkpoint) and self._private_thread(thread):
                for task in store.tasks(thread):
                    if _TASK_ID.fullmatch(task.id) and any(
                        step.checkpoint == checkpoint for step in task.steps
                    ):
                        record = self.workspace.read_text(
                            f".octop/tasks/{task.id}/steps/{checkpoint}.md"
                        )
                        if record:
                            return record
                        break
            return tr("botTaskArchive.unavailable", self.locale)

        return StructuredTool.from_function(task_read_step)

    def observe(
        self, store: TaskStore, thread: str, name: str, result: ToolMessage | Command[Any]
    ) -> None:
        if name not in {
            "task_plan",
            "task_check",
            "task_finish",
            "write_todos",
            "send_file_to_user",
        }:
            return
        if not self._private_thread(thread):
            return
        task_id = None
        if name.startswith("task_"):
            if not isinstance(result, ToolMessage) or result.status == "error":
                return
            try:
                task_id = json.loads(result.text)["task"]["id"]
            except (ValueError, KeyError, TypeError):
                return
        with store.locked(thread):
            task = (
                next((item for item in store.tasks(thread) if item.id == task_id), None)
                if task_id
                else store.running(thread)
            )
            if not task or not _TASK_ID.fullmatch(task.id):
                return
            directory = f".octop/tasks/{task.id}"
            if name == "write_todos":
                if not isinstance(result, Command) or not isinstance(result.update, dict):
                    return
                raw = result.update.get("todos")
                if not isinstance(raw, list) or len(raw) > MAX_TASK_STEPS:
                    return
                steps = []
                for index, item in enumerate(raw):
                    if (
                        not isinstance(item, dict)
                        or not isinstance(item.get("content"), str)
                        or item.get("status") not in {"pending", "in_progress", "completed"}
                    ):
                        return
                    step = TaskStep(content=item["content"][:500], status=item["status"])
                    if (
                        index < len(task.steps)
                        and task.steps[index].content == step.content
                        and task.steps[index].status == step.status
                    ):
                        step.checkpoint = task.steps[index].checkpoint
                    steps.append(step)
                task.steps = steps
                store.save(thread, task)
            try:
                record = render_record(task, self.locale)
                if task.tier == "deep":
                    for step in task.steps:
                        if step.status == "completed" and step.checkpoint is None:
                            checkpoint = new_ulid()
                            self.workspace.write_text(
                                f"{directory}/steps/{checkpoint}.md",
                                f"# {step.content}\n\n{record}",
                            )
                            step.checkpoint = checkpoint
                            store.save(thread, task)
                self.workspace.upload_bytes(f"{directory}/task.md", record.encode("utf-8"))
            except OSError:
                # The database retains progress. A subsequent task update retries the mirror.
                logger.warning("Could not mirror task %s in its workspace", task.id)
