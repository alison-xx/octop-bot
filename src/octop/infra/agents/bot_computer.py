"""Expose the host's app-scoped desktop capability to an authenticated private chat."""

import asyncio
from typing import Any

from langchain_core.tools import StructuredTool
from langgraph.config import get_config

from octop.infra.control.desktop.bot_apps import Action, BotComputer
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError


def computer_tool(computer: BotComputer, repos: RepoBundle, bot: str, owner: int) -> StructuredTool:
    async def octop_computer(
        action: Action,
        app_id: str = "",
        pid: int = 0,
        window_id: int = 0,
        token: str = "",
        value: str = "",
        foreground: bool = False,
    ) -> Any:
        """Operate an application the user granted to this bot. List windows, then read its accessible
        elements with the exact app_id, pid and window_id. Use an observed element token to click
        or set_value in the background. Request foreground only after a background refusal when the
        user granted it. Read the window again to verify. Use handoff for login or human input.
        """
        ctx = get_config().get("configurable") or {}
        if (
            str(ctx.get("user")) != str(owner)
            or ctx.get("agent_id") != bot
            or ctx.get("octop_bot_browser") is not True
        ):
            raise OctopError.localized(ErrorCode.FORBIDDEN)
        from octop.infra.cloud.computers.remote import configured_target
        from octop.infra.desktop import bot_desktop_enabled

        if bot_desktop_enabled():
            from octop.infra.auth.lynxce_cloud import has_session

            row = await asyncio.to_thread(repos.agent_repo.get, bot)
            if (
                row is not None
                and configured_target(row) == "cloud"
                and await asyncio.to_thread(has_session, repos, owner)
            ):
                raise OctopError.localized(ErrorCode.FORBIDDEN)
        return await computer.run(
            repos, owner, bot, action, app_id, pid, window_id, token, value, foreground
        )

    return StructuredTool.from_function(coroutine=octop_computer)
