"""A Bot's cloud computer as a harness backend (``deepagents`` ``BaseSandbox``).

The agent's ``/`` is the workspace folder on the computer's own disk (``WORKSPACE``), which
persists while it is paused; ``execute`` runs there with the whole computer (desktop, Chrome,
its own files) at hand. Every call starts or resumes the computer first (and keeps it paid
for); ``close`` leaves it running, since the idle reaper pauses it. Path mapping follows
octop-harness's Docker sandbox: file tools see virtual paths, the shell sees real ones.
"""

from __future__ import annotations

import asyncio
import posixpath
import shlex
from typing import TYPE_CHECKING, Any

from deepagents.backends.protocol import (
    FILE_NOT_FOUND,
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox

from octop.infra.cloud.computers.driver import WORKSPACE

if TYPE_CHECKING:
    from octop.infra.cloud.computers.manager import ComputerManager

DEFAULT_COMMAND_TIMEOUT = 30 * 60
TAKEN_OVER = (
    "The user has taken over this computer (for example to sign in or solve a check). "
    "Do not use it now; tell the user what you need and wait until they hand it back."
)


class CloudComputer(BaseSandbox):
    def __init__(self, manager: ComputerManager, *, user_id: int, agent_id: str) -> None:
        self._manager = manager
        self._user_id = user_id
        self._agent_id = agent_id
        self.sandbox_fs: bool = True
        self.virtual_mode: bool = True

    @property
    def id(self) -> str:
        return f"computer-{self._agent_id}"

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        if self._manager.taken_over(self._agent_id, self._user_id):
            # Agent-facing: the user is signing in or solving a check on this computer.
            return ExecuteResponse(output=TAKEN_OVER, exit_code=1, truncated=False)
        exit_code, output = self._manager.run(
            self._agent_id, self._user_id, command, timeout or DEFAULT_COMMAND_TIMEOUT
        )
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
        return super().read(self._map_path(file_path), offset=offset, limit=limit)

    def write(self, file_path: str, content: str) -> Any:
        result = super().write(self._map_path(file_path), content)
        if result.path:
            result.path = self._to_virtual_path(result.path)
        return result

    def edit(
        self, file_path: str, old_string: str, new_string: str, replace_all: bool = False
    ) -> Any:
        result = super().edit(
            self._map_path(file_path), old_string, new_string, replace_all=replace_all
        )
        if result.path:
            result.path = self._to_virtual_path(result.path)
        return result

    def ls(self, path: str) -> Any:
        result = super().ls(self._map_path(path))
        if result.entries:
            result.entries = [self._virtual(e) for e in result.entries]
        return result

    def glob(self, pattern: str, path: str | None = None) -> Any:
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

    def mkdir_path(self, path: str) -> None:
        result = self.execute(f"mkdir -p {shlex.quote(self._map_path(path))}")
        if result.exit_code not in (0, None):
            raise OSError(result.output or f"mkdir failed for {path!r}")

    def delete_path(self, path: str) -> None:
        mapped = self._map_path(path)
        if mapped == WORKSPACE:
            raise OSError("the workspace itself cannot be deleted")
        result = self.execute(f"rm -rf {shlex.quote(mapped)}")
        if result.exit_code not in (0, None):
            raise OSError(result.output or f"delete failed for {path!r}")

    def move_path(self, src: str, dest: str) -> None:
        src_m, dest_m = self._map_path(src), self._map_path(dest)
        parent = shlex.quote(posixpath.dirname(dest_m))
        result = self.execute(f"mkdir -p {parent} && mv {shlex.quote(src_m)} {shlex.quote(dest_m)}")
        if result.exit_code not in (0, None):
            raise OSError(result.output or f"move failed for {src!r} -> {dest!r}")

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        responses: list[FileUploadResponse] = []
        for path, content in files:
            try:
                self._manager.write(self._agent_id, self._user_id, self._map_path(path), content)
            except Exception as exc:  # noqa: BLE001 - reported per file, like the other sandboxes
                responses.append(FileUploadResponse(path=path, error=str(exc)))
            else:
                responses.append(FileUploadResponse(path=path, error=None))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for path in paths:
            try:
                content = self._manager.read(self._agent_id, self._user_id, self._map_path(path))
            except Exception as exc:  # noqa: BLE001 - reported per file
                responses.append(FileDownloadResponse(path=path, content=None, error=str(exc)))
                continue
            error = None if content is not None else FILE_NOT_FOUND
            responses.append(FileDownloadResponse(path=path, content=content, error=error))
        return responses

    def close(self) -> None:
        """The computer outlives the agent runtime; the reaper pauses it when idle."""
