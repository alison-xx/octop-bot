"""Lynxce end-user cloud sessions, separate from the personal model OAuth grant."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Coroutine, Mapping
from contextlib import suppress
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal
from uuid import uuid4

import httpx
from filelock import AsyncFileLock
from pydantic import BaseModel

from octop.infra.crypto.fernet import decrypt_json, encrypt_json
from octop.infra.db.services import SharedServices
from octop.infra.desktop import bot_cloud_enabled, bot_desktop_enabled
from octop.infra.errors import ErrorCode, OctopError

logger = logging.getLogger(__name__)

_ORIGIN = "https://api.lynxce.cn"
_ID = r"(?!\.{1,2}(?:/|$))[A-Za-z0-9_.-]{1,256}"
_WEB_ID = r"[A-Za-z0-9._:-]{4,96}"
CHECKOUT_PATH = "/api/billing/recharge/checkout-link"
WORKBUDDY_SESSION_PATH = "/api/oauth/workbuddy/session"
# Lynxce's WorkBuddy hand-off code: "wb-handoff." + base64url payload + "." + HMAC-SHA256.
_HANDOFF = re.compile(r"wb-handoff\.[A-Za-z0-9_-]{16,1024}\.[A-Za-z0-9_-]{43}")
_READS = {
    "/api/user/quota": set(),
    "/api/user/cloud-work/capabilities": set(),
    "/api/user/cloud-work/tasks": {"sessionId"},
    "/api/user/web-chat-sessions": {"limit", "cursor"},
    "/api/user/scheduled-tasks": set(),
}
_READ_DETAIL = re.compile(rf"/api/user/(?:web-chat-sessions/{_WEB_ID}|scheduled-tasks/{_ID})")
_WRITES = re.compile(
    rf"/api/user/(?:cloud-work/tasks(?:/{_ID}/actions)?|scheduled-tasks(?:/{_ID}/enabled)?|web-chat-sessions/{_WEB_ID}/items)"
)


class CloudAccountStatus(BaseModel):
    connected: bool = False
    account_id: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None


@dataclass(frozen=True)
class _Grant:
    account_id: str
    display_name: str | None
    binding: str
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    # None: not read from Lynxce yet (logins saved before the avatar was kept); "": no avatar.
    avatar_url: str | None = None

    def status(self) -> CloudAccountStatus:
        return CloudAccountStatus(
            connected=True,
            account_id=self.account_id,
            display_name=self.display_name,
            avatar_url=self.avatar_url or None,
        )


def _enabled() -> bool:
    """The desktop app keeps a Lynxce session per local user; so does cloud mode, per tenant."""
    return bot_desktop_enabled() or bot_cloud_enabled()


def _key(user_id: int) -> str:
    return f"lynxce.cloud.user.{user_id}"


def _load(services: SharedServices, user_id: int) -> _Grant | None:
    repo = services.secret_repo
    key = _key(user_id)
    blob = repo.get(key)
    return _Grant(**decrypt_json(repo, key + ".fernet", blob)) if blob else None


def _save(services: SharedServices, user_id: int, grant: _Grant) -> None:
    repo = services.secret_repo
    key = _key(user_id)
    repo.put(key, encrypt_json(repo, key + ".fernet", asdict(grant)))
    # The local owner can be removed during an upstream login/refresh. Its deletion
    # transaction clears existing keys; also clear a write that arrived afterwards.
    if services.user_repo.get(user_id) is None:
        repo.delete(key)
        repo.delete(key + ".fernet")
        raise OctopError.localized(ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED)


def cloud_status(services: SharedServices, user_id: int) -> CloudAccountStatus:
    """Read the locally saved identity without contacting the cloud."""
    grant = _load(services, user_id) if _enabled() else None
    return grant.status() if grant else CloudAccountStatus()


def _avatar(profile: dict[str, Any]) -> str:
    value = profile.get("avatarUrl")
    if isinstance(value, str) and value.startswith("https://") and len(value) <= 2048:
        return value
    return ""


async def cloud_account(services: SharedServices, user_id: int) -> CloudAccountStatus:
    """The saved identity; a login saved before avatars were kept reads its avatar once."""
    grant = await asyncio.to_thread(_load, services, user_id) if _enabled() else None
    if grant is None or grant.avatar_url is not None:
        return grant.status() if grant else CloudAccountStatus()
    async with _lock(services, user_id):
        current = await asyncio.to_thread(_load, services, user_id)
        if current is None or current.binding != grant.binding or current.avatar_url is not None:
            return current.status() if current else CloudAccountStatus()
        try:
            profile = await _send("GET", "/api/user/profile", bearer=current.access_token)
        except _UpstreamFailure:
            # An expired token is renewed by the next cloud request; show initials until then.
            return current.status()
        if not isinstance(profile, dict) or profile.get("id") != current.account_id:
            return current.status()
        updated = replace(current, avatar_url=_avatar(profile))
        await _finish(asyncio.to_thread(_save, services, user_id, updated))
        return updated.status()


def _lock(services: SharedServices, user_id: int) -> AsyncFileLock:
    return AsyncFileLock(services.paths.root / f".lynxce-cloud-{user_id}.lock")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(45, connect=10), follow_redirects=False, trust_env=False
    )


async def _finish[T](operation: Coroutine[Any, Any, T]) -> T:
    """Do not release the account lock while a cancelled request's grant write is still running."""
    task = asyncio.create_task(operation)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


class _UpstreamFailure(Exception):
    def __init__(self, status: int):
        self.status = status


def _rejected(status: int) -> OctopError:
    if status == 402:
        return OctopError.localized(ErrorCode.BOT_CLOUD_CREDITS_REQUIRED)
    if status == 404:
        return OctopError.localized(ErrorCode.NOT_FOUND)
    if status in {400, 403, 409, 422, 429}:
        return OctopError.localized(ErrorCode.BOT_CLOUD_REQUEST_REJECTED, status=status)
    return OctopError.localized(ErrorCode.NETWORK_ERROR)


async def _send(
    method: str,
    path: str,
    *,
    bearer: str | None = None,
    json: dict[str, Any] | None = None,
    params: Mapping[str, str | int] | None = None,
    headers: Mapping[str, str] | None = None,
) -> Any:
    # 'web' is Lynxce's supported multi-session channel. Exchanging a desktop auth code
    # would revoke the user's existing Lynxce desktop session and its API keys.
    sent = {**(headers or {}), "Accept": "application/json", "X-Lynxce-Client": "web"}
    if bearer:
        sent["Authorization"] = f"Bearer {bearer}"
    try:
        async with _client() as client:
            response = await client.request(
                method, _ORIGIN + path, headers=sent, json=json, params=params
            )
    except httpx.HTTPError:
        raise _UpstreamFailure(502) from None
    if not response.is_success:
        raise _UpstreamFailure(response.status_code)
    try:
        body = response.json()
    except ValueError:
        raise _UpstreamFailure(502) from None
    if (
        not isinstance(body, dict)
        or type(body.get("code")) is not int
        or body["code"] != 0
        or "data" not in body
    ):
        raise _UpstreamFailure(502)
    return body["data"]


def _token(data: Any, name: str) -> str:
    value = data.get(name) if isinstance(data, dict) else None
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 32768
        or not value.isascii()
        or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise OctopError.localized(ErrorCode.NETWORK_ERROR)
    return value


async def _session_login(path: str, body: dict[str, str]) -> _Grant:
    """Open a Lynxce 'web' session through one of its sign-in endpoints."""
    try:
        data = await _send("POST", path, json=body)
    except _UpstreamFailure as exc:
        if exc.status in {401, 403}:
            raise OctopError.localized(ErrorCode.AUTH_FAILED, status=403) from None
        raise _rejected(exc.status) from None
    profile = data.get("user") if isinstance(data, dict) else None
    if (
        not isinstance(profile, dict)
        or not isinstance(profile.get("id"), str)
        or not profile["id"].strip()
    ):
        raise OctopError.localized(ErrorCode.NETWORK_ERROR)
    name = profile.get("displayName")
    return _Grant(
        profile["id"],
        name if isinstance(name, str) else None,
        uuid4().hex,
        _token(data, "accessToken"),
        _token(data, "refreshToken"),
        _avatar(profile),
    )


async def _password_login(account: str, password: str) -> _Grant:
    account = account.strip()
    if not (1 <= len(account) <= 200 and 8 <= len(password) <= 4096):
        raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS, status=422)
    return await _session_login(
        "/api/auth/password-login", {"account": account, "password": password}
    )


_EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{1,63}")
_PHONE = re.compile(r"\+?[0-9][0-9 -]{5,30}")
_CODE = re.compile(r"[0-9]{6}")


CodeChannel = Literal["phone", "email"]


def code_target(target: str) -> tuple[CodeChannel, str]:
    """Classify a Lynxce sign-in target as ``("email", …)`` or ``("phone", …)``.

    Lynxce normalizes phone numbers itself; this only rejects input it would refuse.
    """
    target = target.strip()
    if "@" in target:
        if _EMAIL.fullmatch(target):
            return "email", target
    elif _PHONE.fullmatch(target):
        return "phone", target
    raise OctopError.localized(ErrorCode.LYNXCE_CODE_TARGET_INVALID, status=422)


async def request_login_code(target: str, locale: str | None = None) -> CodeChannel:
    """Ask Lynxce to text or email a one-time sign-in code. Returns ``"phone"`` or ``"email"``.

    New Lynxce users are created on first code sign-in and need no password.
    """
    kind, value = code_target(target)
    body: dict[str, str] = {kind: value}
    if kind == "email":
        body["locale"] = "en" if (locale or "").lower().startswith("en") else "zh-CN"
    try:
        await _send("POST", f"/api/auth/{kind}-code", json=body)
    except _UpstreamFailure as exc:
        if exc.status == 429:
            raise OctopError.localized(ErrorCode.LYNXCE_CODE_THROTTLED, status=429) from None
        if exc.status in {400, 422}:
            raise OctopError.localized(ErrorCode.LYNXCE_CODE_TARGET_INVALID, status=422) from None
        raise _rejected(exc.status) from None
    return kind


async def _code_login(target: str, code: str) -> _Grant:
    kind, value = code_target(target)
    code = code.strip()
    if not _CODE.fullmatch(code):
        raise OctopError.localized(ErrorCode.LYNXCE_CODE_INVALID, status=401)
    try:
        return await _session_login(f"/api/auth/{kind}-login", {kind: value, "code": code})
    except OctopError as exc:
        if exc.code is ErrorCode.AUTH_FAILED:
            raise OctopError.localized(ErrorCode.LYNXCE_CODE_INVALID, status=401) from None
        raise


async def verify_account(account: str, password: str) -> CloudAccountStatus:
    """Prove ownership of a Lynxce account without keeping its session.

    Used as the sign-in identity of the Bot web build. The upstream session opened
    by the check is closed right away; only the stable account id is returned.
    """
    return await _verified(await _password_login(account, password))


async def verify_account_code(target: str, code: str) -> CloudAccountStatus:
    """Same as :func:`verify_account`, proved with a one-time code instead of a password."""
    return await _verified(await _code_login(target, code))


async def _verified(grant: _Grant) -> CloudAccountStatus:
    with suppress(_UpstreamFailure):
        await _send("POST", "/api/auth/logout", bearer=grant.access_token, json={})
    return grant.status()


async def login_cloud(
    services: SharedServices, user_id: int, account: str, password: str
) -> CloudAccountStatus:
    if not _enabled():
        raise OctopError.localized(ErrorCode.FORBIDDEN)
    async with _lock(services, user_id):
        grant = await _password_login(account, password)
        await _finish(asyncio.to_thread(_save, services, user_id, grant))
        return grant.status()


async def login_cloud_code(
    services: SharedServices, user_id: int, target: str, code: str
) -> CloudAccountStatus:
    """Sign in with a one-time code texted or emailed by Lynxce (works for password-less accounts)."""
    if not _enabled():
        raise OctopError.localized(ErrorCode.FORBIDDEN)
    async with _lock(services, user_id):
        grant = await _code_login(target, code)
        await _finish(asyncio.to_thread(_save, services, user_id, grant))
        return grant.status()


async def login_cloud_workbuddy(
    services: SharedServices, user_id: int, handoff_code: str
) -> CloudAccountStatus:
    """Sign in with the one-time code Lynxce issues after a WorkBuddy authorization.

    The desktop shell captures the code from Lynxce's landing page before that page
    can spend it. The account is the Lynxce account bound to the WorkBuddy identity.
    """
    if not _enabled():
        raise OctopError.localized(ErrorCode.FORBIDDEN)
    if not _HANDOFF.fullmatch(handoff_code):
        raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS, status=422)
    async with _lock(services, user_id):
        grant = await _session_login(WORKBUDDY_SESSION_PATH, {"handoffCode": handoff_code})
        await _finish(asyncio.to_thread(_save, services, user_id, grant))
        return grant.status()


async def logout_cloud(
    services: SharedServices, user_id: int, *, expected_account_id: str | None = None
) -> CloudAccountStatus:
    if not _enabled():
        raise OctopError.localized(ErrorCode.FORBIDDEN)
    initial = await asyncio.to_thread(_load, services, user_id)
    if initial is None:
        return CloudAccountStatus()
    if expected_account_id is not None and expected_account_id != initial.account_id:
        raise OctopError.localized(ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED)
    async with _lock(services, user_id):
        grant = await asyncio.to_thread(_load, services, user_id)
        if grant:
            if initial.binding != grant.binding:
                raise OctopError.localized(ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED)
            await _finish(asyncio.to_thread(services.secret_repo.delete, _key(user_id)))
            # Local sign-out is durable even if Lynxce is temporarily unavailable.
            with suppress(_UpstreamFailure):
                await _send("POST", "/api/auth/logout", bearer=grant.access_token, json={})
    return CloudAccountStatus()


async def _refresh(services: SharedServices, user_id: int, grant: _Grant) -> _Grant:
    try:
        data = await _send("POST", "/api/auth/refresh", json={"refreshToken": grant.refresh_token})
        access = _token(data, "accessToken")
        profile = await _send("GET", "/api/user/profile", bearer=access)
        if not isinstance(profile, dict) or not isinstance(profile.get("id"), str):
            raise OctopError.localized(ErrorCode.NETWORK_ERROR)
        if profile["id"] != grant.account_id:
            raise _UpstreamFailure(403)
    except _UpstreamFailure as exc:
        if exc.status in {401, 403}:
            await asyncio.to_thread(services.secret_repo.delete, _key(user_id))
            raise OctopError.localized(ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED) from None
        raise _rejected(exc.status) from None
    refresh = _token(data, "refreshToken") if "refreshToken" in data else grant.refresh_token
    updated = replace(
        grant, access_token=access, refresh_token=refresh, avatar_url=_avatar(profile)
    )
    await asyncio.to_thread(_save, services, user_id, updated)
    return updated


def _allowed(method: str, path: str, params: Mapping[str, str | int]) -> bool:
    # Web history identifiers support a literal or URL-encoded colon (e.g. cowork:uuid).
    path = path.replace("%3A", ":").replace("%3a", ":")
    if method == "POST":
        return not params and (path == CHECKOUT_PATH or _WRITES.fullmatch(path) is not None)
    if method != "GET":
        return False
    if path in _READS:
        return _READS[path].issuperset(params)
    match = _READ_DETAIL.fullmatch(path)
    return match is not None and not (
        set(params) - ({"runs"} if path.startswith("/api/user/scheduled-tasks/") else set())
    )


def _allowed_action(payload: dict[str, Any]) -> bool:
    request_id = payload.get("requestId")
    if not isinstance(request_id, str) or not re.fullmatch(
        r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", request_id
    ):
        return False
    if payload.get("action") == "cancel":
        return set(payload) == {"action", "requestId"}
    return (
        payload.get("action") == "input"
        and set(payload) == {"action", "requestId", "text"}
        and isinstance(payload["text"], str)
    )


async def request_cloud(
    services: SharedServices,
    user_id: int,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    params: Mapping[str, str | int] | None = None,
    expected_account_id: str | None = None,
) -> Any:
    """Invoke one supported end-user operation as the account that initiated this request."""
    if (
        not _enabled()
        or not _allowed(method, path, params or {})
        or (method == "GET" and json is not None)
        or (path == CHECKOUT_PATH and (json is not None or not expected_account_id))
        or (path.endswith("/actions") and not _allowed_action(json or {}))
    ):
        raise OctopError.localized(ErrorCode.FORBIDDEN)
    initial = await asyncio.to_thread(_load, services, user_id)
    if not initial or (
        expected_account_id is not None and initial.account_id != expected_account_id
    ):
        raise OctopError.localized(ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED)
    async with _lock(services, user_id):
        grant = await asyncio.to_thread(_load, services, user_id)
        if not grant or grant.binding != initial.binding:
            raise OctopError.localized(ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED)
        try:
            return await _send(method, path, bearer=grant.access_token, json=json, params=params)
        except _UpstreamFailure as exc:
            if exc.status != 401:
                raise _rejected(exc.status) from None
        # Keep the lock until rotation has been recorded, even if this view closes.
        grant = await _finish(_refresh(services, user_id, grant))
        try:
            return await _send(method, path, bearer=grant.access_token, json=json, params=params)
        except _UpstreamFailure as exc:
            if exc.status == 401:
                await _finish(asyncio.to_thread(services.secret_repo.delete, _key(user_id)))
                raise OctopError.localized(ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED) from None
            raise _rejected(exc.status) from None


# Cloud mode (OCTOP_BOT_CLOUD): signing in to the server *is* signing in to Lynxce, and the
# session is kept for the wallet, recharge and the tenant's model key.

CloudSession = _Grant


async def open_password_session(account: str, password: str) -> CloudSession:
    return await _password_login(account, password)


async def open_code_session(target: str, code: str) -> CloudSession:
    return await _code_login(target, code)


async def discard_session(session: CloudSession) -> None:
    """Close a sign-in that will not be kept (best effort), so it does not stay open upstream."""
    with suppress(_UpstreamFailure):
        await _send("POST", "/api/auth/logout", bearer=session.access_token, json={})


async def keep_session(services: SharedServices, user_id: int, session: CloudSession) -> None:
    """Store a fresh sign-in for this tenant, replacing (and closing) the previous one."""
    async with _lock(services, user_id):
        previous = await asyncio.to_thread(_load, services, user_id)
        await _finish(asyncio.to_thread(_save, services, user_id, session))
    if previous is not None and previous.binding != session.binding:
        with suppress(_UpstreamFailure):
            await _send("POST", "/api/auth/logout", bearer=previous.access_token, json={})


_IAP_HEADERS = {"X-Lynxce-Iap-App": "cn.lynxce.octopbot"}
# What cloud mode may do with a tenant's stored Lynxce session, besides request_cloud.
_TENANT_CALLS: dict[tuple[str, str], dict[str, str]] = {
    ("POST", "/api/user/personal-api-keys"): {},
    ("POST", "/api/user/account/deletion-request"): {},
    ("GET", "/api/billing/app/recharge-packages"): _IAP_HEADERS,
    ("POST", "/api/billing/apple/purchase-intents"): _IAP_HEADERS,
    ("POST", "/api/billing/apple/transactions"): _IAP_HEADERS,
    # Cloud computers: minutes reserved before running, settled by the second at pause.
    ("POST", "/api/billing/octop-bot/compute/reserve"): {},
    ("POST", "/api/billing/octop-bot/compute/settle"): {},
}
# Compute billing also proves the caller is the cloud Octop server, not the tenant (who holds
# their own token and could otherwise settle a running computer at 0 s). The key is shared
# with Lynxce, set there by the operator, and never leaves this server.
_SERVICE_KEY_PATHS = frozenset(
    {"/api/billing/octop-bot/compute/reserve", "/api/billing/octop-bot/compute/settle"}
)


def _service_headers(path: str) -> dict[str, str]:
    if path not in _SERVICE_KEY_PATHS:
        return {}
    key = (os.environ.get("OCTOP_BOT_COMPUTE_SERVICE_KEY") or "").strip()
    if not key:
        logger.warning("OCTOP_BOT_COMPUTE_SERVICE_KEY is not set; Lynxce will refuse %s", path)
        return {}
    return {"X-Octop-Service-Key": key}


async def tenant_call(
    services: SharedServices,
    user_id: int,
    method: str,
    path: str,
    json: dict[str, Any] | None = None,
) -> Any:
    """Cloud mode: one of a few account operations, as the tenant's stored Lynxce session."""
    allowed = _TENANT_CALLS.get((method, path))
    if not bot_cloud_enabled() or allowed is None:
        raise OctopError.localized(ErrorCode.FORBIDDEN)
    extra = {**allowed, **_service_headers(path)}
    async with _lock(services, user_id):
        grant = await asyncio.to_thread(_load, services, user_id)
        if grant is None:
            raise OctopError.localized(ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED)
        try:
            return await _send(method, path, bearer=grant.access_token, json=json, headers=extra)
        except _UpstreamFailure as exc:
            if exc.status != 401:
                raise _rejected(exc.status) from None
            grant = await _refresh(services, user_id, grant)
            try:
                return await _send(
                    method, path, bearer=grant.access_token, json=json, headers=extra
                )
            except _UpstreamFailure as again:
                raise _rejected(again.status) from None


async def model_key_rejected(secret: str) -> bool:
    """Whether Lynxce's open gateway refuses this personal API key (revoked or expired).

    Only a 401/403 counts; an unreachable gateway or any other reply keeps the key.
    """
    try:
        async with _client() as client:
            response = await client.get(
                _ORIGIN + "/api/v1/models", headers={"Authorization": f"Bearer {secret}"}
            )
    except httpx.HTTPError:
        return False
    return response.status_code in {401, 403}


async def create_model_key(services: SharedServices, user_id: int, body: dict[str, Any]) -> Any:
    """Mint a Lynxce personal API key for this tenant with its stored session."""
    return await tenant_call(services, user_id, "POST", "/api/user/personal-api-keys", body)


def forget_session(services: SharedServices, user_id: int) -> None:
    services.secret_repo.delete(_key(user_id))
