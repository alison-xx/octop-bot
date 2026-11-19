"""Resolve the browser selected by an authenticated dashboard request."""

from typing import Any

from fastapi import Depends

from octop.api.common.agent import user_owns_agent
from octop.api.deps import current_user, get_server
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.browser_media import user_browser_profile


def owned_browser_profile(server: Any, user: Any, bot_id: str | None) -> str:
    if bot_id is not None:
        row = server.services.agent_repo.get(bot_id)
        if row is None or not user_owns_agent(row, user):
            raise OctopError(ErrorCode.AGENT_NOT_FOUND, "Bot not found", status=404)
    return user_browser_profile(user.id, bot_id)


def selected_profile(
    bot_id: str | None = None,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> str:
    return owned_browser_profile(server, user, bot_id)
