"""Bot web build: sign in (and claim a fresh instance) with a Lynxce account."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import os
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from octop.api.deps import get_server, require_database
from octop.api.routers.setup import LOCAL_DESKTOP_USERNAME as LEGACY_OWNER_USERNAME
from octop.infra.auth import lynxce_cloud
from octop.infra.auth.lynxce_owner import OWNER_USERNAME, bind_owner, owner_binding
from octop.infra.auth.mfa.service import MfaService
from octop.infra.auth.tokens import PURPOSE_DESKTOP_REMOTE, sign_token
from octop.infra.cloud.bot_cloud import accounts as cloud_accounts
from octop.infra.desktop import bot_cloud_enabled, bot_web_enabled
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import Role
from octop.infra.utils.locale import normalize_locale, resolve_request_locale

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_FAILURES = 5
_FAILURE_WINDOW_SECONDS = 300
_failures: dict[str, list[float]] = {}
# Code sends per client address: Lynxce pays for the SMS, so a public instance must not relay floods.
_MAX_SENDS = 5
_SEND_WINDOW_SECONDS = 600
_sends: dict[str, list[float]] = {}
# One process serves an instance; serialize the "first sign-in claims it" step.
_claim_lock = asyncio.Lock()
_token_login_ips: dict[str, list[float]] = {}
_token_login_accounts: dict[str, list[float]] = {}


def _limit_token_login(bucket: dict[str, list[float]], key: str, limit: int) -> None:
    now = time.monotonic()
    recent = [t for t in bucket.get(key, []) if now - t < 60]
    bucket[key] = recent
    if len(recent) >= limit:
        raise OctopError.localized(ErrorCode.LOGIN_LOCKED)
    recent.append(now)


_BASE64URL = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
_MAX_TOKEN_LENGTH = 8192


def _is_session_token(token: str) -> bool:
    """Reject API keys and non-JWT shapes before contacting Lynxce."""
    if token.startswith("sk-") or len(token) > _MAX_TOKEN_LENGTH:
        return False
    parts = token.split(".")
    return len(parts) == 3 and all(part and set(part) <= _BASE64URL for part in parts)


def _session_payload(token: str) -> dict[str, Any] | None:
    try:
        segment = token.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return None
    return payload if isinstance(payload, dict) else None


def _valid_session_payload(payload: dict[str, Any] | None, *, require_src: bool) -> bool:
    return bool(
        payload is not None
        and payload.get("typ") == "access"
        and ("client" not in payload or payload["client"] == "web")
        and not any(key in payload for key in ("appId", "appVer", "desktopVer", "mobileVer"))
        and (not require_src or payload.get("src") == "octopbot")
    )


class LynxceLoginBody(BaseModel):
    account: str = Field(min_length=1, max_length=200, description="Lynxce phone or email.")
    password: str = Field(min_length=1, max_length=4096)
    locale: str | None = Field(default=None, max_length=16)
    local_password: str | None = Field(
        default=None,
        max_length=4096,
        description="Only for a Bot web instance set up with a local password before Lynxce "
        "sign-in: that password, once, to bind this Lynxce account to the existing owner.",
    )


class LynxceCodeBody(BaseModel):
    target: str = Field(min_length=1, max_length=256, description="Lynxce phone or email.")
    locale: str | None = Field(default=None, max_length=16)


class LynxceCodeSent(BaseModel):
    channel: Literal["phone", "email"] = Field(description="Where Lynxce sent the code.")


class LynxceCodeLoginBody(BaseModel):
    target: str = Field(min_length=1, max_length=256, description="Lynxce phone or email.")
    code: str = Field(min_length=1, max_length=16, description="Six-digit code Lynxce sent.")
    password: str | None = Field(
        default=None,
        max_length=4096,
        description="Only after a `LYNXCE_SIGNUP_PASSWORD_REQUIRED` reply: the sign-in password "
        "for the new Lynxce account (a new email needs one). Sent with the same code.",
    )
    locale: str | None = Field(default=None, max_length=16)
    local_password: str | None = Field(
        default=None,
        max_length=4096,
        description="Only for a Bot web instance set up with a local password before Lynxce "
        "sign-in: that password, once, to bind this Lynxce account to the existing owner.",
    )


class LynxceIdentityStatus(BaseModel):
    enabled: bool = Field(description="This build signs its owner in with a Lynxce account.")
    claimed: bool = Field(description="An owner Lynxce account is already bound.")
    legacy_owner: bool = Field(
        default=False,
        description="Not bound yet, but set up earlier with a local password: the first "
        "Lynxce sign-in must also give that password once.",
    )
    cloud: bool = Field(
        default=False,
        description="Octop Bot cloud: every Lynxce account signs in to an account of its own.",
    )


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
    if not (bot_web_enabled() or bot_cloud_enabled()):
        raise OctopError.localized(ErrorCode.FORBIDDEN)


@router.get(
    "/lynxce/status",
    summary="Lynxce sign-in availability",
    response_model=LynxceIdentityStatus,
)
async def lynxce_identity_status(server: Any = Depends(get_server)) -> LynxceIdentityStatus:
    """Whether this instance signs in with Lynxce, and whether an owner is bound yet."""
    if bot_cloud_enabled():
        return LynxceIdentityStatus(enabled=True, claimed=False, cloud=True)
    if not bot_web_enabled() or not server.database_bound:
        return LynxceIdentityStatus(enabled=bot_web_enabled(), claimed=False)
    binding = await asyncio.to_thread(owner_binding, server.services.settings_repo)
    legacy = binding is None and server.user_manager.get(LEGACY_OWNER_USERNAME) is not None
    return LynxceIdentityStatus(enabled=True, claimed=binding is not None, legacy_owner=legacy)


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
    if bot_cloud_enabled():
        return await _cloud_sign_in(
            server,
            request,
            body.locale,
            lambda: lynxce_cloud.open_password_session(body.account, body.password),
        )
    return await _sign_in(
        server,
        request,
        body.locale,
        lambda: lynxce_cloud.verify_account(body.account, body.password),
        body.local_password,
    )


@router.post(
    "/lynxce/code",
    summary="Send a Lynxce sign-in code",
    response_model=LynxceCodeSent,
    description=(
        "Lynxce texts or emails a six-digit code to the phone number or email. "
        "New Lynxce accounts are created on first sign-in and need no password. "
        "Rate-limited per client address."
    ),
)
async def lynxce_send_code(
    body: LynxceCodeBody, request: Request, server: Any = Depends(get_server)
) -> LynxceCodeSent:
    _require_enabled()
    require_database(server)
    ip = _client_ip(request)
    now = time.time()
    recent = [t for t in _sends.get(ip, []) if now - t < _SEND_WINDOW_SECONDS]
    if len(recent) >= _MAX_SENDS:
        _sends[ip] = recent
        raise OctopError.localized(ErrorCode.LYNXCE_CODE_THROTTLED, status=429)
    _sends[ip] = [*recent, now]
    locale = body.locale or resolve_request_locale(request)
    return LynxceCodeSent(channel=await lynxce_cloud.request_login_code(body.target, locale))


@router.post("/lynxce/code-login", summary="Sign in with a Lynxce one-time code")
async def lynxce_code_login(
    body: LynxceCodeLoginBody, request: Request, server: Any = Depends(get_server)
) -> dict[str, Any]:
    """Same as ``/lynxce/login``, proved with the code from ``/lynxce/code``.

    Works for Lynxce accounts that never set a password. A new email account needs one:
    Lynxce answers ``LYNXCE_SIGNUP_PASSWORD_REQUIRED``, and the client signs in again with
    the same code and ``password``.
    """
    if bot_cloud_enabled():
        return await _cloud_sign_in(
            server,
            request,
            body.locale,
            lambda: lynxce_cloud.open_code_session(body.target, body.code, body.password),
        )
    return await _sign_in(
        server,
        request,
        body.locale,
        lambda: lynxce_cloud.verify_account_code(body.target, body.code, body.password),
        body.local_password,
    )


class LynxceSessionLoginBody(BaseModel):
    refresh_token: str = Field(
        min_length=1, max_length=32768, description="Lynxce refresh token the desktop hands over."
    )
    locale: str | None = Field(default=None, max_length=16)


@router.post(
    "/lynxce/session-login",
    summary="Sign in with a Lynxce session handed over by the desktop app",
    description=(
        "Octop Bot cloud only. The desktop app moves its Lynxce sign-in here when it starts "
        "keeping its data in the cloud, so the user does not sign in twice. The session is "
        "renewed with Lynxce first, which proves it, and then kept like any cloud sign-in."
    ),
)
async def lynxce_session_login(
    body: LynxceSessionLoginBody, request: Request, server: Any = Depends(get_server)
) -> dict[str, Any]:
    if not bot_cloud_enabled():
        raise OctopError.localized(ErrorCode.FORBIDDEN)
    return await _cloud_sign_in(
        server,
        request,
        body.locale,
        lambda: lynxce_cloud.open_refresh_session(body.refresh_token),
    )


class LynxceTokenLoginBody(BaseModel):
    access_token: str = Field(
        min_length=1,
        max_length=32768,
        description="The desktop's own Lynxce access token. Only used to read which account it "
        "is; never kept, and the desktop keeps its own session.",
    )


@router.post(
    "/lynxce/token-login",
    summary="Sign the desktop app in to its cloud account with its Lynxce access token",
    description=(
        "Octop Bot cloud only. The desktop app, signed in with Lynxce, gets a token for this "
        "account here so its Bots can use cloud computers (shadow Bots, "
        "`/api/octop-bot/remote-bots`). Unlike `session-login`, the Lynxce session is not "
        "handed over. The account must have signed in here before (web, phones, or the "
        "desktop's one-time check), so this server has its own Lynxce session for billing; "
        "otherwise `BOT_CLOUD_SESSION_REQUIRED` (409): sign in once with "
        "`/lynxce/code-login` or `/lynxce/login`, then call this again."
    ),
)
async def lynxce_token_login(
    body: LynxceTokenLoginBody, request: Request, server: Any = Depends(get_server)
) -> dict[str, Any]:
    if not bot_cloud_enabled():
        raise OctopError.localized(ErrorCode.FORBIDDEN)
    require_database(server)
    _limit_token_login(_token_login_ips, _client_ip(request), 30)
    if not _is_session_token(body.access_token):
        raise OctopError.localized(ErrorCode.AUTH_FAILED, status=403)
    account = await _opened(
        request, lambda: lynxce_cloud.account_of_access_token(body.access_token)
    )
    payload = _session_payload(body.access_token)
    require_src = os.environ.get("OCTOP_TOKEN_LOGIN_REQUIRE_SRC", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not _valid_session_payload(payload, require_src=require_src):
        raise OctopError.localized(ErrorCode.AUTH_FAILED, status=403)
    if not require_src and payload is not None and "src" not in payload:
        from octop.infra.metrics import METRICS  # noqa: PLC0415

        METRICS.inc("token_login_without_src_total")
    _limit_token_login(_token_login_accounts, str(account), 10)
    services = server.services
    row = await asyncio.to_thread(cloud_accounts.tenant_for_account, services, account)
    if row is not None and row.disabled:
        raise OctopError.localized(ErrorCode.AUTH_FAILED, status=403)
    connected = (
        row is not None
        and (await asyncio.to_thread(lynxce_cloud.cloud_status, services, row.id)).connected
    )
    user = server.user_manager.get_by_id(row.id) if connected and row is not None else None
    if user is None:
        raise OctopError.localized(ErrorCode.BOT_CLOUD_SESSION_REQUIRED)
    from octop.api.routers.auth import _user_json  # noqa: PLC0415

    secret = services.secret_repo.get("jwt")
    if secret is None:
        raise OctopError.localized(ErrorCode.INTERNAL_ERROR)
    user_row = services.user_repo.get(user.id)
    token = sign_token(
        secret,
        sub=user.id,
        uname=user.username,
        role=user.role,
        purpose=PURPOSE_DESKTOP_REMOTE,
        ttl_seconds=3600,
        mfa_version=int(user_row.mfa_version),
        password_version=int(user_row.password_version),
    )
    services.audit_repo.write(actor=user.username, action="auth.lynxce_token_login")
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": 3600,
        "user": _user_json(user, locale=user.locale),
        "cloud": True,
    }


async def _opened[T](request: Request, opener: Callable[[], Awaitable[T]]) -> T:
    """Run a Lynxce sign-in, counting wrong passwords and codes toward the client's lockout."""
    ip = _client_ip(request)
    _raise_if_throttled(ip)
    try:
        return await opener()
    except OctopError as exc:
        if exc.code in {
            ErrorCode.AUTH_FAILED,
            ErrorCode.SLASH_BAD_ARGS,
            ErrorCode.LYNXCE_CODE_INVALID,
        }:
            _failures.setdefault(ip, []).append(time.time())
        raise


async def _cloud_sign_in(
    server: Any,
    request: Request,
    requested_locale: str | None,
    opener: Callable[[], Awaitable[lynxce_cloud.CloudSession]],
) -> dict[str, Any]:
    """Cloud mode: any Lynxce account signs in to (and on first use, gets) its own account."""
    require_database(server)
    session = await _opened(request, opener)
    locale = normalize_locale(requested_locale or resolve_request_locale(request))
    user = await cloud_accounts.provision(server.services, server.user_manager, session, locale)
    # Tells clients this server also keeps the Lynxce wallet for the account.
    return {**_issue(server, user, "auth.lynxce_cloud_login"), "cloud": True}


def _issue(server: Any, user: Any, action: str) -> dict[str, Any]:
    server.services.user_repo.touch_last_login(user.id)
    server.services.audit_repo.write(actor=user.username, action=action)
    token, ttl = MfaService(server.services).mint_access_token(user)
    from octop.api.routers.auth import _user_json  # noqa: PLC0415

    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": ttl,
        "user": _user_json(user, locale=user.locale),
    }


async def _sign_in(
    server: Any,
    request: Request,
    requested_locale: str | None,
    verify: Callable[[], Awaitable[lynxce_cloud.CloudAccountStatus]],
    local_password: str | None = None,
) -> dict[str, Any]:
    _require_enabled()
    require_database(server)
    ip = _client_ip(request)
    identity = await _opened(request, verify)
    assert identity.account_id is not None
    locale = normalize_locale(requested_locale or resolve_request_locale(request))
    async with _claim_lock:
        settings = server.services.settings_repo
        binding = await asyncio.to_thread(owner_binding, settings)
        user = None
        if binding is not None and binding.account_id == identity.account_id:
            user = server.user_manager.get_by_id(binding.user_id)
        elif binding is None and server.user_manager.count() == 0:
            user = await _claim(server, identity.account_id, identity.display_name, locale)
        elif binding is None and server.user_manager.get(LEGACY_OWNER_USERNAME) is not None:
            # Set up with a local password before Lynxce sign-in: proving that password once
            # binds this Lynxce account to the existing owner, data and all. Without it,
            # anyone with a Lynxce account could take the instance over.
            if not local_password:
                raise OctopError.localized(ErrorCode.LYNXCE_LEGACY_PASSWORD_REQUIRED)
            legacy = await server.user_manager.authenticate(LEGACY_OWNER_USERNAME, local_password)
            if legacy is None:
                _failures.setdefault(ip, []).append(time.time())
                raise OctopError.localized(ErrorCode.AUTH_FAILED)
            await asyncio.to_thread(bind_owner, settings, identity.account_id, legacy.id)
            server.services.audit_repo.write(
                actor=legacy.username, action="auth.lynxce_bound", target=identity.account_id
            )
            user = legacy
        if user is None:
            _failures.setdefault(ip, []).append(time.time())
            raise OctopError.localized(ErrorCode.LYNXCE_OWNER_MISMATCH, status=403)
    return _issue(server, user, "auth.lynxce_login")
