"""Chat models visible to one signed-in Lynxce account."""

from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import uuid4

import httpx
from octop_harness.config import HarnessAgentConfig, ModelConfig, ProviderConfig

from octop.infra.agents.providers.lynxce_media import LYNXCE_HOSTS, LynxceMediaAuth
from octop.infra.agents.providers.presets import lynxce_model_input
from octop.infra.desktop import bot_cloud_enabled, bot_desktop_enabled
from octop.infra.errors import ErrorCode, OctopError

if TYPE_CHECKING:
    from octop.infra.db.services import SharedServices

BASE_URL = "https://center.lynxce.cn/api/v1"
# Lynxce's open gateway, which takes personal API keys (cloud mode).
GATEWAY_URL = "https://api.lynxce.cn/api/v1"


def lynxce_chat_models(catalog: object) -> list[dict[str, str]]:
    """Parse the account's OpenAI model list; text entries normally omit modality."""
    if not isinstance(catalog, dict) or not isinstance(catalog.get("data"), list):
        raise ValueError("Invalid Lynxce model catalog")
    models: dict[str, dict[str, str]] = {}
    for row in catalog["data"]:
        if not isinstance(row, dict) or row.get("modality") not in (None, "text"):
            continue
        raw_id = row.get("id")
        if not isinstance(raw_id, str) or not (model_id := raw_id.strip()):
            continue
        name = row.get("name")
        label = name.strip() if isinstance(name, str) else ""
        models.setdefault(model_id, {"id": model_id, "name": label or model_id})
    return list(models.values())


@dataclass(frozen=True)
class AccountModel:
    user_id: int
    connection_id: str
    model_id: str

    @property
    def ref(self) -> str:
        return f"lynxce/{self.model_id}"

    def provider(self, services: SharedServices | None) -> ProviderConfig:
        async def token_for_request() -> str:
            from octop.infra.auth.lynxce import get_access_token

            if (
                services is None
                or await asyncio.to_thread(account_selection, services, self.user_id) != self
            ):
                raise _auth_required()
            return await get_access_token(
                services, self.user_id, expected_connection_id=self.connection_id
            )

        # ChatOpenAI supports callable API keys. The cached SDK clients invoke this
        # on every request; no bearer is held on the agent or its configuration.
        return ProviderConfig(
            id="lynxce",
            name="Lynxce",
            protocol="openai",
            base_url=BASE_URL,
            api_key=cast("str", token_for_request),
            models=[ModelConfig(id=self.model_id, name=self.model_id)],
        )

    def harness_config(
        self, config: HarnessAgentConfig, services: SharedServices | None
    ) -> HarnessAgentConfig:
        from octop.infra.agents.middleware.model_failover import SafeModelFailoverMiddleware

        return replace(
            config,
            providers=[self.provider(services)],
            default_model=self.ref,
            multimodal_model=None,
            model_selector=None,
            role_bindings=None,
            memory_aux_light_model=self.ref,
            memory_aux_heavy_model=self.ref,
            middleware=[
                m
                for m in (config.middleware or [])
                if not isinstance(m, SafeModelFailoverMiddleware)
            ],
        )

    def request(self, request: dict[str, Any]) -> dict[str, Any]:
        return {
            **request,
            "model": self.ref,
            "configurable": {
                **(request.get("configurable") or {}),
                "model": self.ref,
                "octop_auto_route": False,
            },
        }


# How often a cloud tenant's model key is checked with the gateway, per tenant.
KEY_CHECK_SECONDS = 10 * 60
_key_checked: dict[int, float] = {}


@dataclass(frozen=True)
class CloudAccountModel(AccountModel):
    """Cloud mode: the tenant's own Lynxce personal API key, read on every request."""

    def provider(self, services: SharedServices | None) -> ProviderConfig:
        async def key_for_request() -> str:
            if services is None:
                raise _auth_required()
            return await cloud_model_key(services, self.user_id)

        return ProviderConfig(
            id="lynxce",
            name="Lynxce",
            protocol="openai",
            base_url=GATEWAY_URL,
            api_key=cast("str", key_for_request),
            models=[
                ModelConfig(
                    id=self.model_id,
                    name=self.model_id,
                    input=lynxce_model_input(self.model_id),
                )
            ],
        )


async def cloud_model_key(services: SharedServices, user_id: int) -> str:
    """A cloud tenant's personal API key, checked with the gateway now and then."""
    from octop.infra.cloud.bot_cloud.accounts import (  # noqa: PLC0415
        ensure_model_key,
        load_model_key,
    )

    key = await asyncio.to_thread(load_model_key, services, user_id)
    now = time.monotonic()
    if key is not None and now - _key_checked.get(user_id, -math.inf) < KEY_CHECK_SECONDS:
        return key.secret
    # Now and then, ask the gateway: a key it refuses (401, revoked in the Lynxce account
    # centre) is replaced with the tenant's stored session, without signing in again.
    try:
        key = await ensure_model_key(services, user_id, verify=True)
    except Exception:  # noqa: BLE001 - no session to mint with, or Lynxce unreachable
        if key is None:
            raise _auth_required() from None
        return key.secret
    _key_checked[user_id] = now
    return key.secret


def _auth_required() -> OctopError:
    return OctopError.localized(
        ErrorCode.CONNECTOR_AUTH_REQUIRED,
        status=403,
        details={"servers": "Lynxce"},
        servers="Lynxce",
    )


def _key(user_id: int) -> str:
    return f"octop_bot:lynxce:model:{user_id}"


def _connection(services: SharedServices, user_id: int) -> str:
    from octop.infra.auth.lynxce import connection_id

    grant = connection_id(services, user_id)
    if not grant:
        raise _auth_required()
    return grant


async def personal_gateway(
    services: SharedServices,
    user_id: int,
    grant: str,
    endpoint: Literal["models", "account", "account/recharge-link"],
) -> object:
    from octop.infra.auth.lynxce import get_access_token

    bearer = await get_access_token(services, user_id, expected_connection_id=grant)
    if endpoint == "account/recharge-link":
        from octop.infra.auth.lynxce._grants import require_recharge_scope

        await asyncio.to_thread(require_recharge_scope, services, user_id, grant)
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            reply = await client.request(
                "POST" if endpoint == "account/recharge-link" else "GET",
                BASE_URL + "/" + endpoint,
                headers={"Authorization": f"Bearer {bearer}"},
            )
        reply.raise_for_status()
        return reply.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if endpoint == "account/recharge-link" and status == 403:
            try:
                error = reply.json().get("error")
            except (ValueError, AttributeError):
                error = None
            if isinstance(error, dict) and error.get("code") == "insufficient_scope":
                raise OctopError.localized(ErrorCode.BOT_LYNXCE_RECHARGE_AUTH_REQUIRED) from None
        if status in (401, 403):
            raise _auth_required() from None
        raise OctopError.localized(
            ErrorCode.INTERNAL_ERROR, status=status if status in (402, 429) else 502
        ) from None
    except (httpx.RequestError, ValueError):
        raise OctopError.localized(ErrorCode.INTERNAL_ERROR, status=502) from None


async def _models(services: SharedServices, user_id: int, grant: str) -> list[dict[str, str]]:
    data = await personal_gateway(services, user_id, grant, "models")
    try:
        return lynxce_chat_models(data)
    except ValueError:
        raise OctopError.localized(ErrorCode.INTERNAL_ERROR, status=502) from None


async def list_account_models(services: SharedServices, user_id: int) -> list[dict[str, str]]:
    grant = await asyncio.to_thread(_connection, services, user_id)
    models = await _models(services, user_id, grant)
    if grant != await asyncio.to_thread(_connection, services, user_id):
        raise _auth_required()
    return models


async def select_account_model(services: SharedServices, user_id: int, model_id: str) -> str:
    key = _key(user_id)
    grant = await asyncio.to_thread(_connection, services, user_id)
    previous = await asyncio.to_thread(services.settings_repo.get_or_insert, key, "{}")
    models = await _models(services, user_id, grant)
    if not any(row["id"] == model_id for row in models):
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    if grant != await asyncio.to_thread(_connection, services, user_id):
        raise _auth_required()
    saved = json.dumps({"connection": grant, "model": model_id, "revision": uuid4().hex})
    if not await asyncio.to_thread(services.settings_repo.replace_if_current, key, previous, saved):
        raise OctopError.localized(ErrorCode.FORBIDDEN, status=409)
    return model_id


def account_selection(services: SharedServices, user_id: int) -> AccountModel | None:
    if bot_cloud_enabled():
        return _cloud_selection(services, user_id)
    if not bot_desktop_enabled():
        return None
    raw = services.settings_repo.get(_key(user_id))
    if not isinstance(raw, str) or not raw:
        return None
    data = json.loads(raw)
    if not data.get("model"):
        return None
    if _connection(services, user_id) != data["connection"]:
        raise _auth_required()
    return AccountModel(user_id, data["connection"], data["model"])


def _cloud_selection(services: SharedServices, user_id: int) -> AccountModel | None:
    """Every tenant chats through their own key; admins keep the server's shared providers."""
    from octop.infra.cloud.bot_cloud.accounts import cloud_model_id  # noqa: PLC0415

    user = services.user_repo.get(user_id)
    if user is None or str(user.role) == "admin":
        return None
    raw = services.settings_repo.get(_key(user_id))
    chosen = json.loads(raw).get("model") if isinstance(raw, str) and raw else None
    model = chosen if isinstance(chosen, str) and chosen else cloud_model_id()
    return CloudAccountModel(user_id, "cloud", model)


def selected_account_model(services: SharedServices, user_id: int) -> str | None:
    try:
        selected = account_selection(services, user_id)
    except OctopError as exc:
        if exc.code != ErrorCode.CONNECTOR_AUTH_REQUIRED:
            raise
        return None
    return selected.model_id if selected else None


def clear_account_model(services: SharedServices, user_id: int) -> None:
    # A fresh marker also invalidates a selection currently waiting on /models.
    services.settings_repo.set(_key(user_id), json.dumps({"revision": uuid4().hex}))


# --- Image and video generation (see lynxce_media.py) -------------------------------------


def _api_key_provider(services: SharedServices) -> tuple[str, str] | None:
    """A server's own Lynxce API key (the "灵策智算 (Lynxce)" preset): base URL and key."""
    from urllib.parse import urlsplit  # noqa: PLC0415

    for row in services.provider_repo.list_all():
        base = (row.base_url or "").strip().rstrip("/")
        if (
            row.enabled
            and row.api_key
            and urlsplit(base).scheme == "https"
            and urlsplit(base).hostname in LYNXCE_HOSTS
        ):
            return base, row.api_key
    return None


def media_source(
    services: SharedServices, user_id: int | None
) -> Literal["cloud", "account", "api_key"] | None:
    """Which Lynxce credential pays for this user's Bots' images and videos, if any.

    A cloud tenant: their own personal key. The desktop app signed in to Lynxce: that
    account. Otherwise a Lynxce API key the server's operator added as a model provider.
    """
    if user_id is not None:
        try:
            selected = account_selection(services, user_id)
        except OctopError:
            selected = None  # the desktop sign-in lapsed; the server's key may still apply
        if isinstance(selected, CloudAccountModel):
            return "cloud"
        if selected is not None:
            return "account"
    return "api_key" if _api_key_provider(services) else None


async def media_auth(services: SharedServices, user_id: int | None) -> LynxceMediaAuth:
    """The Lynxce endpoint and bearer for one media request, read fresh every time."""
    source = await asyncio.to_thread(media_source, services, user_id)
    if source == "cloud":
        from octop.infra.cloud.bot_cloud.accounts import ensure_media_scopes  # noqa: PLC0415

        assert user_id is not None
        secret = await cloud_model_key(services, user_id)
        await ensure_media_scopes(services, user_id)
        return LynxceMediaAuth(GATEWAY_URL, secret)
    if source == "account":
        from octop.infra.auth.lynxce import get_access_token  # noqa: PLC0415

        assert user_id is not None
        selected = await asyncio.to_thread(account_selection, services, user_id)
        if selected is None:
            raise _auth_required()
        token = await get_access_token(
            services, user_id, expected_connection_id=selected.connection_id
        )
        return LynxceMediaAuth(BASE_URL, token)
    found = await asyncio.to_thread(_api_key_provider, services)
    if found is None:
        raise _auth_required()
    return LynxceMediaAuth(*found)
