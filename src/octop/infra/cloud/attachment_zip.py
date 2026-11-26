"""ZIP operations on a cloud Bot's stored chat files, independent of its desktop."""

from __future__ import annotations

import asyncio
import io
import stat
import zipfile
from pathlib import PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from langchain_core.tools import StructuredTool, ToolException

if TYPE_CHECKING:
    from octop_harness.backends.workspace import BackendWorkspace

_MAX_ENTRIES = 512
_MAX_BYTES = 64 * 1024 * 1024
_STORED = {"inbound", "generated", "outbound"}


def _relative(name: str) -> PurePosixPath:
    path = PurePosixPath(name.replace("\\", "/"))
    if not path.parts or path.is_absolute() or ".." in path.parts or PureWindowsPath(name).drive:
        raise ValueError("Use a relative file path inside the archive.")
    return path


def _read(
    workspace: BackendWorkspace, path: str, remaining: int, sizes: dict[str, dict[str, int]]
) -> bytes:
    parent = str(PurePosixPath(path).parent)
    if parent not in sizes:
        sizes[parent] = {
            str(entry["path"]).lstrip("/"): entry["size"]
            for entry in workspace.list_dir(parent) or []
            if isinstance(entry.get("size"), int)
        }
    if sizes[parent].get(path, 0) > remaining:
        raise ValueError("Selected files exceed the size limit.")
    payload = workspace.download_bytes(path)
    if payload is None:
        raise ValueError(f"File not found: {path}")
    if len(payload) > remaining:
        raise ValueError("Selected files exceed the size limit.")
    return payload


def _extract(workspace: BackendWorkspace, source: str, target: str) -> list[str]:
    data = _read(workspace, source, _MAX_BYTES, {})
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > _MAX_ENTRIES or sum(e.file_size for e in entries) > _MAX_BYTES:
            raise ValueError("ZIP exceeds 512 entries or 64 MiB expanded.")
        members: dict[PurePosixPath, bytes] = {}
        directories: set[PurePosixPath] = set()
        for entry in entries:
            path = _relative(entry.filename)
            if entry.flag_bits & 1 or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError("Encrypted and symbolic link entries are unsupported.")
            directories.update(path.parents)
            if entry.is_dir():
                directories.add(path)
                continue
            if path in members:
                raise ValueError("ZIP contains duplicate filenames.")
            members[path] = archive.read(entry)
        if not members or directories.intersection(members):
            raise ValueError("ZIP has no files or has conflicting file and directory names.")
    # Read and CRC-check all members before exposing any files.
    workspace.upload_many([(f"{target}/{path}", data) for path, data in members.items()])
    return [str(path) for path in members]


def _pack(workspace: BackendWorkspace, root: str, names: list[str], target: str) -> None:
    if not 1 <= len(names) <= _MAX_ENTRIES:
        raise ValueError("Specify between 1 and 512 relative filenames.")
    paths = [_relative(name) for name in names]
    if len(set(paths)) != len(paths):
        raise ValueError("ZIP filenames must be distinct.")
    buf = io.BytesIO()
    total = 0
    sizes: dict[str, dict[str, int]] = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
        for path in paths:
            data = _read(workspace, f"{root}/{path}", _MAX_BYTES - total, sizes)
            total += len(data)
            archive.writestr(str(path), data)
    workspace.upload_bytes(target, buf.getvalue())


def cloud_attachment_zip_tool(workspace: BackendWorkspace) -> StructuredTool:
    async def cloud_attachment_zip(
        action: Literal["extract", "pack"],
        source: str,
        members: list[str] | None = None,
        filename: str = "archive.zip",
    ) -> dict[str, object]:
        """Process chat ZIP files in Octop storage without a computer. Extract an uploaded ZIP
        by its workspace path. The receipt gives the output directory and relative member names
        for read_file. To pack, pass a source directory, chosen relative member names, and a ZIP
        filename. Send the returned ZIP path to the user. Limits: 512 entries, 64 MiB expanded.
        """
        try:
            path = _relative(source.removeprefix("/"))
            if path.parts[0] not in _STORED:
                raise ValueError("Use a path in inbound/, generated/ or outbound/.")
            target = f"generated/archives/{uuid4().hex}"
            if action == "extract":
                if len(path.parts) < 2 or path.suffix.lower() != ".zip":
                    raise ValueError("Select a ZIP attachment.")
                try:
                    names = await asyncio.to_thread(_extract, workspace, str(path), target)
                except (OSError, RuntimeError, ValueError, zipfile.BadZipFile):
                    # This invocation alone owns the unique destination, even after a partial write.
                    if await workspace.aexists(target):
                        await workspace.adelete(target)
                    raise
                return {"directory": target, "members": names, "count": len(names)}
            name = _relative(filename)
            if len(name.parts) != 1 or name.suffix.lower() != ".zip":
                raise ValueError("Choose a ZIP filename without directories.")
            output = f"{target}/{name}"
            await asyncio.to_thread(_pack, workspace, str(path), members or [], output)
            return {"path": output, "count": len(members or [])}
        except (OSError, RuntimeError, ValueError, zipfile.BadZipFile) as exc:
            raise ToolException(str(exc)) from exc

    return StructuredTool.from_function(coroutine=cloud_attachment_zip, handle_tool_error=True)
