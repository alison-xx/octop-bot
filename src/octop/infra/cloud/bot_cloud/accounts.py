"""Cloud-mode tenants: a Lynxce sign-in becomes an Octop account with its own model key.

Each Lynxce account maps to one non-admin Octop user through the ``user_sso_identities`` table
(provider kind ``lynxce``, subject = Lynxce user id). The tenant's chats call the Lynxce open
gateway with a personal API key minted for them ("Octop Bot 云端"), so usage is billed to their
own Lynxce wallet and shows up, revocable, in their Lynxce account centre.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from octop.infra.auth import lynxce_cloud
from octop.infra.crypto.fernet import decrypt_json, encrypt_json
from octop.infra.errors import ErrorCode, OctopError

if TYPE_CHECKING:
    from octop.infra.db.services import SharedServices
    from octop.infra.users.identity import User
    from octop.infra.users.manager import UserManager

SSO_KIND = "lynxce"
KEY_NAME = "Octop Bot 云端"
DEFAULT_MODEL = "deepseek-flash"


@dataclass(frozen=True)
class ModelKey:
    key_id: str
    secret: str


def _provider_id(services: SharedServices) -> int:
    """The (never enabled) SSO provider row the tenants' Lynxce identities hang off."""
    row = services.sso_repo.get_by_kind(SSO_KIND)
    if row is None:
        row = services.sso_repo.upsert_by_kind(
            SSO_KIND,
            enabled=False,
            display_name="Lynxce",
            issuer="https://api.lynxce.cn",
            client_id="octop-bot-cloud",
            client_secret_enc=None,
            scopes="",
            dashboard_origin=None,
        )
    return int(row.id)


def _key_ref(user_id: int) -> str:
    return f"lynxce.cloud.model_key.{user_id}"


def load_model_key(services: SharedServices, user_id: int) -> ModelKey | None:
    repo = services.secret_repo
    ref = _key_ref(user_id)
    blob = repo.get(ref)
    if not blob:
        return None
    data = decrypt_json(repo, ref + ".fernet", blob)
    return ModelKey(key_id=str(data["key_id"]), secret=str(data["secret"]))


def forget_model_key(services: SharedServices, user_id: int) -> None:
    services.secret_repo.delete(_key_ref(user_id))


def _save_model_key(services: SharedServices, user_id: int, key: ModelKey) -> None:
    repo = services.secret_repo
    ref = _key_ref(user_id)
    repo.put(ref, encrypt_json(repo, ref + ".fernet", {"key_id": key.key_id, "secret": key.secret}))


def _key_request() -> dict[str, Any]:
    """Chat only; the daily cap is Lynxce's default unless OCTOP_BOT_CLOUD_KEY_DAILY_LIMIT says
    otherwise (``none`` = no cap). The user can change it in their Lynxce account centre."""
    body: dict[str, Any] = {"name": KEY_NAME, "scopes": ["model:chat"]}
    raw = (os.environ.get("OCTOP_BOT_CLOUD_KEY_DAILY_LIMIT") or "").strip().lower()
    if raw == "none":
        body["dailyCreditLimit"] = None
    elif raw.isdigit() and int(raw) > 0:
        body["dailyCreditLimit"] = int(raw)
    return body


async def ensure_model_key(services: SharedServices, user_id: int) -> ModelKey:
    existing = await asyncio.to_thread(load_model_key, services, user_id)
    if existing is not None:
        return existing
    data = await lynxce_cloud.create_model_key(services, user_id, _key_request())
    key_id = data.get("id") if isinstance(data, dict) else None
    secret = data.get("secret") if isinstance(data, dict) else None
    if not isinstance(key_id, str) or not isinstance(secret, str) or not secret.startswith("sk-"):
        raise OctopError.localized(ErrorCode.NETWORK_ERROR)
    key = ModelKey(key_id=key_id, secret=secret)
    await asyncio.to_thread(_save_model_key, services, user_id, key)
    return key


async def provision(
    services: SharedServices,
    users: UserManager,
    session: lynxce_cloud.CloudSession,
    locale: str | None = None,
) -> User:
    """Find or create the tenant for this Lynxce account and keep its session and model key.

    A new tenant starts in ``locale`` (the sign-in's language); an existing one keeps theirs.
    """
    provider_id = await asyncio.to_thread(_provider_id, services)
    existing = await asyncio.to_thread(
        services.user_repo.get_by_sso, provider_id, session.account_id
    )
    claims: dict[str, Any] = {"name": session.display_name or ""}
    user = await users.resolve_or_create_sso_user(
        provider_id=provider_id, subject=session.account_id, claims=claims
    )
    if existing is None and locale:
        await asyncio.to_thread(services.user_repo.set_locale, user.id, locale)
        user.locale = locale
    await lynxce_cloud.keep_session(services, user.id, session)
    await ensure_model_key(services, user.id)
    return user


async def delete_account(services: SharedServices, users: UserManager, user: User) -> int:
    """App Store 5.1.1(v): delete the Lynxce account, then close this tenant's account here.

    Lynxce signs the account out everywhere and erases it after its cooling-off period; the
    local account is disabled and its Lynxce session and model key are dropped at once.
    Returns the cooling-off days.
    """
    data = await lynxce_cloud.tenant_call(
        services, user.id, "POST", "/api/user/account/deletion-request", {"confirm": "注销账号"}
    )
    await users.disable(user.username)
    await asyncio.to_thread(forget_model_key, services, user.id)
    await asyncio.to_thread(lynxce_cloud.forget_session, services, user.id)
    days = data.get("coolingDays") if isinstance(data, dict) else None
    return days if isinstance(days, int) else 7


def cloud_model_id() -> str:
    return (os.environ.get("OCTOP_BOT_CLOUD_MODEL") or "").strip() or DEFAULT_MODEL
