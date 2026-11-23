"""A Bot's cloud computer as a harness backend (``deepagents`` ``BaseSandbox``).

The sandbox is the workspace: file tools and ``execute`` act on the computer's own disk, which
persists while it is paused. Every call starts or resumes the computer first (and keeps it
paid for); ``close`` leaves it running, since the idle reaper pauses it.
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from deepagents.backends.protocol import (
    FILE_NOT_FOUND,
    INVALID_PATH,
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox

if TYPE_CHECKING:
    from octop.infra.cloud.computers.manager import ComputerManager

DEFAULT_COMMAND_TIMEOUT = 30 * 60


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
        exit_code, output = self._manager.run(
            self._agent_id, self._user_id, command, timeout or DEFAULT_COMMAND_TIMEOUT
        )
        return ExecuteResponse(output=output, exit_code=exit_code, truncated=False)

    def mkdir_path(self, path: str) -> None:
        result = self.execute(f"mkdir -p {shlex.quote(path)}")
        if result.exit_code not in (0, None):
            raise OSError(result.output or f"mkdir failed for {path!r}")

    def delete_path(self, path: str) -> None:
        result = self.execute(f"rm -rf {shlex.quote(path)}")
        if result.exit_code not in (0, None):
            raise OSError(result.output or f"delete failed for {path!r}")

    def move_path(self, src: str, dest: str) -> None:
        parent = shlex.quote(dest.rsplit("/", 1)[0] or "/")
        result = self.execute(f"mkdir -p {parent} && mv {shlex.quote(src)} {shlex.quote(dest)}")
        if result.exit_code not in (0, None):
            raise OSError(result.output or f"move failed for {src!r} -> {dest!r}")

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        responses: list[FileUploadResponse] = []
        for path, content in files:
            if not path.startswith("/"):
                responses.append(FileUploadResponse(path=path, error=INVALID_PATH))
                continue
            try:
                self._manager.write(self._agent_id, self._user_id, path, content)
            except Exception as exc:  # noqa: BLE001 - reported per file, like the other sandboxes
                responses.append(FileUploadResponse(path=path, error=str(exc)))
            else:
                responses.append(FileUploadResponse(path=path, error=None))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for path in paths:
            if not path.startswith("/"):
                responses.append(FileDownloadResponse(path=path, content=None, error=INVALID_PATH))
                continue
            try:
                content = self._manager.read(self._agent_id, self._user_id, path)
            except Exception as exc:  # noqa: BLE001 - reported per file
                responses.append(FileDownloadResponse(path=path, content=None, error=str(exc)))
                continue
            error = None if content is not None else FILE_NOT_FOUND
            responses.append(FileDownloadResponse(path=path, content=content, error=error))
        return responses

    def close(self) -> None:
        """The computer outlives the agent runtime; the reaper pauses it when idle."""
