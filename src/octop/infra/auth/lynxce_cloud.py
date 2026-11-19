"""Lynxce end-user cloud sessions, separate from the personal model OAuth grant."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Coroutine, Mapping
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

import httpx
from filelock import AsyncFileLock
from pydantic import BaseModel

from octop.infra.crypto.fernet import decrypt_json, encrypt_json
from octop.infra.db.services import SharedServices
from octop.infra.desktop import bot_desktop_enabled
from octop.infra.errors import ErrorCode, OctopError

_ORIGIN = "https://api.lynxce.cn"
_ID = r"(?!\.{1,2}(?:/|$))[A-Za-z0-9_.-]{1,256}"
_WEB_ID = r"[A-Za-z0-9._:-]{4,96}"
_READS = {
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


@dataclass(frozen=True)
class _Grant:
    account_id: str
    display_name: str | None
    binding: str
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)

    def status(self) -> CloudAccountStatus:
        return CloudAccountStatus(
            connected=True, account_id=self.account_id, display_name=self.display_name
        )


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
    grant = _load(services, user_id) if bot_desktop_enabled() else None
    return grant.status() if grant else CloudAccountStatus()


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
) -> Any:
    # 'web' is Lynxce's supported multi-session channel. Exchanging a desktop auth code
    # would revoke the user's existing Lynxce desktop session and its API keys.
    headers = {"Accept": "application/json", "X-Lynxce-Client": "web"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    try:
        async with _client() as client:
            response = await client.request(
                method, _ORIGIN + path, headers=headers, json=json, params=params
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


async def login_cloud(
    services: SharedServices, user_id: int, account: str, password: str
) -> CloudAccountStatus:
    if not bot_desktop_enabled():
        raise OctopError.localized(ErrorCode.FORBIDDEN)
    account = account.strip()
    if not (1 <= len(account) <= 200 and 8 <= len(password) <= 4096):
        raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS, status=422)
    async with _lock(services, user_id):
        try:
            data = await _send(
                "POST", "/api/auth/password-login", json={"account": account, "password": password}
            )
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
        grant = _Grant(
            profile["id"],
            name if isinstance(name, str) else None,
            uuid4().hex,
            _token(data, "accessToken"),
            _token(data, "refreshToken"),
        )
        await _finish(asyncio.to_thread(_save, services, user_id, grant))
        return grant.status()


async def logout_cloud(
    services: SharedServices, user_id: int, *, expected_account_id: str | None = None
) -> CloudAccountStatus:
    if not bot_desktop_enabled():
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
    updated = _Grant(grant.account_id, grant.display_name, grant.binding, access, refresh)
    await asyncio.to_thread(_save, services, user_id, updated)
    return updated


def _allowed(method: str, path: str, params: Mapping[str, str | int]) -> bool:
    # Web history identifiers support a literal or URL-encoded colon (e.g. cowork:uuid).
    path = path.replace("%3A", ":").replace("%3a", ":")
    if method == "POST":
        return not params and _WRITES.fullmatch(path) is not None
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
        not bot_desktop_enabled()
        or not _allowed(method, path, params or {})
        or (method == "GET" and json is not None)
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
