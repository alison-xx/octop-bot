"""Shell and explicit workspace transfers for a desktop Bot with a cloud computer."""

import asyncio
from collections.abc import Callable
from typing import Annotated, Any, Literal

import octop_harness.backends as harness_backends
from langchain_core.tools import StructuredTool
from octop_harness.backends.workspace import is_system_logical_entry
from pydantic import Field

from octop.infra.bot_tasks.approvals import ApprovalRules, ask
from octop.infra.cloud.computers.remote import (
    MAX_FILE_BYTES,
    RemoteComputerManager,
    RemoteDriver,
    transfer_path,
)
from octop.infra.errors import ErrorCode, OctopError


def workspace_tool(remote: RemoteComputerManager, workspace: Callable[[], Any]) -> StructuredTool:
    driver = RemoteDriver(remote)

    def cloud_computer_workspace(
        action: Literal["run", "upload", "download"],
        command: Annotated[str, Field(max_length=600)] = "",
        timeout: Annotated[int, Field(ge=1, le=300)] = 120,
        local_path: str = "",
        cloud_path: str = "",
    ) -> str:
        """Run a command on this Bot's cloud computer, or explicitly transfer one file between
        this Bot's local workspace and its cloud workspace. Both paths must be workspace-relative.
        The ordinary execute and file tools stay local. The user reviews the command or transfer.
        """
        if action == "run" and not command.strip():
            raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS)
        if action != "run":
            local_path, cloud_path = transfer_path(local_path), transfer_path(cloud_path)
        if action != "run" and is_system_logical_entry(local_path.split("/", 1)[0]):
            raise OctopError.localized(ErrorCode.FORBIDDEN)
        if action == "upload" and not callable(
            getattr(workspace(), "adownload_bytes_capped", None)
        ):
            raise OctopError.localized(ErrorCode.BOT_WORKSPACE_BOUNDED_READ_REQUIRED)
        detail = command if action == "run" else f"{action}: {local_path} ↔ {cloud_path}"
        if len(detail) > 600:
            raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS)
        allowed, note = ask(
            rules=ApprovalRules(remote.services.settings_repo),
            user_repo=remote.services.user_repo,
            agent_id=remote.agent_id,
            user_id=remote.user_id,
            category="upload" if action == "upload" else "other",
            target="Cloud computer",
            detail=detail,
            offer_always=False,
        )
        if not allowed:
            return note
        if remote.taken_over(remote.agent_id, remote.user_id):
            from octop.infra.cloud.computers.backend import TAKEN_OVER

            return TAKEN_OVER
        if action == "run":
            code, output = driver.run(remote.agent_id, command, timeout)
            return f"exit_code={code}\n{output}"
        if action == "upload":
            try:
                data = asyncio.run(
                    workspace().adownload_bytes_capped(local_path, max_bytes=MAX_FILE_BYTES)
                )
            except NotImplementedError:
                raise OctopError.localized(ErrorCode.BOT_WORKSPACE_BOUNDED_READ_REQUIRED) from None
            except ValueError as exc:
                if isinstance(exc, getattr(harness_backends, "DownloadTooLargeError", ())):
                    raise OctopError.localized(
                        ErrorCode.ATTACHMENT_TOO_LARGE, details={"max_mb": 50}, max_mb=50
                    ) from None
                raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS) from None
            except OSError:
                raise OctopError.localized(ErrorCode.FORBIDDEN) from None
            if data is None:
                raise OctopError.localized(ErrorCode.NOT_FOUND)
            driver.write(remote.agent_id, cloud_path, data)
        else:
            data = driver.read(remote.agent_id, cloud_path)
            try:
                workspace().upload_bytes(local_path, data)
            except (OSError, ValueError):
                raise OctopError.localized(ErrorCode.FORBIDDEN) from None
        return f"{action}: {len(data)} bytes"

    return StructuredTool.from_function(func=cloud_computer_workspace)
