"""Independent Octop Bot surfaces reached through the local desktop shell."""

from typing import Annotated

from fastapi import Depends, Request

from octop.api.deps import current_user, get_server
from octop.infra.db.services import SharedServices
from octop.infra.desktop import bot_desktop_enabled
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.server import OctopServer
from octop.infra.users.identity import User


def _desktop_services(
    request: Request, server: Annotated[OctopServer, Depends(get_server)]
) -> SharedServices:
    if (
        not bot_desktop_enabled()
        or not request.client
        or request.client.host not in {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
    ):
        raise OctopError.localized(ErrorCode.FORBIDDEN)
    assert server.services is not None
    return server.services


Services = Annotated[SharedServices, Depends(_desktop_services)]
Owner = Annotated[User, Depends(current_user)]
