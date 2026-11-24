"""A user's own model vendor keys (Tencent Cloud, Bailian, Volcengine Ark, ...).

Each user keeps their keys to themselves: they are stored encrypted under the user, never in
the server-wide ``providers`` table, so other users (and cloud tenants) cannot see or use them.
Chats on an own key are billed by the vendor, not in Lynxce credits.

In cloud mode a key can only point at a built-in vendor's official HTTPS endpoint: a free-form
URL would let any tenant make the server call internal addresses. The desktop app also takes
any OpenAI-compatible URL (a local gateway, a company proxy).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from octop_harness.config import ModelConfig, ProviderConfig

from octop.infra.agents.providers.lynxce import AccountModel
from octop.infra.agents.providers.presets import load_provider_presets
from octop.infra.crypto.fernet import decrypt_json, encrypt_json
from octop.infra.desktop import bot_cloud_enabled, bot_desktop_enabled, bot_web_enabled
from octop.infra.errors import ErrorCode, OctopError

if TYPE_CHECKING:
    from octop.infra.db.services import SharedServices

OWN_PREFIX = "own:"
CUSTOM_VENDOR = "custom"
# Server-side presets that are not "paste a key" vendors: Lynxce has its own sign-in, the rest
# are local services or OAuth logins.
_NOT_KEY_VENDORS = {"lynxce", "magpie", "openai-codex", "ollama", "onnx"}
MAX_KEYS = 20


def _store_key(user_id: int) -> str:
    return f"octop_bot:own_model_keys:{user_id}"


@dataclass(frozen=True)
class OwnKey:
    id: str
    vendor: str
    name: str
    base_url: str
    protocol: str
    api_key: str
    models: tuple[tuple[str, str], ...]
    created_at: float

    def public(self) -> dict[str, Any]:
        """What the owner sees: never the key itself, only its last four characters."""
        return {
            "id": self.id,
            "vendor": self.vendor,
            "name": self.name,
            "base_url": self.base_url,
            "key_hint": "****" + self.api_key[-4:] if len(self.api_key) > 8 else "****",
            "models": [{"id": mid, "name": label} for mid, label in self.models],
            "created_at": self.created_at,
        }


def _vendors() -> dict[str, dict[str, Any]]:
    return {
        str(p["id"]): p
        for p in load_provider_presets()
        if p.get("id") not in _NOT_KEY_VENDORS
        and p.get("purpose") != "embedding"
        and p.get("protocol") in ("openai", "anthropic")
        and isinstance(p.get("base_url"), str)
        and p["base_url"].startswith("https://")
    }


def vendor_catalog() -> list[dict[str, Any]]:
    """Vendors a user can add a key for, with their suggested models."""
    return [
        {
            "id": vid,
            "name": p.get("name") or vid,
            "vendor": p.get("vendor") or vid,
            "logo_id": p.get("logo_id") or p.get("vendor") or vid,
            "base_url": p["base_url"],
            "protocol": p["protocol"],
            "api_key_prefix": p.get("api_key_prefix") or "",
            "models": [
                {"id": str(m["id"]), "name": str(m.get("name") or m["id"])}
                for m in p.get("models") or []
                if isinstance(m, dict) and m.get("id")
            ],
        }
        for vid, p in _vendors().items()
    ]


def custom_urls_allowed(admin: bool = True) -> bool:
    """Whether a key may point at any OpenAI-compatible URL instead of a listed vendor.

    Never on Octop Bot cloud (a tenant could make the server call internal addresses), always
    in the desktop app, and on a self-hosted Bot web server only for its admins.
    """
    if bot_cloud_enabled():
        return False
    if bot_web_enabled() and not bot_desktop_enabled():
        return admin
    return True


def _load(services: SharedServices, user_id: int) -> list[OwnKey]:
    key = _store_key(user_id)
    blob = services.secret_repo.get(key)
    if not blob:
        return []
    data = decrypt_json(services.secret_repo, key + ".fernet", blob)
    return [
        OwnKey(
            id=row["id"],
            vendor=row["vendor"],
            name=row["name"],
            base_url=row["base_url"],
            protocol=row["protocol"],
            api_key=row["api_key"],
            models=tuple((m["id"], m["name"]) for m in row.get("models") or []),
            created_at=float(row.get("created_at") or 0),
        )
        for row in data.get("keys") or []
    ]


def _save(services: SharedServices, user_id: int, keys: list[OwnKey]) -> None:
    key = _store_key(user_id)
    rows = [
        {
            "id": k.id,
            "vendor": k.vendor,
            "name": k.name,
            "base_url": k.base_url,
            "protocol": k.protocol,
            "api_key": k.api_key,
            "models": [{"id": mid, "name": label} for mid, label in k.models],
            "created_at": k.created_at,
        }
        for k in keys
    ]
    services.secret_repo.put(
        key, encrypt_json(services.secret_repo, key + ".fernet", {"keys": rows})
    )


def list_keys(services: SharedServices, user_id: int) -> list[OwnKey]:
    return _load(services, user_id)


def get_key(services: SharedServices, user_id: int, key_id: str) -> OwnKey | None:
    return next((k for k in _load(services, user_id) if k.id == key_id), None)


def _bad(code: ErrorCode, **params: Any) -> OctopError:
    return OctopError.localized(code, status=400, **params)


def _check_custom_url(base_url: str) -> str:
    url = base_url.strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise _bad(ErrorCode.BOT_MODEL_VENDOR_UNSUPPORTED)
    return url


def _vendor_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=15, follow_redirects=False)


async def _fetch_models(base_url: str, protocol: str, api_key: str) -> list[tuple[str, str]] | None:
    """The vendor's model list, ``None`` if it has none to give; raises if the key is refused."""
    headers = (
        {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        if protocol == "anthropic"
        else {"Authorization": f"Bearer {api_key}"}
    )
    try:
        async with _vendor_client() as client:
            resp = await client.get(f"{base_url}/models", headers=headers)
    except httpx.HTTPError:
        return None
    if resp.status_code in (401, 403):
        raise _bad(ErrorCode.BOT_MODEL_KEY_INVALID)
    if resp.status_code != 200:
        return None
    try:
        rows = resp.json().get("data")
    except ValueError:
        return None
    if not isinstance(rows, list):
        return None
    found: list[tuple[str, str]] = []
    for row in rows:
        mid = row.get("id") if isinstance(row, dict) else None
        if isinstance(mid, str) and mid.strip():
            label = row.get("display_name") or row.get("name") or mid
            found.append((mid.strip(), str(label)))
    return found or None


async def add_key(
    services: SharedServices,
    user_id: int,
    *,
    vendor: str,
    api_key: str,
    name: str | None = None,
    base_url: str | None = None,
    protocol: str | None = None,
    admin: bool = True,
) -> OwnKey:
    """Check the key with the vendor and keep it. Returns the stored key."""
    secret = api_key.strip()
    if not secret:
        raise _bad(ErrorCode.BOT_MODEL_KEY_INVALID)
    if vendor == CUSTOM_VENDOR:
        if not custom_urls_allowed(admin) or not base_url:
            raise _bad(ErrorCode.BOT_MODEL_VENDOR_UNSUPPORTED)
        url = _check_custom_url(base_url)
        proto = "anthropic" if protocol == "anthropic" else "openai"
        label = (name or "").strip() or (urlsplit(url).hostname or url)
        suggested: list[tuple[str, str]] = []
    else:
        preset = _vendors().get(vendor)
        if preset is None:
            raise _bad(ErrorCode.BOT_MODEL_VENDOR_UNSUPPORTED)
        url = str(preset["base_url"]).rstrip("/")
        proto = str(preset["protocol"])
        label = (name or "").strip() or str(preset.get("name") or vendor)
        suggested = [
            (str(m["id"]), str(m.get("name") or m["id"]))
            for m in preset.get("models") or []
            if isinstance(m, dict) and m.get("id")
        ]
    listed = await _fetch_models(url, proto, secret)
    models = tuple(listed or suggested)
    if not models:
        # Nothing to choose from: a custom endpoint without /models.
        raise _bad(ErrorCode.BOT_MODEL_KEY_INVALID)
    entry = OwnKey(
        id=uuid4().hex[:12],
        vendor=vendor,
        name=label[:60],
        base_url=url,
        protocol=proto,
        api_key=secret,
        models=models,
        created_at=time.time(),
    )

    def store() -> None:
        keys = _load(services, user_id)
        if len(keys) >= MAX_KEYS:
            raise _bad(ErrorCode.BOT_MODEL_KEY_LIMIT, limit=MAX_KEYS)
        _save(services, user_id, [*keys, entry])

    await asyncio.to_thread(store)
    return entry


def remove_key(services: SharedServices, user_id: int, key_id: str) -> bool:
    keys = _load(services, user_id)
    kept = [k for k in keys if k.id != key_id]
    if len(kept) == len(keys):
        return False
    _save(services, user_id, kept)
    return True


@dataclass(frozen=True)
class OwnKeyModel(AccountModel):
    """A chat model on one of the user's own vendor keys; the key is read on every request,
    so removing it stops the next turn."""

    protocol: str = "openai"
    base_url: str = ""

    @property
    def key_id(self) -> str:
        return self.connection_id.removeprefix(OWN_PREFIX)

    @property
    def ref(self) -> str:
        return f"own/{self.model_id}"

    def provider(
        self, services: SharedServices | None, bot_id: str | None = None
    ) -> ProviderConfig:
        # The user's own provider, not Lynxce: no Lynxce headers, so bot_id is unused.
        del bot_id

        async def key_for_request() -> str:
            own = (
                await asyncio.to_thread(get_key, services, self.user_id, self.key_id)
                if services is not None
                else None
            )
            if own is None:
                # Removed while a turn was running; the next turn falls back to the default.
                raise _bad(ErrorCode.BOT_MODEL_KEY_INVALID)
            return own.api_key

        return ProviderConfig(
            id="own",
            name="Own key",
            protocol=cast("Literal['openai', 'anthropic']", self.protocol),
            base_url=self.base_url,
            api_key=cast("str", key_for_request),
            models=[ModelConfig(id=self.model_id, name=self.model_id)],
        )


def own_selection(
    services: SharedServices, user_id: int, connection: str, model: str
) -> OwnKeyModel | None:
    """The selected own-key model, or ``None`` once that key was removed (use the default)."""
    own = get_key(services, user_id, connection.removeprefix(OWN_PREFIX))
    if own is None:
        return None
    return OwnKeyModel(user_id, connection, model, protocol=own.protocol, base_url=own.base_url)
