"""How many Bots and group chats one Octop Bot cloud account may own.

Hard ceilings for now, checked where every Bot and group is created (registry.create and
bot_groups.create_group), so no path can go around them. They apply to cloud tenants only:
Bots on this computer stay unlimited, as the pricing page says. Plan-based numbers come later.
"""

from __future__ import annotations

from typing import Any

from octop.infra.desktop import bot_cloud_enabled
from octop.infra.errors import ErrorCode, OctopError

MAX_BOTS = 50
MAX_GROUPS = 20


def cloud_tenant(user_repo: Any, user_id: int) -> bool:
    """A non-admin account on a cloud-mode server (bot.lynxce.cn)."""
    if not bot_cloud_enabled():
        return False
    user = user_repo.get(user_id)
    return user is not None and user.role != "admin"


def assert_bot_capacity(user_repo: Any, agent_repo: Any, user_id: int) -> None:
    if not cloud_tenant(user_repo, user_id):
        return
    owned = int(agent_repo.count_by_user(user_id, kind="expert"))
    if owned >= MAX_BOTS:
        raise OctopError.localized(
            ErrorCode.BOT_COUNT_LIMIT, details={"used": owned, "limit": MAX_BOTS}
        )


def assert_group_capacity(user_repo: Any, group_repo: Any, user_id: int) -> None:
    if not cloud_tenant(user_repo, user_id):
        return
    owned = len(group_repo.list_by_owner(user_id))
    if owned >= MAX_GROUPS:
        raise OctopError.localized(
            ErrorCode.BOT_GROUP_COUNT_LIMIT,
            details={"used": owned, "limit": MAX_GROUPS},
        )
