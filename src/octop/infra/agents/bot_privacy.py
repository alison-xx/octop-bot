"""Private bot membership, retained directories, and workspace tool access."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langgraph.prebuilt.tool_node import ToolCallRequest

from octop.infra.agents.bot_workspace import chief_key, is_private_bot
from octop.infra.agents.settings.profile import parse_config_json
from octop.infra.agents.workspace.dir import workspace_dir_from_config
from octop.infra.errors import ErrorCode, OctopError

_PREFIX = "octop_bot:private_directory:"
_FILE_TOOLS = {"read_file", "write_file", "edit_file", "ls", "glob", "grep"}


def privacy_approvals(current: dict[str, Any], workspace: Path, description: str) -> dict[str, Any]:
    """Keep the user's ordinary gates, and review operations leaving a private workspace."""

    def outside_or_previously_gated(previous: Any) -> Callable[[Any], bool]:
        def required(request: Any) -> bool:
            args = request.tool_call.get("args") or {}
            target = args.get("file_path") or args.get("path")
            if not target or not (workspace / target).resolve().is_relative_to(workspace):
                return True
            if not previous:
                return False
            when = previous.get("when") if isinstance(previous, dict) else None
            return bool(when(request)) if when else True

        return required

    result = dict(current)
    for name in ("ask_agent", "execute", "write_file", "edit_file"):
        gate: dict[str, Any] = {
            "description": description,
            "allowed_decisions": ["approve", "reject"],
        }
        if name in {"write_file", "edit_file"}:
            gate["when"] = outside_or_previously_gated(current.get(name))
        result[name] = gate
    return result


def private_dirs(settings: Any) -> dict[str, dict[str, Any]]:
    return {
        key[len(_PREFIX) :]: json.loads(raw) for key, raw in settings.with_prefix(_PREFIX).items()
    }


def assert_new_workspace_available(services: Any, agent_id: str, workspace: Path) -> None:
    resolved = workspace.resolve()
    for reserved_id, record in private_dirs(services).items():
        root = Path(record["path"]).resolve()
        if (
            reserved_id == agent_id
            or resolved.is_relative_to(root)
            or root.is_relative_to(resolved)
        ):
            raise OctopError(ErrorCode.WORKSPACE_ROOT_RESTRICTED, "private bot directory")


def release_directory(services: Any, owner: int, agent_id: str) -> None:
    record = private_dirs(services.settings_repo).get(agent_id)
    if not record or record["owner"] != owner:
        raise OctopError(ErrorCode.NOT_FOUND, "unknown retained folder")
    if services.agent_repo.get(agent_id):
        raise OctopError(ErrorCode.FORBIDDEN, "turn off privacy on the active bot")
    services.settings_repo.delete(_PREFIX + agent_id)


def _update_privacy(services: Any, manager: Any, owner: int, agent_id: str, private: bool) -> bool:
    row = manager.get_row(agent_id)
    if row is None or row.user_id != owner or row.kind != "expert":
        raise OctopError(ErrorCode.AGENT_NOT_FOUND, "unknown personal bot")
    if is_private_bot(row) == private:
        return False
    if manager.is_agent_active(agent_id):
        raise OctopError(ErrorCode.AGENT_BUSY, "bot is running a turn")
    key = _PREFIX + agent_id
    cfg = parse_config_json(row.config_json)
    record = None
    if private:
        from octop.infra.bot_groups.service import list_groups

        if (
            services.settings_repo.get(chief_key(owner)) == agent_id
            or row.is_shared
            or any(agent_id in g.member_ids for g in list_groups(services, owner))
            or any(
                agent_id in manager.teams.member_ids(t.agent_id)
                for t in services.agent_repo.list_all()
                if t.kind == "team"
            )
        ):
            raise OctopError(
                ErrorCode.TEAM_MEMBER_INVALID, "remove this bot from teams and sharing first"
            )
        backend = cfg.get("backend") or {}
        if not isinstance(backend, dict) or backend.get("type") not in {
            None,
            "filesystem",
            "local_shell",
        }:
            raise OctopError(
                ErrorCode.WORKSPACE_OP_UNSUPPORTED, "private folders require local storage"
            )
        root = manager.resolve_workspace_dir(agent_id).resolve()
        others = [
            workspace_dir_from_config(
                parse_config_json(other.config_json),
                paths=services.paths,
                agent_id=other.agent_id,
                ensure=False,
            ).resolve()
            for other in services.agent_repo.list_all()
            if other.agent_id != agent_id
        ]
        others.extend(
            Path(p["path"])
            for other_id, p in private_dirs(services.settings_repo).items()
            if other_id != agent_id
        )
        if (
            root == Path(root.anchor)
            or root == Path.home()
            or services.paths.root.resolve().is_relative_to(root)
            or any(root.is_relative_to(p) or p.is_relative_to(root) for p in others)
        ):
            raise OctopError(
                ErrorCode.WORKSPACE_ROOT_RESTRICTED, "choose a dedicated private working folder"
            )
        record = json.dumps({"owner": owner, "path": str(root), "name": row.name})
        cfg["octop_bot"] = {"private": True}
    else:
        cfg.pop("octop_bot", None)
    if not services.agent_repo.set_bot_privacy(
        agent_id, row.config_json, json.dumps(cfg, ensure_ascii=False), key, record
    ):
        raise OctopError.localized(ErrorCode.AGENT_BUSY)
    return True


async def set_privacy(services: Any, manager: Any, owner: int, agent_id: str, private: bool) -> Any:
    if await asyncio.to_thread(_update_privacy, services, manager, owner, agent_id, private):
        await manager.reload(agent_id)
    return await asyncio.to_thread(manager.get_row, agent_id)


class PrivateDirectoryGuard(AgentMiddleware[Any, Any]):
    """Enforce retained directory access for ordinary Octop filesystem tools."""

    def __init__(
        self, settings: Any, agent_id: str, workspace: Path, backend_root: str | None
    ) -> None:
        self.settings = settings
        self.agent_id = agent_id
        self.workspace = workspace
        self.backend_root = Path(backend_root) if backend_root else workspace

    def check(self, call: Any) -> None:
        name = call.get("name")
        if name not in _FILE_TOOLS:
            return
        protected = private_dirs(self.settings)
        if not protected:
            return
        args = call.get("args") or {}
        value = str(args.get("file_path") or args.get("path") or ".")
        targets = [
            (self.workspace / value).resolve(),
            (self.backend_root / value.lstrip("/\\")).resolve(),
        ]
        recursive = name in {"glob", "grep"}
        for other_id, record in protected.items():
            if other_id == self.agent_id:
                continue
            root = Path(record["path"]).resolve()
            if any(
                p.is_relative_to(root) or (recursive and root.is_relative_to(p)) for p in targets
            ):
                raise OctopError(ErrorCode.FORBIDDEN, "private bot workspace")

    def wrap_tool_call(self, request: ToolCallRequest, handler: Callable[..., Any]) -> Any:
        self.check(request.tool_call)
        return handler(request)

    async def awrap_tool_call(
        self, request: ToolCallRequest, handler: Callable[..., Awaitable[Any]]
    ) -> Any:
        await asyncio.to_thread(self.check, request.tool_call)
        return await handler(request)
