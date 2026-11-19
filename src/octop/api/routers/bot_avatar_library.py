"""The signed-in user's reusable Bot portraits."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field

from octop.api.common.upload_limit import read_upload_capped
from octop.api.deps import current_user, get_server
from octop.i18n import tr
from octop.infra.agents.bot_avatar_library import (
    MAX_BATCH,
    MAX_PAGE,
    MAX_PHOTO_BYTES,
    MAX_PHOTOS,
    PhotoId,
    PhotoPage,
    PhotoRef,
    apply_library_photo,
    list_photos,
    store_photo,
)
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.server import OctopServer
from octop.infra.users.identity import User
from octop.infra.utils.locale import resolve_request_locale

router = APIRouter()
logger = logging.getLogger(__name__)
Owner = Annotated[User, Depends(current_user)]
Server = Annotated[OctopServer, Depends(get_server)]


class FailedPhoto(BaseModel):
    name: str
    message: str


class ImportResult(BaseModel):
    imported: list[PhotoRef] = Field(default_factory=list)
    duplicates: list[PhotoRef] = Field(default_factory=list)
    failed: list[FailedPhoto] = Field(default_factory=list)


class SelectedPhoto(BaseModel):
    photo_id: PhotoId


class AppliedPhoto(BaseModel):
    icon_url: str


@router.get("/avatar-library", summary="Browse your saved Bot photos, newest first")
def browse(
    user: Owner,
    server: Server,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = MAX_PAGE,
) -> PhotoPage:
    assert server.services is not None
    return list_photos(server.services, user.id, offset, limit)


@router.post(
    "/avatar-library/import", summary="Import up to 20 photos and report a result for each"
)
async def add(
    request: Request,
    user: Owner,
    server: Server,
    files: Annotated[list[UploadFile], File(min_length=1, max_length=MAX_BATCH)],
) -> ImportResult:
    assert server.services is not None
    result = ImportResult()
    locale = user.locale or resolve_request_locale(request)
    for file in files:
        name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()[:120] or "photo"
        try:
            data = await read_upload_capped(
                file, max_bytes=MAX_PHOTO_BYTES, code=ErrorCode.AVATAR_TOO_LARGE
            )
            status, entry = await asyncio.to_thread(
                store_photo, server.services, user.id, name, data
            )
        except OctopError as exc:
            reason = (
                tr("octop_bot.photo_too_large", locale, size=MAX_PHOTO_BYTES)
                if exc.code == ErrorCode.AVATAR_TOO_LARGE
                else exc.localized_message(locale)
            )
            result.failed.append(FailedPhoto(name=name, message=reason))
            continue
        except Exception:
            logger.exception("Could not import a Bot library photo for user %s", user.id)
            result.failed.append(
                FailedPhoto(name=name, message=tr("octop_bot.photo_import_failed", locale))
            )
            continue
        if status == "full":
            result.failed.append(
                FailedPhoto(
                    name=name, message=tr("octop_bot.photo_capacity", locale, count=MAX_PHOTOS)
                )
            )
        elif status == "duplicate":
            result.duplicates.append(entry)
        else:
            result.imported.append(entry)
    return result


@router.delete(
    "/avatar-library/{photo_id}",
    status_code=204,
    summary="Remove a library photo, keeping Bot portraits",
)
def remove(photo_id: PhotoId, user: Owner, server: Server) -> Response:
    assert server.services is not None
    if not server.services.repos.bot_avatar_photo_repo.delete(user.id, photo_id):
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    return Response(status_code=204)


@router.put("/bots/{agent_id}/avatar-photo", summary="Copy a library photo to an owned Bot")
async def apply(agent_id: str, body: SelectedPhoto, user: Owner, server: Server) -> AppliedPhoto:
    assert server.services is not None and server.app_runtime is not None
    url = await apply_library_photo(
        server.services, server.app_runtime.agent_registry, agent_id, user.id, body.photo_id
    )
    return AppliedPhoto(icon_url=url)
