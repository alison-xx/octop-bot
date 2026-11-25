"""Cloud-mode tenants: a Lynxce sign-in becomes an Octop account with its own model key.

Each Lynxce account maps to one non-admin Octop user through the ``user_sso_identities`` table
(provider kind ``lynxce``, subject = Lynxce user id). The tenant's chats call the Lynxce open
gateway with a personal API key minted for them ("Octop Bot 云端 · <tag>"), so usage is billed
to their own Lynxce wallet and shows up, revocable, in their Lynxce account centre.

Lynxce never returns a key's secret again, so a key this server lost (new database, key
forgotten or revoked) cannot be reused: it is revoked before the replacement is minted. The
``<tag>`` tells this server's keys apart from those of other servers and desktops signed in to
the same account, which must keep working.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import secrets
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from filelock import AsyncFileLock

from octop.infra.auth import lynxce_cloud, lynxce_compute
from octop.infra.crypto.fernet import decrypt_json, encrypt_json
from octop.infra.errors import ErrorCode, OctopError

if TYPE_CHECKING:
    from octop.infra.db.services import SharedServices
    from octop.infra.users.identity import User
    from octop.infra.users.manager import UserManager

logger = logging.getLogger(__name__)

SSO_KIND = "lynxce"
KEY_NAME = "Octop Bot 云端"
# Lynxce serves Octop Bot only the Tencent Cloud TokenHub models, all named ``tencent/…``.
LYNXCE_MODEL_PREFIX = "tencent/"
DEFAULT_MODEL = "tencent/auto"
# Chat, plus the Bots' image and video generation (lynxce_media.py).
KEY_SCOPES = ("model:chat", "media:image", "media:video")
# Under OCTOP_HOME, not in the database, so the tag survives a database swap.
INSTANCE_FILE = ".lynxce-key-instance"
# UserManager.disabled_reason of a tenant who asked Lynxce to delete their account.
DELETION_PENDING = "lynxce_deletion_pending"


@dataclass(frozen=True)
class ModelKey:
    key_id: str
    secret: str
    # Scopes this server gave the key; keys minted before media generation have none recorded.
    scopes: tuple[str, ...] = ()
    # The key has no credit cap of its own: only the wallet balance limits it. Keys minted
    # before this got Lynxce's default daily cap (1000 credits) and are lifted once.
    uncapped: bool = False


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
        uncapped=data.get("uncapped") is True,
    )


def forget_model_key(services: SharedServices, user_id: int) -> None:
    services.secret_repo.delete(_key_ref(user_id))


def _save_model_key(services: SharedServices, user_id: int, key: ModelKey) -> None:
    repo = services.secret_repo
    ref = _key_ref(user_id)
    data = {
        "key_id": key.key_id,
        "secret": key.secret,
        "scopes": list(key.scopes),
        "uncapped": key.uncapped,
    }
    repo.put(ref, encrypt_json(repo, ref + ".fernet", data))


def key_name(services: SharedServices, user_id: int) -> str:
    """``Octop Bot 云端 · <tag>``: the tag is fixed for this server and local user."""
    path = services.paths.root / INSTANCE_FILE
    try:
        with path.open("x", encoding="utf-8") as fh:
            fh.write(secrets.token_hex(16))
    except FileExistsError:
        pass
    instance = path.read_text(encoding="utf-8").strip()
    tag = hashlib.sha256(f"{instance}:{user_id}".encode()).hexdigest()[:6]
    return f"{KEY_NAME} · {tag}"


def _operator_daily_cap() -> int | None:
    """A daily credit cap the operator sets for every key (OCTOP_BOT_CLOUD_KEY_DAILY_LIMIT)."""
    raw = (os.environ.get("OCTOP_BOT_CLOUD_KEY_DAILY_LIMIT") or "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else None


def _key_request(name: str) -> dict[str, Any]:
    """Chat and media generation, with no credit cap on the key itself.

    The wallet balance is the only limit: a user who still has credits must never be stopped.
    Lynxce gives a key 1000 credits a day unless told otherwise, so the caps are sent as
    ``null``. OCTOP_BOT_CLOUD_KEY_DAILY_LIMIT, when the operator sets it, is the one exception.
    """
    return {
        "name": name,
        "scopes": list(KEY_SCOPES),
        "dailyCreditLimit": _operator_daily_cap(),
        "monthlyCreditLimit": None,
    }


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
                return await _lift_caps(services, user_id, existing)
            await asyncio.to_thread(forget_model_key, services, user_id)
        return await _mint_model_key(services, user_id, existing)


async def _lift_caps(services: SharedServices, user_id: int, key: ModelKey) -> ModelKey:
    """Take Lynxce's default daily cap off a key minted with it, once (best effort).

    Runs at sign-in and at the periodic key check before a chat, so a deploy lifts every
    active user's cap before their next message. On failure the next check tries again.
    """
    if key.uncapped or _operator_daily_cap() is not None:
        return key
    try:
        await lynxce_cloud.tenant_call(
            services,
            user_id,
            "PATCH",
            f"/api/user/personal-api-keys/{key.key_id}",
            {"dailyCreditLimit": None, "monthlyCreditLimit": None},
        )
    except Exception:  # noqa: BLE001 - no session, or Lynxce down: chat on, retry later
        logger.warning("Could not lift the credit caps of the Lynxce key of user %s", user_id)
        return key
    lifted = replace(key, uncapped=True)
    await asyncio.to_thread(_save_model_key, services, user_id, lifted)
    return lifted


async def _revoke(services: SharedServices, user_id: int, key_id: str) -> None:
    try:
        await lynxce_cloud.revoke_model_key(services, user_id, key_id)
    except Exception:  # noqa: BLE001 - already gone, or Lynxce down: the key just stays
        logger.warning("Could not revoke Lynxce key %s of user %s", key_id, user_id)


async def _revoke_stale_keys(
    services: SharedServices, user_id: int, name: str, stale: ModelKey | None
) -> None:
    """Before minting: revoke this server's previous keys for the account (best effort).

    That is the key it held (``stale``), any key with this server's ``name`` (one it lost),
    and keys named plain ``KEY_NAME`` that were never used: those came from before the tag,
    from no server that is chatting with them.
    """
    ids = {stale.key_id} if stale is not None else set()
    try:
        listing = await lynxce_cloud.list_model_keys(services, user_id)
    except Exception:  # noqa: BLE001 - mint anyway; the next replacement cleans up
        logger.warning("Could not list the Lynxce keys of user %s", user_id)
        listing = None
    items = listing.get("items") if isinstance(listing, dict) else None
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        if item.get("name") == name or (
            item.get("name") == KEY_NAME and item.get("lastUsedAt") is None
        ):
            ids.add(item["id"])
    for key_id in sorted(ids):
        await _revoke(services, user_id, key_id)


async def _mint_model_key(
    services: SharedServices, user_id: int, stale: ModelKey | None = None
) -> ModelKey:
    name = await asyncio.to_thread(key_name, services, user_id)
    await _revoke_stale_keys(services, user_id, name, stale)
    data = await lynxce_cloud.create_model_key(services, user_id, _key_request(name))
    key_id = data.get("id") if isinstance(data, dict) else None
    secret = data.get("secret") if isinstance(data, dict) else None
    if not isinstance(key_id, str) or not isinstance(secret, str) or not secret.startswith("sk-"):
        raise OctopError.localized(ErrorCode.NETWORK_ERROR)
    key = ModelKey(
        key_id=key_id,
        secret=secret,
        scopes=KEY_SCOPES,
        uncapped=_operator_daily_cap() is None,
    )
    await asyncio.to_thread(_save_model_key, services, user_id, key)
    return key


async def revoke_model_key(services: SharedServices, user_id: int) -> None:
    """Desktop sign-out: revoke the key upstream while the session still works, then forget it."""
    async with _key_lock(services, user_id):
        key = await asyncio.to_thread(load_model_key, services, user_id)
        if key is None:
            return
        await _revoke(services, user_id, key.key_id)
        await asyncio.to_thread(forget_model_key, services, user_id)


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
            replace(key, scopes=KEY_SCOPES),
        )


def tenant_for_account(services: SharedServices, account_id: str) -> Any | None:
    """The tenant of a Lynxce account that has signed in here before, if any."""
    provider = services.sso_repo.get_by_kind(SSO_KIND)
    if provider is None:
        return None
    return services.user_repo.get_by_sso(int(provider.id), account_id)


async def desktop_computer_user(
    services: SharedServices, users: UserManager, account_id: str, server_code: str | None
) -> User:
    row = await asyncio.to_thread(tenant_for_account, services, account_id)
    if row is not None and row.disabled:
        raise OctopError.localized(ErrorCode.AUTH_FAILED, status=403)
    if server_code is not None:
        grant = await lynxce_cloud.redeem_compute_code(account_id, server_code)
        provider_id = await asyncio.to_thread(_provider_id, services)
        user = await users.resolve_or_create_sso_user(
            provider_id=provider_id, subject=account_id, claims={}
        )
        await lynxce_cloud.keep_compute_grant(services, user.id, grant)
        return user
    if row is not None and await lynxce_cloud.computer_billing_connected(
        services, row.id, account_id
    ):
        connected_user = await asyncio.to_thread(users.get_by_id, row.id)
        if connected_user is not None:
            return connected_user
    raise OctopError.localized(ErrorCode.BOT_CLOUD_SESSION_REQUIRED)


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
    await asyncio.to_thread(lynxce_compute.forget, services, user.id)
    days = data.get("coolingDays") if isinstance(data, dict) else None
    return days if isinstance(days, int) else 7


def cloud_model_id() -> str:
    return (os.environ.get("OCTOP_BOT_CLOUD_MODEL") or "").strip() or DEFAULT_MODEL


def lynxce_chat_model(saved: object) -> str:
    """The Lynxce model to chat on: a saved choice, unless it predates the Tencent-only line."""
    if isinstance(saved, str) and saved.startswith(LYNXCE_MODEL_PREFIX):
        return saved
    return cloud_model_id()
