"""Personal, content-addressed photo library and native expert avatar application."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from typing import TYPE_CHECKING, Annotated, Literal
from weakref import WeakValueDictionary

from pydantic import BaseModel, Field

from octop.infra.agents.experts.avatar import (
    agent_avatar_api_path,
    sniff_avatar_media_type,
    write_workspace_avatar,
)
from octop.infra.errors import ErrorCode, OctopError

if TYPE_CHECKING:
    from octop.infra.agents.manager import AgentManager
    from octop.infra.db.services import SharedServices

# DS-Bot's 160,000-character data URL limit, including the longest MIME prefix.
MAX_PHOTO_BYTES = ((160_000 - len("data:image/jpeg;base64,")) // 4) * 3
MAX_PHOTOS = 500
MAX_BATCH = 20
MAX_PAGE = 48
PhotoId = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
_apply_locks: WeakValueDictionary[tuple[int, str], asyncio.Lock] = WeakValueDictionary()


class PhotoRef(BaseModel):
    id: PhotoId
    name: str


class Photo(PhotoRef):
    mime: str
    bytes: int
    created_at: int = Field(description="Unix time in milliseconds")
    image: str = Field(description="A data URL for this page's thumbnail")


class PhotoPage(BaseModel):
    items: list[Photo]
    total: int
    next: int


class PhotoRefPage(BaseModel):
    items: list[PhotoRef]
    total: int
    next: int


def list_photo_refs(
    services: SharedServices, user_id: int, offset: int = 0, limit: int = MAX_PAGE
) -> PhotoRefPage:
    offset = max(0, offset)
    count, rows = services.repos.bot_avatar_photo_repo.page(
        user_id, offset, max(1, min(MAX_PAGE, limit)), with_content=False
    )
    items = [PhotoRef(id=row["photo_id"], name=row["name"]) for row in rows]
    return PhotoRefPage(items=items, total=count, next=offset + len(items))


def list_photos(services: SharedServices, owner: int, offset: int, limit: int) -> PhotoPage:
    count, rows = services.repos.bot_avatar_photo_repo.page(owner, offset, limit, with_content=True)
    items = []
    for row in rows:
        data = bytes(row["content"])
        preview = base64.b64encode(data).decode("ascii")
        items.append(
            Photo(
                id=row["photo_id"],
                name=row["name"],
                mime=row["mime"],
                bytes=len(data),
                created_at=row["created_at"],
                image=f"data:{row['mime']};base64,{preview}",
            )
        )
    return PhotoPage(items=items, total=count, next=offset + len(items))


def store_photo(
    services: SharedServices, owner: int, name: str, data: bytes
) -> tuple[Literal["imported", "duplicate", "full"], PhotoRef]:
    if len(data) > MAX_PHOTO_BYTES:
        raise OctopError.localized(ErrorCode.AVATAR_TOO_LARGE)
    mime = sniff_avatar_media_type(data)
    digest = hashlib.sha256(data).hexdigest()
    status, saved_name = services.repos.bot_avatar_photo_repo.store(
        owner, digest, name, mime, data, capacity=MAX_PHOTOS
    )
    return status, PhotoRef(id=digest, name=saved_name)


async def apply_library_photo(
    services: SharedServices, registry: AgentManager, agent_id: str, user_id: int, photo_id: str
) -> str:
    from octop.infra.agents.bot_appearance import mark_bot_photo

    lock = _apply_locks.setdefault((id(registry), agent_id), asyncio.Lock())
    async with lock:
        row = await asyncio.to_thread(services.agent_repo.get, agent_id)
        if row is None or row.user_id != user_id or row.kind == "team":
            raise OctopError.localized(ErrorCode.AGENT_NOT_FOUND)
        data = await asyncio.to_thread(
            services.repos.bot_avatar_photo_repo.content, user_id, photo_id
        )
        if data is None:
            raise OctopError.localized(ErrorCode.NOT_FOUND)
        workspace = await asyncio.to_thread(registry.workspace_for_agent, agent_id)
        if workspace is None:
            raise OctopError.localized(ErrorCode.AGENT_NOT_FOUND)
        await write_workspace_avatar(workspace, data)
        icon_url = f"{agent_avatar_api_path(agent_id)}?photo={photo_id}"
        updated = await asyncio.to_thread(registry.set_icon_url, agent_id, icon_url)
        await asyncio.to_thread(mark_bot_photo, services.settings_repo, updated)
        return icon_url
