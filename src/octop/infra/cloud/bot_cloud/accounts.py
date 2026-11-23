"""Cloud-mode tenants: a Lynxce sign-in becomes an Octop account with its own model key.

Each Lynxce account maps to one non-admin Octop user through the ``user_sso_identities`` table
(provider kind ``lynxce``, subject = Lynxce user id). The tenant's chats call the Lynxce open
gateway with a personal API key minted for them ("Octop Bot 云端"), so usage is billed to their
own Lynxce wallet and shows up, revocable, in their Lynxce account centre.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from filelock import AsyncFileLock

from octop.infra.auth import lynxce_cloud
from octop.infra.crypto.fernet import decrypt_json, encrypt_json
from octop.infra.errors import ErrorCode, OctopError

if TYPE_CHECKING:
    from octop.infra.db.services import SharedServices
    from octop.infra.users.identity import User
    from octop.infra.users.manager import UserManager

logger = logging.getLogger(__name__)

SSO_KIND = "lynxce"
KEY_NAME = "Octop Bot 云端"
DEFAULT_MODEL = "deepseek-flash"
# Chat, plus the Bots' image and video generation (lynxce_media.py).
KEY_SCOPES = ("model:chat", "media:image", "media:video")
# UserManager.disabled_reason of a tenant who asked Lynxce to delete their account.
DELETION_PENDING = "lynxce_deletion_pending"


@dataclass(frozen=True)
class ModelKey:
    key_id: str
    secret: str
    # Scopes this server gave the key; keys minted before media generation have none recorded.
    scopes: tuple[str, ...] = ()


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
    scopes = data.get("scopes")
    return ModelKey(
        key_id=str(data["key_id"]),
        secret=str(data["secret"]),
        scopes=tuple(str(s) for s in scopes) if isinstance(scopes, list) else (),
    )


def forget_model_key(services: SharedServices, user_id: int) -> None:
    services.secret_repo.delete(_key_ref(user_id))


def _save_model_key(services: SharedServices, user_id: int, key: ModelKey) -> None:
    repo = services.secret_repo
    ref = _key_ref(user_id)
    data = {"key_id": key.key_id, "secret": key.secret, "scopes": list(key.scopes)}
    repo.put(ref, encrypt_json(repo, ref + ".fernet", data))


def _key_request() -> dict[str, Any]:
    """Chat and media generation; the daily cap is Lynxce's default unless
    OCTOP_BOT_CLOUD_KEY_DAILY_LIMIT says otherwise (``none`` = no cap). The user can change it
    in their Lynxce account centre."""
    body: dict[str, Any] = {"name": KEY_NAME, "scopes": list(KEY_SCOPES)}
    raw = (os.environ.get("OCTOP_BOT_CLOUD_KEY_DAILY_LIMIT") or "").strip().lower()
    if raw == "none":
        body["dailyCreditLimit"] = None
    elif raw.isdigit() and int(raw) > 0:
        body["dailyCreditLimit"] = int(raw)
    return body


def _key_lock(services: SharedServices, user_id: int) -> AsyncFileLock:
    # Not lynxce_cloud._lock: minting the key takes that one (tenant_call), and it does not nest.
    return AsyncFileLock(services.paths.root / f".lynxce-cloud-key-{user_id}.lock")


async def ensure_model_key(
    services: SharedServices, user_id: int, *, verify: bool = False
) -> ModelKey:
    """The tenant's model key, minted on first use.

    One key per tenant even when two sign-ins race (phone and web): the check and the mint
    run under a per-tenant lock. ``verify`` asks the gateway first and replaces a key the
    user revoked in their Lynxce account centre, which would otherwise fail every chat.
    """
    async with _key_lock(services, user_id):
        existing = await asyncio.to_thread(load_model_key, services, user_id)
        if existing is not None:
            if not verify or not await lynxce_cloud.model_key_rejected(existing.secret):
                return existing
            await asyncio.to_thread(forget_model_key, services, user_id)
        return await _mint_model_key(services, user_id)


async def _mint_model_key(services: SharedServices, user_id: int) -> ModelKey:
    data = await lynxce_cloud.create_model_key(services, user_id, _key_request())
    key_id = data.get("id") if isinstance(data, dict) else None
    secret = data.get("secret") if isinstance(data, dict) else None
    if not isinstance(key_id, str) or not isinstance(secret, str) or not secret.startswith("sk-"):
        raise OctopError.localized(ErrorCode.NETWORK_ERROR)
    key = ModelKey(key_id=key_id, secret=secret, scopes=KEY_SCOPES)
    await asyncio.to_thread(_save_model_key, services, user_id, key)
    return key


async def ensure_media_scopes(services: SharedServices, user_id: int) -> None:
    """Give a key minted for chat only the media scopes too, once, with the tenant's session.

    Lynxce does not upgrade an existing key's scopes. On failure (no session, Lynxce down) the
    key is used as it is: the gateway then answers ``api_key_scope_forbidden``, and signing in
    again retries this.
    """
    async with _key_lock(services, user_id):
        key = await asyncio.to_thread(load_model_key, services, user_id)
        if key is None or set(KEY_SCOPES) <= set(key.scopes):
            return
        try:
            await lynxce_cloud.tenant_call(
                services,
                user_id,
                "PATCH",
                f"/api/user/personal-api-keys/{key.key_id}",
                {"scopes": list(KEY_SCOPES)},
            )
        except Exception:  # noqa: BLE001 - see the docstring
            logger.warning("Could not add media scopes to the Lynxce key of user %s", user_id)
            return
        await asyncio.to_thread(
            _save_model_key,
            services,
            user_id,
            ModelKey(key_id=key.key_id, secret=key.secret, scopes=KEY_SCOPES),
        )


async def provision(
    services: SharedServices,
    users: UserManager,
    session: lynxce_cloud.CloudSession,
    locale: str | None = None,
) -> User:
    """Find or create the tenant for this Lynxce account and keep its session and model key.

    A new tenant starts in ``locale`` (the sign-in's language); an existing one keeps theirs.

    Account deletion: :func:`delete_account` disables the tenant with reason
    :data:`DELETION_PENDING`. Lynxce only lets the account sign in again while it still
    exists, i.e. the user cancelled the deletion during the cooling-off period, so a
    successful sign-in re-enables that tenant. A tenant the operator disabled (no reason, or
    disabled again by the operator after the deletion request) stays disabled; the session
    just opened is then closed upstream, as on any failure before it is kept.
    """
    try:
        provider_id = await asyncio.to_thread(_provider_id, services)
        existing = await asyncio.to_thread(
            services.user_repo.get_by_sso, provider_id, session.account_id
        )
        if (
            existing is not None
            and existing.disabled
            and await asyncio.to_thread(users.disabled_reason, existing.id) == DELETION_PENDING
        ):
            await users.enable(existing.username)
        claims: dict[str, Any] = {"name": session.display_name or ""}
        user = await users.resolve_or_create_sso_user(
            provider_id=provider_id, subject=session.account_id, claims=claims
        )
        if existing is None and locale:
            await asyncio.to_thread(services.user_repo.set_locale, user.id, locale)
            user.locale = locale
    except Exception:
        await lynxce_cloud.discard_session(session)
        raise
    await lynxce_cloud.keep_session(services, user.id, session)
    try:
        # Signing in again is how a tenant recovers from a key revoked in the Lynxce console.
        await ensure_model_key(services, user.id, verify=True)
        await ensure_media_scopes(services, user.id)
    except Exception:
        # The sign-in fails, so its session must not stay open, here or upstream.
        await asyncio.to_thread(lynxce_cloud.forget_session, services, user.id)
        await lynxce_cloud.discard_session(session)
        raise
    return user


async def delete_account(services: SharedServices, users: UserManager, user: User) -> int:
    """App Store 5.1.1(v): delete the Lynxce account, then close this tenant's account here.

    Lynxce signs the account out everywhere and erases it after its cooling-off period; the
    local account is disabled (reason :data:`DELETION_PENDING`) and its Lynxce session and
    model key are dropped at once. Signing in again during the cooling-off period re-enables
    it (see :func:`provision`). Returns the cooling-off days.
    """
    data = await lynxce_cloud.tenant_call(
        services, user.id, "POST", "/api/user/account/deletion-request", {"confirm": "注销账号"}
    )
    await users.disable(user.username, reason=DELETION_PENDING)
    await asyncio.to_thread(forget_model_key, services, user.id)
    await asyncio.to_thread(lynxce_cloud.forget_session, services, user.id)
    days = data.get("coolingDays") if isinstance(data, dict) else None
    return days if isinstance(days, int) else 7


def cloud_model_id() -> str:
    return (os.environ.get("OCTOP_BOT_CLOUD_MODEL") or "").strip() or DEFAULT_MODEL
