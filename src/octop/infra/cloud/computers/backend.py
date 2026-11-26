"""A Bot's cloud computer as a harness backend (``deepagents`` ``BaseSandbox``).

The agent's ``/`` is the workspace folder on the computer's own disk (``WORKSPACE``), which
persists while it is paused; ``execute`` runs there with the whole computer (desktop, Chrome,
its own files) at hand. Path mapping follows octop-harness's Docker sandbox: file tools see
virtual paths, the shell sees real ones.

The Bot's context (SOUL, AGENTS, MEMORY and the other persona files, ``.octop/`` system files,
memory and skills) stays in the P1 object store: the harness
reads it at every start and new conversation, and that must never wake (and bill) a computer.
Only work on the computer starts it: ``execute`` and files outside those paths. The first time
a Bot's computer starts, the files the Bot already had in the object store are copied onto it.
``close`` leaves the computer running, since the idle reaper pauses it.

The Bot's deliverables (``generated/``: documents it writes, images and videos it makes;
``outbound/``: files it sends the user) are kept in the object store too, so chatting, file
cards and previews never wake the computer. They are mirrored onto the computer whenever it
starts or resumes and before each command, and what a command leaves there is copied back to
the store afterwards (``SHARED_DIRS``). Chat uploads in ``inbound/`` are copied onto the
computer in one direction so commands can open them. Deleting a file on one side does not delete the other.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import posixpath
import shlex
import threading
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

from octop.infra.cloud.computers.driver import WORKSPACE, ComputerDriver
from octop.infra.cloud.computers.manager import WAKE_COMMAND_TIMEOUT, ComputerUnavailable
from octop.infra.cloud.computers.office import OfficePreviewError, guest_preview
from octop.infra.errors import ErrorCode, OctopError

if TYPE_CHECKING:
    from pathlib import Path

    from octop.infra.cloud.computers.manager import ComputerIO, ComputerManager

logger = logging.getLogger(__name__)

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
# Deliverables: in the object store, mirrored onto the computer (see the module docstring).
SHARED_DIRS = ("/generated/", "/outbound/")
# ``/agents/`` holds the built-in sub-agent definitions, checked whenever a Bot is created.
STORE_DIRS = (
    "/.octop/",
    "/.octop-auth/",
    "/agents/",
    "/memory/",
    "/memories/",
    "/skills/",
    "/inbound/",
    *SHARED_DIRS,
)
# Bounds for mirroring the deliverables: files past them stay where they are.
MAX_SHARED_FILES = 500
MAX_SHARED_FILE_BYTES = 100 * 1024 * 1024
# Lists the computer's deliverables as "<size> <mtime> <path relative to WORKSPACE>".
_LIST_SHARED = (
    f"cd {shlex.quote(WORKSPACE)} 2>/dev/null && "
    + "find "
    + " ".join(d.strip("/") for d in SHARED_DIRS)
    + f" -type f -size -{MAX_SHARED_FILE_BYTES // 1024}k -printf '%s %T@ %p\\n' 2>/dev/null"
    + f" | head -n {MAX_SHARED_FILES}; true"
)


def on_store(path: str | None) -> bool:
    """Is this virtual path part of the Bot's context, kept in the object store?"""
    raw = "/" + (path or "").strip().replace("\\", "/").lstrip("/")
    if raw.startswith(WORKSPACE + "/"):
        raw = raw[len(WORKSPACE) :]
    raw = posixpath.normpath(raw)
    return raw in STORE_FILES or any(raw + "/" == d or raw.startswith(d) for d in STORE_DIRS)


def _listing(output: str) -> dict[str, tuple[int, float]]:
    """``_LIST_SHARED`` output → virtual path → (size, mtime)."""
    found: dict[str, tuple[int, float]] = {}
    for line in output.splitlines():
        size, _, rest = line.strip().partition(" ")
        mtime, _, relative = rest.partition(" ")
        try:
            found["/" + relative.strip().lstrip("./")] = (int(size), float(mtime))
        except ValueError:
            continue
    return found


def computer_off(workspace: Any, path: str, *, search: bool = False) -> bool:
    """Reading or writing ``path`` would wake this Bot's paused (or never started) computer.

    Dashboard and app requests check this first and answer ``BOT_COMPUTER_OFF`` instead: only
    the Bot's own work or the user opening the computer may start it.
    """
    backend = getattr(workspace, "backend", None)
    return isinstance(backend, CloudComputer) and backend.would_wake(path, search=search)


def left_on_computer(workspace: Any, path: str) -> bool:
    """``path`` is a deliverable the store lacks, and this Bot's computer, which may still hold
    it (made before deliverables were mirrored into the store), is off: once the computer
    starts, its deliverables are copied into the store."""
    backend = getattr(workspace, "backend", None)
    return isinstance(backend, CloudComputer) and backend.may_hold(path)


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
        # Store revisions and payload digests are separate: S3 lists encoded envelope sizes.
        self._pushed: dict[str, tuple[int | None, str]] = {}
        self._mirror_instance: str | None = None
        self._mirrored_digest: dict[str, bytes] = {}
        self._seen: dict[str, tuple[int, float]] = {}
        self._sync_lock = threading.Lock()
        if store is not None:
            manager.on_wake(agent_id, self._on_wake)

    def office_preview(self, path: str, digest: str) -> tuple[int, str]:
        """Verify a delivered revision and keep its thumbnail in this Bot's workspace."""
        mapped = self._map_path(path)
        key = self._to_virtual_path(mapped)
        if mapped == WORKSPACE or (
            on_store(key) and not key.startswith((*SHARED_DIRS, "/inbound/"))
        ):
            raise OfficePreviewError(
                "Save the Office deliverable in generated/ or outbound/ and send it again."
            )
        preview = f"/outbound/office-previews/{digest}.jpg"

        def check(driver: ComputerDriver, instance: str) -> tuple[int, str]:
            stored = None
            if self._store is not None and self._stored(key):
                item = self._store.download_files([key])[0]
                stored = item.content
                if stored is None or hashlib.sha256(stored).hexdigest() != digest:
                    raise OfficePreviewError(
                        "The saved document changed. Send the current revision again."
                    )
            pages, jpeg = guest_preview(driver, instance, mapped, digest, stored)
            if self._store is None:
                driver.write(instance, self._map_path(preview), jpeg)
            elif self._store.upload_files([(preview, jpeg)])[0].error:
                raise OfficePreviewError("The document opened, but its preview could not be saved.")
            return pages, preview.lstrip("/")

        try:
            return self._manager.use(self._agent_id, self._user_id, check, start=False)
        except ComputerUnavailable as exc:
            raise OfficePreviewError(
                "Office verification needs a running cloud computer handed back by the user."
            ) from exc

    def _stored(self, path: str | None) -> bool:
        return self._store is not None and on_store(path)

    def would_wake(self, path: str | None, *, search: bool = False) -> bool:
        """Is ``path`` on the computer (not the store) while the computer is off?

        Listing the workspace itself shows the store's copy, so it never wakes; a ``search``
        (glob, grep, a whole-workspace archive) from there does.
        """
        if self._stored(path) or (not search and self._map_path(path) == WORKSPACE):
            return False
        return not self._manager.is_running(self._agent_id, self._user_id)

    def may_hold(self, path: str | None) -> bool:
        """See :func:`left_on_computer`."""
        if self._store is None:
            return False
        raw = posixpath.normpath("/" + (path or "").strip().replace("\\", "/").lstrip("/"))
        if raw.startswith(WORKSPACE + "/"):
            raw = raw[len(WORKSPACE) :]
        if not any(raw.startswith(folder) for folder in SHARED_DIRS):
            return False
        record = self._manager.record(self._agent_id, self._user_id)
        return bool(record.instance_id) and not record.running

    # -- deliverables: the store's copy and the computer's --------------------

    def _store_entries(
        self, folders: tuple[str, ...], *, seed: bool = False
    ) -> dict[str, tuple[int | None, str]]:
        """List metadata only. The S3 backend's recursive glob downloads every object."""
        assert self._store is not None
        pending = [folder.rstrip("/") or "/" for folder in folders]
        found: dict[str, tuple[int | None, str]] = {}
        while pending:
            folder = pending.pop()
            listing = self._store.ls(folder)
            if listing.error and not listing.entries and "path_not_found" not in listing.error:
                raise OSError(listing.error)
            rows = listing.entries or []
            if folder == "/inbound" and len(rows) > MAX_SHARED_FILES:
                # Chat uploads are flat. Keep the newest available to commands at the limit.
                rows = sorted(
                    rows,
                    key=lambda row: (str(row.get("modified_at") or ""), row["path"]),
                    reverse=True,
                )
            for entry in rows:
                path = str(entry.get("path") or "").rstrip("/")
                if (
                    not path
                    or posixpath.normpath(path) != path
                    or posixpath.dirname(path) != folder
                    or (seed and on_store(path))
                ):
                    continue
                if entry.get("is_dir"):
                    pending.append(path)
                    continue
                found[path] = (entry.get("size"), str(entry.get("modified_at") or ""))
                if not seed and len(found) >= MAX_SHARED_FILES:
                    return found
        return found

    def _push(self, write: Any, entries: dict[str, tuple[int | None, str]]) -> bool:
        """Push changed objects. Store sizes include the JSON envelope on S3."""
        assert self._store is not None
        wrote = False
        for path, revision in entries.items():
            if revision[1] and self._pushed.get(path) == revision:
                continue
            got = self._store.download_files([path])[0]
            if got.content is None:
                continue
            if len(got.content) > MAX_SHARED_FILE_BYTES:
                self._pushed[path] = revision
                continue
            digest = hashlib.sha256(got.content).digest()
            if self._mirrored_digest.get(path) != digest:
                write(self._map_path(path), got.content)
                self._mirrored_digest[path] = digest
                wrote = True
            self._pushed[path] = revision
        return wrote

    def _pull(
        self,
        read: Any,
        found: dict[str, tuple[int, float]],
        *,
        known: dict[str, tuple[int | None, str]] | None = None,
    ) -> None:
        """Copy deliverables from the computer into the store.

        With a known store listing, only copy missing files (a computer from before mirroring);
        otherwise every file that changed since it was last seen.
        """
        assert self._store is not None
        for path, stamp in found.items():
            if known is not None and path in known:
                continue
            if known is None and self._seen.get(path) == stamp:
                continue
            data = read(self._map_path(path))
            if data is None:
                continue
            digest = hashlib.sha256(data).digest()
            if self._mirrored_digest.get(path) == digest:
                continue
            result = self._store.upload_files([(path, data)])[0]
            if result.error:
                raise OSError(result.error)
            self._mirrored_digest[path] = digest
            self._pushed.pop(path, None)

    def _on_wake(self, io: ComputerIO) -> None:
        """The computer just started or resumed: bring both copies of the deliverables level."""
        with self._sync_lock:
            found = _listing(io.run(_LIST_SHARED)[1])
            shared = self._store_entries(SHARED_DIRS)
            if self._mirror_instance != io.instance_id:
                self._pushed.clear()
                self._mirrored_digest.clear()
                self._mirror_instance = io.instance_id
            else:
                # On resume, preserve local edits to previously mirrored revisions.
                for path, revision in list(shared.items()):
                    if path not in found:
                        self._pushed.pop(path, None)
                        self._mirrored_digest.pop(path, None)
                    elif self._pushed.get(path) == revision and self._seen.get(path) != found[path]:
                        del shared[path]
            self._pull(io.read, found, known=shared)
            wrote = self._push(io.write, shared)
            self._push(io.write, self._store_entries(("/inbound/",)))
            self._seen = _listing(io.run(_LIST_SHARED)[1]) if wrote else found

    def _before_command(self) -> None:
        if self._store is None or not self._manager.is_running(self._agent_id, self._user_id):
            return  # starting it runs _on_wake

        def sync(driver: ComputerDriver, instance: str) -> None:
            with self._sync_lock:
                entries = self._store_entries(SHARED_DIRS)
                entries.update(self._store_entries(("/inbound/",)))
                self._push(lambda path, data: driver.write(instance, path, data), entries)

        self._manager.use(self._agent_id, self._user_id, sync, start=False)

    def _after_command(self) -> None:
        if self._store is None:
            return

        def sync(driver: ComputerDriver, instance: str) -> None:
            with self._sync_lock:
                code, output = driver.run(instance, _LIST_SHARED, WAKE_COMMAND_TIMEOUT)
                if code == 0:
                    found = _listing(output)
                    self._pull(lambda path: driver.read(instance, path), found)
                    self._seen = found

        try:
            self._manager.use(self._agent_id, self._user_id, sync, start=False)
        except Exception:  # noqa: BLE001 - the command worked; copied after the next one
            logger.warning("copying deliverables off the computer of %s failed", self._agent_id)

    def _seed(self, write: Any) -> None:
        """First start: skip context directories before descending into their contents."""
        if self._store is None:
            return
        for path in self._store_entries(("/",), seed=True):
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
            self._before_command()
            exit_code, output = self._manager.run(
                self._agent_id,
                self._user_id,
                command,
                timeout or DEFAULT_COMMAND_TIMEOUT,
                seed=self._seed,
            )
        except ComputerUnavailable:
            return ExecuteResponse(output=TAKEN_OVER, exit_code=1, truncated=False)
        except OctopError as exc:
            if exc.code != ErrorCode.BOT_COMPUTER_BUSY:
                raise
            # Agent-facing: AGS is out of capacity even after pausing idle computers.
            return ExecuteResponse(output=NO_CAPACITY, exit_code=1, truncated=False)
        self._after_command()
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
            with self._sync_lock:
                self._pushed.pop(file_path, None)
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
            with self._sync_lock:
                self._pushed.pop(file_path, None)
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
        if self._store is not None and self._map_path(path) == WORKSPACE:
            # Tool callers can also put the directory in the pattern: skills/**/SKILL.md.
            folder, _, subpattern = pattern.removeprefix("/").partition("/")
            if f"/{folder}/" in STORE_DIRS and subpattern and ".." not in subpattern.split("/"):
                return self._store.glob(subpattern, f"/{folder}")
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
                with self._sync_lock:
                    responses.extend(self._store.upload_files([(path, content)]))
                    self._pushed.pop(path, None)
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
