"""A Bot's cloud computer as a harness backend (``deepagents`` ``BaseSandbox``).

The agent's ``/`` is the workspace folder on the computer's own disk (``WORKSPACE``), which
persists while it is paused; ``execute`` runs there with the whole computer (desktop, Chrome,
its own files) at hand. Path mapping follows octop-harness's Docker sandbox: file tools see
virtual paths, the shell sees real ones.

The Bot's context (SOUL, AGENTS, MEMORY and the other persona files, ``.octop/`` system files,
memory, skills and chat attachments in ``inbound/``) stays in the P1 object store: the harness
reads it at every start and new conversation, and that must never wake (and bill) a computer.
Only work on the computer starts it: ``execute`` and files outside those paths. The first time
a Bot's computer starts, the files the Bot already had in the object store are copied onto it.
``close`` leaves the computer running, since the idle reaper pauses it.
"""

from __future__ import annotations

import asyncio
import posixpath
import shlex
from typing import TYPE_CHECKING, Any

from deepagents.backends.protocol import (
    FILE_NOT_FOUND,
    BackendProtocol,
    DeleteResult,
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox

from octop.infra.cloud.computers.driver import WORKSPACE
from octop.infra.errors import ErrorCode, OctopError

if TYPE_CHECKING:
    from pathlib import Path

    from octop.infra.cloud.computers.manager import ComputerManager

DEFAULT_COMMAND_TIMEOUT = 30 * 60
TAKEN_OVER = (
    "The user has taken over this computer (for example to sign in or solve a check). "
    "Do not use it now; tell the user what you need and wait until they hand it back."
)
NO_CAPACITY = (
    "The cloud computer could not start: no cloud computer is free right now. "
    "Do not retry now; tell the user to try again in a few minutes."
)

# Context the harness reads on every start: kept in the object store, never on the computer.
STORE_FILES = frozenset(
    {
        "/SOUL.md",
        "/AGENTS.md",
        "/MEMORY.md",
        "/USER.md",
        "/PROACTIVE.md",
        "/BOOTSTRAP.md",
        "/IDENTITY.md",
        "/TOOLS.md",
        "/HEARTBEAT.md",
        # Older workspaces keep these system files at the root instead of under .octop/.
        "/.bootstrapped",
        "/manifest.json",
    }
)
# ``/agents/`` holds the built-in sub-agent definitions, checked whenever a Bot is created.
STORE_DIRS = (
    "/.octop/",
    "/.octop-auth/",
    "/agents/",
    "/memory/",
    "/memories/",
    "/skills/",
    "/inbound/",
)


def on_store(path: str | None) -> bool:
    """Is this virtual path part of the Bot's context, kept in the object store?"""
    raw = "/" + (path or "").strip().replace("\\", "/").lstrip("/")
    if raw.startswith(WORKSPACE + "/"):
        raw = raw[len(WORKSPACE) :]
    raw = posixpath.normpath(raw)
    return raw in STORE_FILES or any(raw + "/" == d or raw.startswith(d) for d in STORE_DIRS)


class CloudComputer(BaseSandbox):
    def __init__(
        self,
        manager: ComputerManager,
        *,
        user_id: int,
        agent_id: str,
        store: BackendProtocol | None = None,
        root_dir: Path | None = None,
    ) -> None:
        self._manager = manager
        self._user_id = user_id
        self._agent_id = agent_id
        self._store = store
        self.sandbox_fs: bool = True
        self.virtual_mode: bool = True
        # The agent's host workspace: the harness then shows the model "/" as its
        # working directory (the computer's workspace), never the host path.
        self.root_dir: Path | None = root_dir

    def _stored(self, path: str | None) -> bool:
        return self._store is not None and on_store(path)

    def _seed(self, write: Any) -> None:
        """First start of this Bot's computer: copy its object-store files (not context) onto it."""
        if self._store is None:
            return
        found = self._store.glob("**/*", "/")
        for match in getattr(found, "matches", None) or []:
            path = str(match.get("path") or "")
            if not path or match.get("is_dir") or on_store(path):
                continue
            got = self._store.download_files([path])[0]
            if got.content is not None:
                write(self._map_path(path), got.content)

    @property
    def id(self) -> str:
        return f"computer-{self._agent_id}"

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        if self._manager.taken_over(self._agent_id, self._user_id):
            # Agent-facing: the user is signing in or solving a check on this computer.
            return ExecuteResponse(output=TAKEN_OVER, exit_code=1, truncated=False)
        try:
            exit_code, output = self._manager.run(
                self._agent_id,
                self._user_id,
                command,
                timeout or DEFAULT_COMMAND_TIMEOUT,
                seed=self._seed,
            )
        except OctopError as exc:
            if exc.code != ErrorCode.BOT_COMPUTER_BUSY:
                raise
            # Agent-facing: AGS is out of capacity even after pausing idle computers.
            return ExecuteResponse(output=NO_CAPACITY, exit_code=1, truncated=False)
        return ExecuteResponse(output=output, exit_code=exit_code, truncated=False)

    # -- path mapping ---------------------------------------------------------

    def _map_path(self, path: str | None) -> str:
        """Virtual agent path (``/SOUL.md``, ``notes/a.md``) → path on the computer."""
        raw = (path or "").strip().replace("\\", "/")
        if raw == WORKSPACE or raw.startswith(WORKSPACE + "/"):
            relative = raw[len(WORKSPACE) :]
        else:
            relative = raw
        mapped = posixpath.normpath(f"{WORKSPACE}/{relative.lstrip('/')}")
        # ``..`` never leaves the workspace through the file tools.
        return mapped if mapped == WORKSPACE or mapped.startswith(WORKSPACE + "/") else WORKSPACE

    def shell_path(self, path: str) -> str:
        return self._map_path(path)

    def _to_virtual_path(self, path: str) -> str:
        normalized = posixpath.normpath(path) if path else WORKSPACE
        if normalized == WORKSPACE:
            return "/"
        if normalized.startswith(WORKSPACE + "/"):
            return normalized[len(WORKSPACE) :]
        return path

    def _virtual(self, entry: Any) -> Any:
        if isinstance(entry, dict) and entry.get("path") is not None:
            return {**entry, "path": self._to_virtual_path(str(entry["path"]))}
        return entry

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> Any:
        if self._stored(file_path):
            assert self._store is not None
            return self._store.read(file_path, offset=offset, limit=limit)
        return super().read(self._map_path(file_path), offset=offset, limit=limit)

    def write(self, file_path: str, content: str) -> Any:
        if self._stored(file_path):
            assert self._store is not None
            return self._store.write(file_path, content)
        result = super().write(self._map_path(file_path), content)
        if result.path:
            result.path = self._to_virtual_path(result.path)
        return result

    def edit(
        self, file_path: str, old_string: str, new_string: str, replace_all: bool = False
    ) -> Any:
        if self._stored(file_path):
            assert self._store is not None
            return self._store.edit(file_path, old_string, new_string, replace_all=replace_all)
        result = super().edit(
            self._map_path(file_path), old_string, new_string, replace_all=replace_all
        )
        if result.path:
            result.path = self._to_virtual_path(result.path)
        return result

    def ls(self, path: str) -> Any:
        if self._stored(path):
            assert self._store is not None
            return self._store.ls(path)
        root = self._map_path(path) == WORKSPACE
        if (
            root
            and self._store is not None
            and not self._manager.is_running(self._agent_id, self._user_id)
        ):
            # Listing the workspace never wakes the computer: show what the store holds.
            return self._store.ls("/")
        result = super().ls(self._map_path(path))
        if result.entries:
            result.entries = [self._virtual(e) for e in result.entries]
        if root and self._store is not None:
            # The context lives in the store; list it beside the computer's own files.
            seen = {str(e.get("path")) for e in result.entries or []}
            extra = [
                e
                for e in (self._store.ls("/").entries or [])
                if on_store(str(e.get("path"))) and str(e.get("path")) not in seen
            ]
            result.entries = [*(result.entries or []), *extra]
        return result

    def glob(self, pattern: str, path: str | None = None) -> Any:
        if path is not None and self._stored(path):
            assert self._store is not None
            return self._store.glob(pattern, path)
        result = super().glob(pattern, self._map_path(path))
        if result.matches:
            result.matches = [self._virtual(m) for m in result.matches]
        return result

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        *,
        max_count: int | None = None,
    ) -> Any:
        if path is not None and self._stored(path):
            assert self._store is not None
            return self._store.grep(pattern, path=path, glob=glob, max_count=max_count)
        result = super().grep(pattern, path=self._map_path(path), glob=glob, max_count=max_count)
        if result.matches:
            result.matches = [self._virtual(m) for m in result.matches]
        return result

    # deepagents>=0.6.12 runs the async file tools through ``aexecute`` with the raw path,
    # bypassing the sync overrides above; route them through the mapped sync methods.
    async def als(self, path: str) -> Any:
        return await asyncio.to_thread(self.ls, path)

    async def aglob(self, pattern: str, path: str | None = None) -> Any:
        return await asyncio.to_thread(self.glob, pattern, path)

    async def agrep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        *,
        max_count: int | None = None,
    ) -> Any:
        return await asyncio.to_thread(self.grep, pattern, path, glob, max_count=max_count)

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> Any:
        return await asyncio.to_thread(self.read, file_path, offset, limit)

    async def awrite(self, file_path: str, content: str) -> Any:
        return await asyncio.to_thread(self.write, file_path, content)

    async def aedit(
        self, file_path: str, old_string: str, new_string: str, replace_all: bool = False
    ) -> Any:
        return await asyncio.to_thread(self.edit, file_path, old_string, new_string, replace_all)

    def delete(self, file_path: str) -> DeleteResult:
        if self._stored(file_path):
            assert self._store is not None
            return self._store.delete(file_path)
        mapped = self._map_path(file_path)
        if mapped == WORKSPACE:
            return DeleteResult(error="the workspace itself cannot be deleted")
        result = super().delete(mapped)
        if result.path:
            result.path = self._to_virtual_path(result.path)
        return result

    def mkdir_path(self, path: str) -> None:
        if self._stored(path):
            mkdir = getattr(self._store, "mkdir_path", None)
            if mkdir is not None:
                mkdir(path)
            return
        result = self.execute(f"mkdir -p {shlex.quote(self._map_path(path))}")
        if result.exit_code not in (0, None):
            raise OSError(result.output or f"mkdir failed for {path!r}")

    def delete_path(self, path: str) -> None:
        if self._stored(path):
            remove = getattr(self._store, "delete_path", None)
            if remove is not None:
                remove(path)
            else:
                assert self._store is not None
                self._store.delete(path)
            return
        mapped = self._map_path(path)
        if mapped == WORKSPACE:
            raise OSError("the workspace itself cannot be deleted")
        result = self.execute(f"rm -rf {shlex.quote(mapped)}")
        if result.exit_code not in (0, None):
            raise OSError(result.output or f"delete failed for {path!r}")

    def move_path(self, src: str, dest: str) -> None:
        store_move = getattr(self._store, "move_path", None)
        if self._stored(src) and self._stored(dest) and store_move is not None:
            store_move(src, dest)
            return
        if self._stored(src) or self._stored(dest):
            # Across the store and the computer: copy the bytes, then remove the source.
            got = self.download_files([src])[0]
            if got.content is None:
                raise OSError(got.error or f"move failed for {src!r}")
            sent = self.upload_files([(dest, got.content)])[0]
            if sent.error:
                raise OSError(sent.error)
            self.delete_path(src)
            return
        src_m, dest_m = self._map_path(src), self._map_path(dest)
        parent = shlex.quote(posixpath.dirname(dest_m))
        result = self.execute(f"mkdir -p {parent} && mv {shlex.quote(src_m)} {shlex.quote(dest_m)}")
        if result.exit_code not in (0, None):
            raise OSError(result.output or f"move failed for {src!r} -> {dest!r}")

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        responses: list[FileUploadResponse] = []
        for path, content in files:
            if self._stored(path):
                assert self._store is not None
                responses.extend(self._store.upload_files([(path, content)]))
                continue
            if self._manager.taken_over(self._agent_id, self._user_id):
                responses.append(FileUploadResponse(path=path, error=TAKEN_OVER))
                continue
            try:
                self._manager.write(
                    self._agent_id, self._user_id, self._map_path(path), content, seed=self._seed
                )
            except Exception as exc:  # noqa: BLE001 - reported per file, like the other sandboxes
                responses.append(FileUploadResponse(path=path, error=str(exc)))
            else:
                responses.append(FileUploadResponse(path=path, error=None))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for path in paths:
            if self._stored(path):
                assert self._store is not None
                responses.extend(self._store.download_files([path]))
                continue
            try:
                content = self._manager.read(
                    self._agent_id, self._user_id, self._map_path(path), seed=self._seed
                )
            except Exception as exc:  # noqa: BLE001 - reported per file
                responses.append(FileDownloadResponse(path=path, content=None, error=str(exc)))
                continue
            error = None if content is not None else FILE_NOT_FOUND
            responses.append(FileDownloadResponse(path=path, content=content, error=error))
        return responses

    def close(self) -> None:
        """The computer outlives the agent runtime; the reaper pauses it when idle."""
