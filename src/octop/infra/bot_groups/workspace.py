"""Room artifacts and per-member execution state, scoped to the group owner."""

from __future__ import annotations

from pathlib import Path, PureWindowsPath
from typing import Any

from octop_harness.backends.workspace import BackendWorkspace

from octop.infra.backend.resolve_backend import resolve_octop_backend
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.resource_policy import (
    POLICY_WORKSPACE_ROOT_DIR,
    effective_workspace_root_dir,
)
from octop.infra.utils.ulid import new_ulid
from octop.infra.utils.user_downloads import sanitize_download_filename


def room_root(services: Any, user_id: int, group_id: str) -> Path:
    if not services.repos.bot_group_repo.get(group_id, user_id):
        raise OctopError(ErrorCode.TEAM_NOT_FOUND, "unknown bot group")
    allowed = effective_workspace_root_dir(
        services.user_policy_repo.get(user_id, POLICY_WORKSPACE_ROOT_DIR)
    )
    parent = Path(allowed) if allowed else services.paths.root
    return parent / "bot-groups" / str(user_id) / group_id


def room_files(root: Path) -> BackendWorkspace:
    spec = {"type": "filesystem", "virtual_mode": True, "root_dir": str(root)}
    return BackendWorkspace(resolve_octop_backend(spec, workspace_dir=root), root)


def artifact_path(root: Path, path: str) -> str:
    """Only expose room content; member checkpoints stay under the system directory."""
    relative = Path(path.replace("\\", "/"))
    if (
        relative.drive
        or relative.is_absolute()
        or any(ord(char) < 32 or ord(char) == 127 for char in path)
        or any(part.startswith(".") or ":" in part for part in relative.parts)
    ):
        raise OctopError(ErrorCode.FORBIDDEN, "invalid artifact path")
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise OctopError(ErrorCode.FORBIDDEN, "invalid artifact path")
    actual = resolved.relative_to(root.resolve())
    if any(part.startswith(".") for part in actual.parts):
        raise OctopError(ErrorCode.FORBIDDEN, "internal room file")
    return actual.as_posix()


def upload_artifact(root: Path, filename: str, data: bytes) -> dict[str, Any]:
    if (
        not filename
        or sanitize_download_filename(filename) != filename
        or filename.endswith(".")
        or PureWindowsPath(filename).is_reserved()
        or len(filename.encode("utf-8")) > 255
    ):
        raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS)
    rel = artifact_path(root, f"inbound/{new_ulid()}/{filename}")
    room_files(root).upload_bytes(rel, data)
    return {"name": filename, "path": rel, "is_dir": False}


def require_artifacts(services: Any, user_id: int, group_id: str, paths: list[str]) -> None:
    root = room_root(services, user_id, group_id)
    for path in paths:
        rel = artifact_path(root, path)
        if rel != path or not (root / rel).is_file():
            raise OctopError.localized(ErrorCode.NOT_FOUND)


def list_artifacts(services: Any, user_id: int, group_id: str, path: str) -> list[dict[str, Any]]:
    root = room_root(services, user_id, group_id)
    rel = artifact_path(root, path)
    if not root.is_dir() and rel == ".":
        return []
    if not (root / rel).is_dir():
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    entries = room_files(root).list_dir(rel) or []
    result = []
    for item in entries:
        child = str(item.get("path", "")) if isinstance(item, dict) else ""
        if not child:
            continue
        try:
            visible = artifact_path(root, child)
        except OctopError:
            continue
        result.append(
            {"name": Path(visible).name, "path": visible, "is_dir": bool(item.get("is_dir"))}
        )
    return result


def download_artifact(services: Any, user_id: int, group_id: str, path: str) -> tuple[str, bytes]:
    root = room_root(services, user_id, group_id)
    rel = artifact_path(root, path)
    if not (root / rel).is_file():
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    data = room_files(root).download_bytes(rel)
    if data is None:
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    return Path(rel).name, data
