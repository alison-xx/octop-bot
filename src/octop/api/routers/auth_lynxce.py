"""Bot web build: sign in (and claim a fresh instance) with a Lynxce account."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from octop.api.deps import get_server, require_database
from octop.infra.auth import lynxce_cloud
from octop.infra.auth.lynxce_owner import OWNER_USERNAME, bind_owner, owner_binding
from octop.infra.auth.mfa.service import MfaService
from octop.infra.desktop import bot_web_enabled
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import Role
from octop.infra.utils.locale import normalize_locale, resolve_request_locale

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_FAILURES = 5
_FAILURE_WINDOW_SECONDS = 300
_failures: dict[str, list[float]] = {}
# One process serves an instance; serialize the "first sign-in claims it" step.
_claim_lock = asyncio.Lock()


class LynxceLoginBody(BaseModel):
    account: str = Field(min_length=1, max_length=200, description="Lynxce phone or email.")
    password: str = Field(min_length=1, max_length=4096)
    locale: str | None = Field(default=None, max_length=16)


class LynxceIdentityStatus(BaseModel):
    enabled: bool = Field(description="This build signs its owner in with a Lynxce account.")
    claimed: bool = Field(description="An owner Lynxce account is already bound.")


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _raise_if_throttled(ip: str) -> None:
    now = time.time()
    recent = [t for t in _failures.get(ip, []) if now - t < _FAILURE_WINDOW_SECONDS]
    _failures[ip] = recent
    if len(recent) >= _MAX_FAILURES:
        raise OctopError(
            ErrorCode.LOGIN_LOCKED,
            "too many Lynxce sign-in attempts",
            details={"retry_after_seconds": _FAILURE_WINDOW_SECONDS},
        )


def _require_enabled() -> None:
    if not bot_web_enabled():
        raise OctopError.localized(ErrorCode.FORBIDDEN)


@router.get(
    "/lynxce/status",
    summary="Lynxce sign-in availability",
    response_model=LynxceIdentityStatus,
)
async def lynxce_identity_status(server: Any = Depends(get_server)) -> LynxceIdentityStatus:
    """Whether this instance signs in with Lynxce, and whether an owner is bound yet."""
    if not bot_web_enabled() or not server.database_bound:
        return LynxceIdentityStatus(enabled=bot_web_enabled(), claimed=False)
    binding = await asyncio.to_thread(owner_binding, server.services.settings_repo)
    return LynxceIdentityStatus(enabled=True, claimed=binding is not None)


async def _claim(server: Any, account_id: str, display_name: str | None, locale: str) -> Any:
    """Create the owner for a fresh instance and finish first-run setup."""
    from octop.api.routers.setup import _bootstrap_default_agent  # noqa: PLC0415
    from octop.infra.db.repos.user_roles import ADMIN_USER_ROLE_ID, UserRoleRepo  # noqa: PLC0415
    from octop.infra.setup.completion import mark_setup_wizard_completed  # noqa: PLC0415

    admin_role = UserRoleRepo(server.services.db).get(ADMIN_USER_ROLE_ID)
    # The Lynxce account is the only way in; the local hash is a random value nobody types.
    user = await server.user_manager.create(
        username=OWNER_USERNAME,
        password=secrets.token_urlsafe(32) + "aA1!",
        role=Role.ADMIN,
        display_name=display_name,
        locale=locale,
        role_name=admin_role.user_role_name if admin_role is not None else "管理员",
    )
    await asyncio.to_thread(bind_owner, server.services.settings_repo, account_id, user.id)
    try:
        await _bootstrap_default_agent(server, user_id=user.id, locale=user.locale)
    except Exception as exc:  # pragma: no cover - same tolerance as /setup/finish
        logger.warning("could not auto-create default agent: %s", exc)
    mark_setup_wizard_completed(server.services.settings_repo, server.wizard_tokens)
    return user


@router.post("/lynxce/login", summary="Sign in with a Lynxce account")
async def lynxce_login(
    body: LynxceLoginBody, request: Request, server: Any = Depends(get_server)
) -> dict[str, Any]:
    """Verify a Lynxce account and issue a local access token for its bound owner.

    On a fresh Bot web instance the first verified account claims it: the owner
    is created, Chief is provisioned and setup closes. Afterwards only that same
    Lynxce account can sign in here. The Lynxce password is forwarded to Lynxce
    once and never stored.
    """
    _require_enabled()
    require_database(server)
    ip = _client_ip(request)
    _raise_if_throttled(ip)
    try:
        identity = await lynxce_cloud.verify_account(body.account, body.password)
    except OctopError as exc:
        if exc.code in {ErrorCode.AUTH_FAILED, ErrorCode.SLASH_BAD_ARGS}:
            _failures.setdefault(ip, []).append(time.time())
        raise
    assert identity.account_id is not None
    locale = normalize_locale(body.locale or resolve_request_locale(request))
    async with _claim_lock:
        settings = server.services.settings_repo
        binding = await asyncio.to_thread(owner_binding, settings)
        user = None
        if binding is not None and binding.account_id == identity.account_id:
            user = server.user_manager.get_by_id(binding.user_id)
        elif binding is None and server.user_manager.count() == 0:
            user = await _claim(server, identity.account_id, identity.display_name, locale)
        if user is None:
            _failures.setdefault(ip, []).append(time.time())
            raise OctopError.localized(ErrorCode.LYNXCE_OWNER_MISMATCH, status=403)
    server.services.user_repo.touch_last_login(user.id)
    server.services.audit_repo.write(actor=user.username, action="auth.lynxce_login")
    token, ttl = MfaService(server.services).mint_access_token(user)
    from octop.api.routers.auth import _user_json  # noqa: PLC0415

    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": ttl,
        "user": _user_json(user, locale=user.locale),
    }
