from pathlib import Path

import pytest
from deepagents.backends.local_shell import LocalShellBackend
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from octop_harness.backends.workspace import BackendWorkspace

from octop.infra.bot_tasks.archives import TaskArchive
from octop.infra.bot_tasks.model import Budget, Criterion, Task
from octop.infra.bot_tasks.store import TaskStore
from octop.infra.bot_tasks.tools import snapshot
from octop.infra.bot_tasks.watchdog import restored_task
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle


@pytest.mark.parametrize("chat_type", ["dm", "group"])
def test_private_task_checkpoints_survive_reopening(tmp_path: Path, chat_type: str) -> None:
    db = SqlitePool(tmp_path / "db")
    try:
        run_migrations(db)
        repos = RepoBundle.from_pool(db)
        repos.user_repo.create(username="qa", password_hash="unused", role="user")
        repos.agent_repo.create(agent_id="sample", user_id=1, name="sample")
        ctx = {
            "user_id": 1,
            "agent_id": "sample",
            "channel_type": "dashboard",
            "session_key": "sample-dm",
            "thread_id": "thread",
        }
        repos.thread_repo.insert(**ctx)
        repos.session_repo.upsert(**ctx, chat_type=chat_type)
        root = tmp_path / "workspace"
        root.mkdir()
        ws = BackendWorkspace(LocalShellBackend(root_dir=str(root), virtual_mode=False), root)
        store = TaskStore(repos.settings_repo)
        archive = TaskArchive(ws, repos, "sample", 1, "zh")
        task = store.save(
            "thread",
            Task(
                goal="核对练习表",
                tier="deep",
                budget=Budget(steps=60, minutes=30),
                criteria=[Criterion(text="两行样例")],
            ),
        )
        base = f".octop/tasks/{task.id}"
        archive.observe(
            store, "thread", "task_plan", ToolMessage(content=snapshot(task), tool_call_id="plan")
        )
        command = Command(update={"todos": [{"content": "核对行数", "status": "completed"}]})
        archive.observe(store, "thread", "write_todos", command)
        if chat_type == "group":
            assert ws.read_text(f"{base}/task.md") is None
            return
        fresh = TaskStore(repos.settings_repo)
        task = fresh.running("thread")
        assert task is not None and task.steps[0].checkpoint
        checkpoint = f"{base}/steps/{task.steps[0].checkpoint}.md"
        saved = ws.read_text(checkpoint)
        assert saved and "核对行数" in saved
        read = archive.read_tool(fresh)
        assert (
            read.invoke(
                {"checkpoint": task.steps[0].checkpoint}, {"configurable": {"thread_id": "thread"}}
            )
            == saved
        )
        assert "没有可读取" in read.invoke(
            {"checkpoint": task.steps[0].checkpoint}, {"configurable": {"thread_id": "other"}}
        )
        task.criteria[0].evidence = "样例甲和乙各一行"
        task.criteria[0].status = "passed"
        fresh.save("thread", task)
        archive.observe(
            fresh, "thread", "task_check", ToolMessage(content=snapshot(task), tool_call_id="check")
        )
        archive.observe(fresh, "thread", "write_todos", command)
        assert ws.read_text(checkpoint) == saved
        assert "样例甲和乙各一行" in (ws.read_text(f"{base}/task.md") or "")
        assert "核对行数" in restored_task(task)
        restored = fresh.running("thread")
        assert restored and restored.steps == task.steps
    finally:
        db.close()
