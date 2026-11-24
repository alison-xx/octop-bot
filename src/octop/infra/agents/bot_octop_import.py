"""Octop Bot desktop: bring in the assistants, chats and model keys of an Octop install on
this computer.

Octop keeps everything in ``~/.octop``: ``octop.db`` plus one workspace folder per assistant,
whose ``.octop/memory.sqlite`` also holds the assistant's memory and chat checkpoints. The
import only copies: it reads Octop's database through SQLite's online backup and leaves Octop
untouched, so Octop may keep running. An assistant already here (same id) is skipped, so
importing again only adds assistants that are new.

IM channels and scheduled tasks arrive paused: Octop may still be answering on the same bot
and running the same schedule, and two of each would both reply.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shutil
import sqlite3
import tempfile
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cryptography.fernet import Fernet, InvalidToken

from octop.infra.backup.snapshot import (
    _patch_channel_metadata,
    _rewrite_session_key,
    snapshot_sqlite_file,
)
from octop.infra.crypto.fernet import PURPOSE_PROVIDER
from octop.infra.db.services import SharedServices
from octop.infra.errors import ErrorCode, OctopError

if TYPE_CHECKING:
    from octop.infra.agents.manager import AgentManager

logger = logging.getLogger(__name__)

# Parent first: each table's rows point at rows of the tables before it.
_CHAT_TABLES = (
    "threads",
    "thread_messages",
    "thread_history_projection",
    "thread_compaction_boundaries",
    "trajectory_events",
)
# Point at Octop rows that are not imported (skill packages, knowledge, published experts).
_DROPPED_AGENT_LINKS = ("skill_package_ids", "knowledge_base_ids", "published_expert_id")
_SQLITE_SUFFIXES = (".sqlite", ".db")
_SQLITE_SIDECARS = ("-wal", "-shm", "-journal")

_lock = asyncio.Lock()


@dataclass(frozen=True)
class SourceAgent:
    agent_id: str
    name: str
    threads: int
    exists: bool = False


@dataclass(frozen=True)
class ImportPreview:
    home: str
    agents: list[SourceAgent]
    providers: list[str] = field(default_factory=list)


@dataclass
class ImportedAgent:
    agent_id: str
    name: str
    status: str  # "imported" | "skipped" | "failed"
    reason: str = ""  # "exists" | "team" | "folder_exists" | "error"
    detail: str = ""
    threads: int = 0
    channels: int = 0
    cron_jobs: int = 0


@dataclass
class ImportReport:
    home: str
    agents: list[ImportedAgent] = field(default_factory=list)
    providers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def find_octop_home(own_root: Path, home: Path | None = None) -> Path | None:
    """``~/.octop`` when Octop is installed there on SQLite, and it is not this app's home."""
    root = (home or Path.home()) / ".octop"
    if _source_db(root) is None:
        return None
    with contextlib.suppress(OSError):
        if root.resolve() == own_root.resolve():
            return None
    return root


def _source_db(root: Path) -> Path | None:
    try:
        config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        config = {}
    database = config.get("database") if isinstance(config, dict) else None
    database = database if isinstance(database, dict) else {}
    if str(database.get("driver") or "sqlite") != "sqlite":
        return None
    path = Path(str(database.get("sqlite_path") or "octop.db")).expanduser()
    path = path if path.is_absolute() else root / path
    return path if path.is_file() else None


@contextlib.contextmanager
def _open_source(root: Path) -> Iterator[sqlite3.Connection]:
    """A private snapshot of Octop's database (consistent even while Octop writes to it)."""
    path = _source_db(root)
    if path is None:
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    with tempfile.TemporaryDirectory(prefix="octop-import-") as tmp:
        copy = Path(tmp) / "octop.db"
        snapshot_sqlite_file(path, copy)
        conn = sqlite3.connect(copy)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}


def _rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params)]


def _owner_id(src: sqlite3.Connection) -> int | None:
    """Octop's own user: its first admin, else its first user."""
    row = src.execute(
        "SELECT id FROM users ORDER BY CASE WHEN role = 'admin' THEN 0 ELSE 1 END, id LIMIT 1"
    ).fetchone()
    return int(row[0]) if row else None


def _source_agents(src: sqlite3.Connection, owner: int) -> list[dict[str, Any]]:
    return _rows(src, "SELECT * FROM agents WHERE user_id = ? ORDER BY id", (owner,))


def _thread_counts(src: sqlite3.Connection) -> dict[str, int]:
    return {
        str(row[0]): int(row[1])
        for row in src.execute("SELECT agent_id, COUNT(*) FROM threads GROUP BY agent_id")
    }


def preview(services: SharedServices, root: Path) -> ImportPreview:
    with _open_source(root) as src:
        owner = _owner_id(src)
        agents = [] if owner is None else _source_agents(src, owner)
        counts = _thread_counts(src)
        providers = [str(r["name"]) for r in _rows(src, "SELECT name FROM providers ORDER BY id")]
    taken = {row.name for row in services.provider_repo.list_all()}
    return ImportPreview(
        home=str(root),
        agents=[
            SourceAgent(
                agent_id=str(row["agent_id"]),
                name=str(row["name"]),
                threads=counts.get(str(row["agent_id"]), 0),
                exists=services.agent_repo.get(str(row["agent_id"])) is not None,
            )
            for row in agents
            if row.get("kind") != "team"
        ],
        providers=[name for name in providers if name not in taken],
    )


async def import_octop(
    services: SharedServices, registry: AgentManager, root: Path, user_id: int
) -> ImportReport:
    """Copy Octop's assistants, chats and providers in, then load the new assistants."""
    async with _lock:
        report = await asyncio.to_thread(_import, services, root, user_id)
        if report.providers:
            # Syncs every provider into the harness before the new assistants load.
            await registry.on_provider_changed(provider_name=report.providers[0])
        for item in report.agents:
            if item.status == "imported":
                await _load(services, registry, item.agent_id)
        return report


async def _load(services: SharedServices, registry: AgentManager, agent_id: str) -> None:
    row = await asyncio.to_thread(services.agent_repo.get, agent_id)
    if row is None or not row.enabled or row.last_state == "stopped":
        return
    try:
        registry.get_agent(agent_id)
        return
    except OctopError:
        pass
    try:
        await registry.start(agent_id)
    except Exception:
        # The rows are in; the assistant shows its error and starts on the next reload.
        logger.exception("imported assistant %s did not start", agent_id)


def _import(services: SharedServices, root: Path, user_id: int) -> ImportReport:
    report = ImportReport(home=str(root))
    with _open_source(root) as src:
        provider_key = _provider_fernet(src)
        report.providers = _import_providers(services, src, provider_key)
        owner = _owner_id(src)
        if owner is None:
            return report
        for row in _source_agents(src, owner):
            report.agents.append(_import_agent(services, src, root, row, owner, user_id))
    return report


def _provider_fernet(src: sqlite3.Connection) -> Fernet | None:
    row = src.execute("SELECT v FROM secrets WHERE k = ?", (PURPOSE_PROVIDER,)).fetchone()
    if row is None:
        return None
    try:
        return Fernet(bytes(row[0]))
    except (TypeError, ValueError):
        return None


def _open_key(fernet: Fernet | None, stored: str | None) -> str | None:
    """Octop's sealed provider key in plain text (legacy plaintext as is)."""
    if not stored or fernet is None:
        return stored
    try:
        return fernet.decrypt(stored.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError):
        return stored


def _import_providers(
    services: SharedServices, src: sqlite3.Connection, fernet: Fernet | None
) -> list[str]:
    repo = services.provider_repo
    taken = {row.name for row in repo.list_all()}
    added: list[str] = []
    for row in _rows(src, "SELECT * FROM providers ORDER BY id"):
        name = str(row["name"])
        if name in taken:
            continue
        provider_id = repo.create(
            name=name,
            kind=str(row["kind"]),
            base_url=row.get("base_url"),
            api_key=_open_key(fernet, row.get("api_key")),
            extra_json=row.get("extra_json"),
            models_json=row.get("models_json"),
            note=row.get("note"),
        )
        if not row.get("enabled", 1):
            repo.update(provider_id, enabled=False)
        taken.add(name)
        added.append(name)
    return added


def _import_agent(
    services: SharedServices,
    src: sqlite3.Connection,
    root: Path,
    row: dict[str, Any],
    old_uid: int,
    new_uid: int,
) -> ImportedAgent:
    agent_id = str(row["agent_id"])
    item = ImportedAgent(agent_id=agent_id, name=str(row["name"]), status="skipped")
    if row.get("kind") == "team":
        item.reason = "team"
        return item
    if services.agent_repo.get(agent_id) is not None:
        item.reason = "exists"
        return item

    config = _config(row.get("config_json"))
    source_dir = Path(str(config.get("workspace_dir") or root / "agents" / agent_id))
    dest_dir = services.paths.agent_workspace(agent_id)
    copy_dir = _inside(source_dir, root)
    if copy_dir:
        if dest_dir.exists():
            item.reason = "folder_exists"
            return item
        config["workspace_dir"] = str(dest_dir)
    # A folder outside ~/.octop (one the user picked) stays where it is and is shared.

    try:
        if copy_dir and source_dir.is_dir():
            _copy_workspace(source_dir, dest_dir)
        with services.db.transaction() as conn:
            dst = _Writer(conn)
            _insert_agent(dst, row, config, new_uid, _free_name(conn, str(row["name"]), new_uid))
            item.threads = _insert_chats(dst, src, agent_id, old_uid, new_uid)
            item.channels = _insert_channels(dst, src, agent_id, new_uid)
            item.cron_jobs = _insert_cron(dst, src, agent_id, old_uid, new_uid)
    except Exception as exc:
        logger.exception("importing Octop assistant %s failed", agent_id)
        if copy_dir:
            shutil.rmtree(dest_dir, ignore_errors=True)
        item.status, item.reason, item.detail = "failed", "error", str(exc)
        item.threads = item.channels = item.cron_jobs = 0
        return item
    item.status = "imported"
    return item


def _config(raw: object) -> dict[str, Any]:
    try:
        value = json.loads(str(raw)) if raw else {}
    except ValueError:
        value = {}
    return value if isinstance(value, dict) else {}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _copy_workspace(source: Path, dest: Path) -> None:
    """Copy a workspace; SQLite files through the online backup so a live Octop is safe."""

    def ignore(_dir: str, names: list[str]) -> list[str]:
        return [
            n
            for n in names
            if any(n.endswith(s + c) for s in _SQLITE_SUFFIXES for c in _SQLITE_SIDECARS)
        ]

    def copy(src: str, dst: str) -> str:
        if src.endswith(_SQLITE_SUFFIXES):
            try:
                snapshot_sqlite_file(Path(src), Path(dst))
                return dst
            except sqlite3.Error:
                Path(dst).unlink(missing_ok=True)
                wal = Path(src + "-wal")
                if wal.is_file():
                    shutil.copy2(wal, dst + "-wal")
        return str(shutil.copy2(src, dst))

    shutil.copytree(source, dest, symlinks=True, ignore=ignore, copy_function=copy)


def _free_name(dst: Any, name: str, user_id: int) -> str:
    """``name``, or ``name (Octop)`` / ``name (Octop 2)`` when a Bot already has it."""
    taken = {r[0] for r in dst.execute("SELECT name FROM agents WHERE user_id = ?", (user_id,))}
    if name not in taken:
        return name
    candidate, index = f"{name} (Octop)", 2
    while candidate in taken:
        candidate, index = f"{name} (Octop {index})", index + 1
    return candidate


class _Writer:
    """Inserts Octop rows into this app's tables, keeping only the columns both schemas have.

    Octop may be an older or newer release than this app; ``id`` is each side's own surrogate.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self._known: dict[str, set[str]] = {}

    def has(self, table: str) -> bool:
        return bool(self._columns(table))

    def _columns(self, table: str) -> set[str]:
        if table not in self._known:
            self._known[table] = _columns(self._conn, table)
        return self._known[table]

    def insert(self, table: str, row: dict[str, Any]) -> None:
        known = self._columns(table)
        columns = [c for c in row if c != "id" and c in known]
        names = ", ".join(f'"{c}"' for c in columns)
        marks = ", ".join("?" for _ in columns)
        self._conn.execute(
            f'INSERT INTO "{table}" ({names}) VALUES ({marks})', [row[c] for c in columns]
        )


def _insert_agent(
    dst: _Writer, row: dict[str, Any], config: dict[str, Any], user_id: int, name: str
) -> None:
    agent = {**row, "user_id": user_id, "name": name, "config_json": json.dumps(config)}
    agent.update({"is_shared": 0, "last_error": None})
    for column in _DROPPED_AGENT_LINKS:
        if column in agent:
            agent[column] = None
    dst.insert("agents", agent)


def _insert_chats(
    dst: _Writer, src: sqlite3.Connection, agent_id: str, old_uid: int, new_uid: int
) -> int:
    threads = _rows(src, "SELECT * FROM threads WHERE agent_id = ?", (agent_id,))
    for thread in threads:
        thread["session_key"] = _rewrite_session_key(
            str(thread["session_key"]), old_uid=old_uid, new_uid=new_uid
        )
        thread["user_id"] = new_uid
        dst.insert("threads", thread)
    ids = [str(t["thread_id"]) for t in threads]
    source_tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in _CHAT_TABLES[1:]:
        if table not in source_tables or not dst.has(table):
            continue
        for thread_id in ids:
            for chat_row in _rows(
                src, f'SELECT * FROM "{table}" WHERE thread_id = ?', (thread_id,)
            ):
                dst.insert(table, chat_row)
    for session in _rows(src, "SELECT * FROM sessions WHERE agent_id = ?", (agent_id,)):
        session["session_key"] = _rewrite_session_key(
            str(session["session_key"]), old_uid=old_uid, new_uid=new_uid
        )
        session["user_id"] = new_uid
        meta = _patch_channel_metadata(
            session.get("channel_metadata"), old_uid=old_uid, new_uid=new_uid
        )
        if meta is not None:
            session["channel_metadata"] = meta
        dst.insert("sessions", session)
    return len(threads)


_LEASES = ("runtime_lease_owner", "runtime_lease_token", "runtime_lease_until")
_RUN_LEASES = ("run_lease_owner", "run_lease_token", "run_lease_until")


def _insert_channels(dst: _Writer, src: sqlite3.Connection, agent_id: str, user_id: int) -> int:
    rows = _rows(src, "SELECT * FROM channels WHERE agent_id = ?", (agent_id,))
    for row in rows:
        config = {**_config(row.get("config_json")), "enabled": False}
        row.update({"user_id": user_id, "enabled": 0, "config_json": json.dumps(config)})
        row.update(dict.fromkeys(_LEASES))
        row["runtime_generation"] = 0
        dst.insert("channels", row)
    return len(rows)


def _insert_cron(
    dst: _Writer, src: sqlite3.Connection, agent_id: str, old_uid: int, new_uid: int
) -> int:
    rows = _rows(src, "SELECT * FROM cron_jobs WHERE agent_id = ?", (agent_id,))
    for row in rows:
        row["session_key"] = _rewrite_session_key(
            str(row["session_key"]), old_uid=old_uid, new_uid=new_uid
        )
        row.update({"user_id": new_uid, "enabled": 0})
        row.update(dict.fromkeys(_RUN_LEASES))
        dst.insert("cron_jobs", row)
    return len(rows)
