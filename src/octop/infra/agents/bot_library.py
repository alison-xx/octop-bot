"""Files a Bot produced in my chats with it (Bot profile → Library)."""

from __future__ import annotations

import asyncio
import datetime as dt
import mimetypes
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from octop.infra.gateway.media.backend_files import (
    extract_workspace_rel,
    is_allowed_host_download_abs_path,
    is_host_absolute_path,
    workspace_download_url,
)

Period = Literal["today", "week", "older"]

MAX_THREADS = 200
MAX_FILES = 200
# Each folder is one listing call on a remote store; past this the rest keep their chat time.
MAX_LISTED_FOLDERS = 40


@dataclass
class _Found:
    path: str
    host: bool
    thread_id: str
    at: int
    size: int | None = None


def _relative(path: str, roots: Sequence[str]) -> str | None:
    text = path.replace("\\", "/")
    for root in roots:
        base = root.replace("\\", "/").rstrip("/")
        if base and text.startswith(base + "/"):
            return text[len(base) + 1 :]
    if not is_host_absolute_path(text):
        return text.lstrip("/")
    # The same workspace under another spelling of the Octop home.
    return extract_workspace_rel(text) if "/.octop/" in text else None


def _hidden(path: str) -> bool:
    return any(part.startswith(".") for part in path.split("/") if part)


def _modified(raw: object) -> int | None:
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str) and raw:
        try:
            return int(dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp())
        except ValueError:
            return None
    return None


def _field(entry: Any, name: str) -> Any:
    return entry.get(name) if isinstance(entry, dict) else getattr(entry, name, None)


def period_of(at: int, *, timezone: str, now: dt.datetime) -> Period:
    """Today / earlier this week (the last seven days) / older, on the server's calendar."""
    zone = ZoneInfo(timezone)
    day = dt.datetime.fromtimestamp(at, zone).date()
    today = now.astimezone(zone).date()
    if day >= today:
        return "today"
    if day > today - dt.timedelta(days=7):
        return "week"
    return "older"


def _collect(rows: Sequence[Any], agent_id: str, roots: Sequence[str], cloud: bool) -> list[_Found]:
    found: list[_Found] = []
    seen: set[str] = set()
    for row in rows:
        at = int(row.last_active or row.created_at or 0)
        for artifact in reversed(row.artifacts):
            if artifact.agent_id and artifact.agent_id != agent_id:
                continue
            rel = _relative(artifact.path, roots)
            host = rel is None
            path = artifact.path if host else rel
            if not path or _hidden(path) or (host and cloud):
                continue
            key = path.casefold() if os.name == "nt" else path
            if key in seen:
                continue
            seen.add(key)
            found.append(_Found(path=path, host=host, thread_id=row.thread_id, at=at))
    return found


async def _stat_workspace(workspace: Any, files: list[_Found]) -> list[_Found]:
    folders: dict[str, list[_Found]] = {}
    for item in files:
        folders.setdefault(item.path.rpartition("/")[0] or ".", []).append(item)
    kept: list[_Found] = []
    for index, (folder, items) in enumerate(folders.items()):
        listing = await workspace.als(folder) if index < MAX_LISTED_FOLDERS else None
        if listing is None:
            kept.extend(items)
            continue
        entries = {
            str(_field(entry, "path") or "").rstrip("/").rsplit("/", 1)[-1]: entry
            for entry in getattr(listing, "entries", None) or []
            if not _field(entry, "is_dir")
        }
        for item in items:
            entry = entries.get(item.path.rsplit("/", 1)[-1])
            if entry is None:
                continue
            size = _field(entry, "size")
            item.size = int(size) if isinstance(size, (int, float)) else None
            item.at = _modified(_field(entry, "modified_at")) or item.at
            kept.append(item)
    return kept


def _stat_host(files: list[_Found], workspace_dir: Path) -> list[_Found]:
    kept: list[_Found] = []
    for item in files:
        if not is_allowed_host_download_abs_path(item.path, workspace=workspace_dir):
            continue
        try:
            stat = os.stat(item.path)
        except OSError:
            continue
        item.size, item.at = stat.st_size, int(stat.st_mtime)
        kept.append(item)
    return kept


async def bot_library(
    *,
    thread_repo: Any,
    workspace: Any | None,
    roots: Sequence[str],
    agent_id: str,
    user_id: int,
    timezone: str,
    cloud: bool,
    now: dt.datetime | None = None,
) -> list[dict[str, Any]]:
    """Newest first: files the Bot wrote or sent in my conversations that still exist."""
    if workspace is None:
        return []
    rows = await asyncio.to_thread(
        thread_repo.list_by_agent_user, agent_id=agent_id, user_id=user_id, limit=MAX_THREADS
    )
    rows = sorted(rows, key=lambda row: row.last_active or row.created_at or 0, reverse=True)
    found = _collect(rows, agent_id, [*roots, str(workspace.workspace_dir)], cloud)
    kept = await _stat_workspace(workspace, [f for f in found if not f.host])
    kept += await asyncio.to_thread(
        _stat_host, [f for f in found if f.host], Path(workspace.workspace_dir)
    )
    kept.sort(key=lambda item: item.at, reverse=True)
    current = now or dt.datetime.now(ZoneInfo(timezone))
    out: list[dict[str, Any]] = []
    for item in kept[:MAX_FILES]:
        name = item.path.rstrip("/").rsplit("/", 1)[-1]
        out.append(
            {
                "name": name,
                "path": item.path,
                "size": item.size,
                "mime": mimetypes.guess_type(name)[0],
                "created_at": item.at,
                "thread_id": item.thread_id,
                "period": period_of(item.at, timezone=timezone, now=current),
                "url": workspace_download_url(agent_id, item.path),
            }
        )
    return out


__all__ = ["Period", "bot_library", "period_of"]
