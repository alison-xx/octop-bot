"""Cloud mode (``OCTOP_BOT_CLOUD``): host-level surfaces are closed to tenants."""

from fastapi import Depends
from starlette.requests import HTTPConnection

from octop.api.deps import current_user, extract_raw_token, resolve_user_from_token
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


async def no_cloud_tenant_http(conn: HTTPConnection) -> None:
    """``no_cloud_tenant`` for routers that also hold WebSocket routes.

    HTTP requests are checked here; a WebSocket route checks ``is_cloud_tenant`` itself after
    its token handshake (a router dependency cannot read a WebSocket's token).
    """
    if conn.scope.get("type") != "http":
        return
    user = getattr(conn.state, "octop_user", None)
    if user is None:
        raw = extract_raw_token(
            authorization=conn.headers.get("authorization"),
            access_token=conn.query_params.get("access_token"),
        )
        if not raw:
            return  # the route's own authentication answers
        user = resolve_user_from_token(conn.app.state.octop_server, raw)
    if is_cloud_tenant(user):
        raise OctopError.localized(ErrorCode.FORBIDDEN)
