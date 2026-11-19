"""User-scoped encrypted grants and rotation under a per-account desktop lock."""

from __future__ import annotations

import asyncio
import secrets
import time
from functools import partial
from pathlib import Path
from typing import Any

from filelock import AsyncFileLock

from octop.infra.auth.lynxce import _provider
from octop.infra.crypto.fernet import decrypt_json, encrypt_json
from octop.infra.db.services import SharedServices
from octop.infra.errors import ErrorCode, OctopError

_PURPOSE = "lynxce_oauth_fernet"
_REFRESH_EARLY_SECONDS = 60


def grant_key(user_id: int) -> str:
    return f"lynxce.oauth.user.{user_id}"


def account_lock(services: SharedServices, user_id: int) -> AsyncFileLock:
    # Rotation invalidates the previous refresh token immediately. Also cover
    # other loops/processes using this installation, not just parallel turns.
    return AsyncFileLock(services.paths.root / f".lynxce-oauth-{user_id}.lock")


def is_connected(services: SharedServices, user_id: int) -> bool:
    return services.secret_repo.get(grant_key(user_id)) is not None


def connection_id(services: SharedServices, user_id: int) -> str | None:
    blob = services.secret_repo.get(grant_key(user_id))
    if not blob:
        return None
    return str(decrypt_json(services.secret_repo, _PURPOSE, blob)["connection_id"])


def load_registration(services: SharedServices, user_id: int) -> dict[str, Any]:
    blob = services.secret_repo.get(f"lynxce.oauth.client.{user_id}")
    return decrypt_json(services.secret_repo, _PURPOSE, blob) if blob else {}


def save_registration(
    services: SharedServices, user_id: int, port: int, client_id: str, attempt_id: str | None
) -> None:
    repo = services.secret_repo
    repo.put(
        f"lynxce.oauth.client.{user_id}",
        encrypt_json(
            repo, _PURPOSE, {"port": port, "client_id": client_id, "attempt_id": attempt_id}
        ),
    )


def forget(services: SharedServices, user_id: int) -> None:
    current = load_registration(services, user_id)
    if current:
        save_registration(services, user_id, current["port"], current["client_id"], None)
    services.secret_repo.delete(grant_key(user_id))


def _load(services: SharedServices, user_id: int) -> dict[str, Any]:
    blob = services.secret_repo.get(grant_key(user_id))
    if not blob:
        raise auth_required()
    return decrypt_json(services.secret_repo, _PURPOSE, blob)


def save(services: SharedServices, user_id: int, grant: dict[str, Any]) -> None:
    repo = services.secret_repo
    repo.put(grant_key(user_id), encrypt_json(repo, _PURPOSE, grant))


def grant_from_tokens(
    data: dict[str, Any],
    client_id: str,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    access = data.get("access_token")
    refresh = data.get("refresh_token", previous and previous["refresh_token"])
    scope = data.get("scope", previous and previous["scope"])
    ttl = data.get("expires_in")
    if not (
        isinstance(access, str)
        and access
        and isinstance(refresh, str)
        and refresh
        and type(ttl) is int
        and ttl > 0
        and str(data.get("token_type", "")).lower() == "bearer"
    ):
        raise _provider.ProviderError("invalid_response")
    if not isinstance(scope, str) or "chat" not in scope.split():
        raise _provider.ProviderError("missing_chat_scope")
    return {
        "access_token": access,
        "refresh_token": refresh,
        "client_id": client_id,
        "scope": scope,
        "connection_id": previous["connection_id"]
        if previous is not None
        else secrets.token_urlsafe(24),
        "expires_at": time.time() + ttl,
    }


def auth_required() -> OctopError:
    return OctopError.localized(
        ErrorCode.CONNECTOR_AUTH_REQUIRED,
        status=403,
        details={"servers": "Lynxce"},
        servers="Lynxce",
    )


def _fresh(grant: dict[str, Any]) -> bool:
    return bool(grant["expires_at"] > time.time() + _REFRESH_EARLY_SECONDS)


async def _rotate(services: SharedServices, user_id: int, expected_id: str) -> str:
    loop = asyncio.get_running_loop()
    async with account_lock(services, user_id):
        current = await loop.run_in_executor(None, _load, services, user_id)
        if current["connection_id"] != expected_id:
            raise auth_required()
        if _fresh(current):
            return str(current["access_token"])
        try:
            data = await _provider.token(
                grant_type="refresh_token",
                client_id=current["client_id"],
                refresh_token=current["refresh_token"],
            )
            updated = grant_from_tokens(data, current["client_id"], current)
        except _provider.ProviderError as exc:
            if exc.reason in {"invalid_grant", "missing_chat_scope"}:
                await loop.run_in_executor(None, services.secret_repo.delete, grant_key(user_id))
                raise auth_required() from None
            raise OctopError.localized(ErrorCode.NETWORK_ERROR) from None
        await loop.run_in_executor(None, save, services, user_id, updated)
        return str(updated["access_token"])


_RotationKey = tuple[asyncio.AbstractEventLoop, Path, int, str]
_rotations: dict[_RotationKey, asyncio.Task[str]] = {}


def _rotation_done(key: _RotationKey, task: asyncio.Task[str]) -> None:
    _rotations.pop(key, None)
    if not task.cancelled():
        task.exception()


async def get_access_token(
    services: SharedServices, user_id: int, *, expected_connection_id: str | None = None
) -> str:
    loop = asyncio.get_running_loop()
    current = await loop.run_in_executor(None, _load, services, user_id)
    if expected_connection_id is not None and expected_connection_id != current["connection_id"]:
        raise auth_required()
    if _fresh(current):
        return str(current["access_token"])
    # A cancelled inference request must still save an already-rotated token.
    key = (loop, services.paths.root, user_id, current["connection_id"])
    task = _rotations.get(key)
    if task is None:
        task = asyncio.create_task(_rotate(services, user_id, current["connection_id"]))
        _rotations[key] = task
        task.add_done_callback(partial(_rotation_done, key))
    return await asyncio.shield(task)
