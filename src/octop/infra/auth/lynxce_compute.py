"""The tenant's independent, revocable Lynxce authorization for computer billing."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from octop.infra.db.services import SharedServices
from octop.infra.errors import ErrorCode, OctopError


@dataclass(frozen=True)
class ComputeGrant:
    account_id: str
    device_id: str
    expires_at: float
    authorized_until: float
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)


def _utc_timestamp(value: Any) -> float:
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.utcoffset() == timedelta(0):
            return stamp.timestamp()
    except (TypeError, ValueError, OverflowError):
        pass
    raise OctopError.localized(ErrorCode.NETWORK_ERROR)


def from_response(data: Any, account_id: str, previous: ComputeGrant | None = None) -> ComputeGrant:
    if not isinstance(data, dict) or data.get("userId") != account_id:
        raise OctopError.localized(ErrorCode.AUTH_FAILED, status=403)
    for name in ("deviceId", "accessToken", "refreshToken"):
        value = data.get(name)
        if not isinstance(value, str) or not 1 <= len(value) <= 32768 or not value.isascii():
            raise OctopError.localized(ErrorCode.NETWORK_ERROR)
        if not value.isprintable() or any(char.isspace() for char in value):
            raise OctopError.localized(ErrorCode.NETWORK_ERROR)
    if previous and data["deviceId"] != previous.device_id:
        raise OctopError.localized(ErrorCode.AUTH_FAILED, status=403)
    now = time.time()
    limit = previous.authorized_until if previous else now + 30 * 86400
    authorized_until = min(limit, _utc_timestamp(data.get("authorizationExpiresAt")))
    expires_at = min(authorized_until, now + 3600, _utc_timestamp(data.get("expiresAt")))
    if expires_at <= now:
        raise OctopError.localized(ErrorCode.BOT_CLOUD_SESSION_REQUIRED)
    return ComputeGrant(
        account_id,
        data["deviceId"],
        expires_at,
        authorized_until,
        data["accessToken"],
        data["refreshToken"],
    )


def _key(user_id: int) -> str:
    return f"lynxce.compute.user.{user_id}"


def load(services: SharedServices, user_id: int) -> ComputeGrant | None:
    key = _key(user_id)
    repo = services.secret_repo
    blob = repo.get(key)
    if blob is None:
        return None
    # This per-account key is erased on withdrawal; decryption must never recreate it.
    raw = repo.get(key + ".fernet")
    if raw is None:
        raise OctopError.localized(ErrorCode.BOT_CLOUD_SESSION_REQUIRED)
    try:
        return ComputeGrant(**json.loads(Fernet(raw).decrypt(blob)))
    except InvalidToken:
        raise OctopError.localized(ErrorCode.BOT_CLOUD_SESSION_REQUIRED) from None


def save(services: SharedServices, user_id: int, grant: ComputeGrant) -> None:
    key = _key(user_id)
    repo = services.secret_repo
    # A consent can be withdrawn and reissued in the same process. Read its current
    # durable wrapping key even if this account was previously authorized by this worker.
    raw = repo.get_or_create(key + ".fernet", Fernet.generate_key)
    repo.put(key, Fernet(raw).encrypt(json.dumps(asdict(grant)).encode()))
    user = services.user_repo.get(user_id)
    if user is None or user.disabled:
        forget(services, user_id)
        raise OctopError.localized(ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED)


def forget(services: SharedServices, user_id: int) -> None:
    key = _key(user_id)
    services.secret_repo.delete(key)
    services.secret_repo.delete(key + ".fernet")
