"""Cloud mode (``OCTOP_BOT_CLOUD``): host-level surfaces are closed to tenants."""

from fastapi import Depends

from octop.api.deps import current_user
from octop.infra.desktop import bot_cloud_enabled
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import User


def is_cloud_tenant(user: User) -> bool:
    return bot_cloud_enabled() and not user.is_admin


async def no_cloud_tenant(user: User = Depends(current_user)) -> User:
    """Router dependency: the host's own files, shells and processes are not for tenants."""
    if is_cloud_tenant(user):
        raise OctopError.localized(ErrorCode.FORBIDDEN)
    return user
