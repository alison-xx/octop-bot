"""The current Octop Bot user's own model vendor keys (我的 API Key)."""

from __future__ import annotations

import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from octop.api.common.bot_desktop import AccountServices, Owner
from octop.api.deps import get_server
from octop.infra.agents.providers import lynxce as models
from octop.infra.agents.providers import own_keys
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.server import OctopServer

router = APIRouter(prefix="/model-keys")


class VendorModel(BaseModel):
    id: str
    name: str


class Vendor(BaseModel):
    id: str = Field(description="Pass as `vendor` when adding a key.")
    name: str
    vendor: str = Field(description="Company, e.g. `tencent`, `aliyun`, `volcengine`.")
    logo_id: str = Field(description="Icon key in the dashboard's provider icon set.")
    base_url: str
    protocol: Literal["openai", "anthropic"]
    api_key_prefix: str = Field(description="Usual key prefix, for the input hint; may be empty.")
    models: list[VendorModel] = Field(description="Suggested models; the key may list more.")


class VendorCatalog(BaseModel):
    vendors: list[Vendor]
    custom_allowed: bool = Field(
        description="Whether a custom OpenAI-compatible URL may be added (desktop only; cloud "
        "accounts use the listed vendors)."
    )


class OwnKeyView(BaseModel):
    id: str
    vendor: str = Field(description="Vendor id from the catalog, or `custom`.")
    name: str
    base_url: str
    key_hint: str = Field(description="The key is never returned; this is `****` + last four.")
    models: list[VendorModel]
    created_at: float


class OwnKeyList(BaseModel):
    keys: list[OwnKeyView]
    in_use: str | None = Field(description="Id of the key the user is chatting on, if any.")
    selected_model: str | None


class AddKey(BaseModel):
    vendor: str = Field(min_length=1, max_length=80, description="Catalog vendor id or `custom`.")
    api_key: str = Field(min_length=1, max_length=4096)
    name: str | None = Field(default=None, max_length=60, description="Optional label.")
    base_url: str | None = Field(
        default=None, max_length=512, description="Only for `custom` (desktop)."
    )
    protocol: Literal["openai", "anthropic"] | None = Field(
        default=None, description="Only for `custom`; defaults to `openai`."
    )


class UseModel(BaseModel):
    model_id: str = Field(min_length=1, max_length=512, description="One of this key's models.")


def _view(key: own_keys.OwnKey) -> OwnKeyView:
    return OwnKeyView.model_validate(key.public())


async def _rebuild(server: OctopServer, user_id: int) -> None:
    if server.app_runtime is not None:
        await server.app_runtime.agent_registry.on_account_model_selected(user_id)


@router.get("/vendors", summary="List model vendors I can add my own API key for")
def vendors(user: Owner, services: AccountServices) -> VendorCatalog:
    del user, services
    return VendorCatalog(
        vendors=[Vendor.model_validate(v) for v in own_keys.vendor_catalog()],
        custom_allowed=own_keys.custom_urls_allowed(),
    )


@router.get("", summary="List my own model vendor keys")
def list_keys(user: Owner, services: AccountServices) -> OwnKeyList:
    return OwnKeyList(
        keys=[_view(k) for k in own_keys.list_keys(services, user.id)],
        in_use=models.own_key_in_use(services, user.id),
        selected_model=models.selected_account_model(services, user.id),
    )


@router.post(
    "",
    status_code=201,
    summary="Add my own model vendor key",
    description="Checks the key with the vendor (its model list) before keeping it. The key is "
    "stored encrypted for this user only and never returned. Chats on it are billed by the "
    "vendor, not in Lynxce credits.",
)
async def add_key(body: AddKey, user: Owner, services: AccountServices) -> OwnKeyView:
    key = await own_keys.add_key(
        services,
        user.id,
        vendor=body.vendor,
        api_key=body.api_key,
        name=body.name,
        base_url=body.base_url,
        protocol=body.protocol,
    )
    return _view(key)


@router.delete(
    "/{key_id}",
    status_code=204,
    summary="Remove my own model vendor key",
    description="If I was chatting on it, my Bots go back to the default model.",
)
async def remove_key(
    key_id: str,
    user: Owner,
    services: AccountServices,
    server: Annotated[OctopServer, Depends(get_server)],
) -> None:
    in_use = models.own_key_in_use(services, user.id) == key_id
    if not await asyncio.to_thread(own_keys.remove_key, services, user.id, key_id):
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    if in_use:
        await asyncio.to_thread(models.leave_own_key, services, user.id)
        await _rebuild(server, user.id)


@router.put("/{key_id}/model", summary="Chat on a model of my own vendor key")
async def use_model(
    key_id: str,
    body: UseModel,
    user: Owner,
    services: AccountServices,
    server: Annotated[OctopServer, Depends(get_server)],
) -> OwnKeyList:
    await models.select_own_model(services, user.id, key_id, body.model_id)
    await _rebuild(server, user.id)
    return list_keys(user, services)
