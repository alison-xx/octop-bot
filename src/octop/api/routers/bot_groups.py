"""Authenticated room timelines and Goals for the Octop Bot workspace."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints

from octop.api.common.content_disposition import content_disposition
from octop.api.common.upload_limit import read_upload_capped
from octop.api.deps import current_user, get_server, require_permission
from octop.infra.bot_groups.im import ImSession, im_sessions, set_binding
from octop.infra.bot_groups.service import (
    Goal,
    Group,
    Message,
    Name,
    ReplyMode,
    create_group,
    get_goal,
    group_row,
    list_groups,
    list_messages,
    set_goal,
    update_group,
)
from octop.infra.bot_groups.turns import run_confirmed_goal, send_message
from octop.infra.bot_groups.workspace import (
    download_artifact,
    list_artifacts,
    room_root,
    upload_artifact,
)
from octop.infra.db.services import SharedServices
from octop.infra.server import OctopServer
from octop.infra.users.identity import User

router = APIRouter(prefix="/octop-bot/groups")


def _services(server: OctopServer = Depends(get_server)) -> SharedServices:
    assert server.services is not None
    return server.services


Services = Annotated[SharedServices, Depends(_services)]
Owner = Annotated[User, Depends(current_user)]
ChannelOwner = Annotated[User, Depends(require_permission("channels"))]


class ImBinding(BaseModel):
    channel_id: str = Field(min_length=1)
    session_key: str = Field(min_length=1)
    linked: bool


@router.get("/{group_id}/im-sessions", summary="List paired IM conversations available to a room")
def room_im_sessions(group_id: str, services: Services, user: ChannelOwner) -> list[ImSession]:
    return im_sessions(services, user.id, group_id)


@router.put("/{group_id}/im-sessions", summary="Link or unlink a paired IM conversation")
def bind_room_im(
    group_id: str, body: ImBinding, services: Services, user: ChannelOwner
) -> list[ImSession]:
    return set_binding(services, user.id, group_id, **body.model_dump())


class GroupSettings(BaseModel):
    name: Name
    admin_id: Name
    member_ids: list[Name] = Field(default_factory=list, max_length=64)
    reply_mode: ReplyMode = "admin_first"


class GroupPatch(BaseModel):
    name: Name | None = None
    admin_id: Name | None = None
    member_ids: list[Name] | None = Field(default=None, max_length=64)
    reply_mode: ReplyMode | None = None


class RoomInput(BaseModel):
    request_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    text: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100000)] = ""
    mention_ids: list[Name] = Field(default_factory=list, max_length=64)
    attachment_paths: list[Annotated[str, StringConstraints(min_length=1, max_length=1024)]] = (
        Field(default_factory=list, max_length=16)
    )


class RoomMemory(BaseModel):
    text: str = Field(max_length=24000)


class RoomFile(BaseModel):
    name: str
    path: str
    is_dir: bool


class MemberDraft(BaseModel):
    agent_id: str
    request_id: str
    text: str


@router.get("/{group_id}/drafts", summary="Read live replies by group member")
def drafts(group_id: str, services: Services, user: Owner) -> list[MemberDraft]:
    group_row(services, user.id, group_id)
    return [
        MemberDraft.model_validate(row)
        for row in services.repos.bot_group_repo.drafts(group_id, user.id)
    ]


@router.get("/{group_id}/files", summary="List shared files in a Bot group")
def files(group_id: str, services: Services, user: Owner, path: str = ".") -> list[RoomFile]:
    return [
        RoomFile.model_validate(row) for row in list_artifacts(services, user.id, group_id, path)
    ]


@router.get(
    "/{group_id}/file",
    summary="Download a shared file from a Bot group",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
def file(group_id: str, path: str, services: Services, user: Owner) -> Response:
    name, data = download_artifact(services, user.id, group_id, path)
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": content_disposition(name)},
    )


@router.post(
    "/{group_id}/files",
    status_code=201,
    summary="Upload an attachment to the group's shared workspace",
)
async def upload(
    group_id: str, services: Services, user: Owner, file: Annotated[UploadFile, File()]
) -> RoomFile:
    root = await asyncio.to_thread(room_root, services, user.id, group_id)
    data = await read_upload_capped(file, max_bytes=services.config.max_upload_bytes)
    entry = await asyncio.to_thread(upload_artifact, root, file.filename or "", data)
    return RoomFile.model_validate(entry)


@router.get("", summary="List my Bot groups")
def groups(services: Services, user: Owner) -> list[Group]:
    return list_groups(services, user.id)


@router.post("", summary="Create a Bot group", status_code=201)
def create(body: GroupSettings, services: Services, user: Owner) -> Group:
    return create_group(services, user.id, **body.model_dump())


@router.get("/{group_id}", summary="Get a Bot group")
def detail(group_id: str, services: Services, user: Owner) -> Group:
    return Group.from_record(group_row(services, user.id, group_id))


@router.patch("/{group_id}", summary="Change group settings and members")
def edit(group_id: str, body: GroupPatch, services: Services, user: Owner) -> Group:
    return update_group(services, user.id, group_id, body.model_dump(exclude_none=True))


@router.delete("/{group_id}", summary="Delete my Bot group", status_code=204)
def delete(group_id: str, services: Services, user: Owner) -> None:
    group_row(services, user.id, group_id)
    services.repos.bot_group_repo.delete(group_id, user.id)


@router.get("/{group_id}/messages", summary="Read a Bot group timeline")
def messages(
    group_id: str,
    services: Services,
    user: Owner,
    after_id: str | None = Query(
        default=None, description="Return messages following this room message ID."
    ),
) -> list[Message]:
    return list_messages(services, user.id, group_id, after_id=after_id)


@router.post(
    "/{group_id}/messages",
    summary="Send a group message and run its recipients",
    description="Mentioned members work in parallel. Reuse request_id to retrieve a turn without dispatching twice.",
)
async def post(
    group_id: str,
    body: RoomInput,
    services: Services,
    user: Owner,
    server: OctopServer = Depends(get_server),
) -> list[Message]:
    assert server.app_runtime is not None
    return await send_message(services, server.app_runtime, user, group_id, **body.model_dump())


@router.get("/{group_id}/goal", summary="Read the group Goal and evidence")
def goal(group_id: str, services: Services, user: Owner) -> Goal | None:
    return get_goal(services, user.id, group_id)


@router.put("/{group_id}/goal", summary="Set or confirm the group Goal")
def save_goal(
    group_id: str,
    body: Goal,
    services: Services,
    user: Owner,
    background_tasks: BackgroundTasks,
    server: OctopServer = Depends(get_server),
) -> Goal:
    prior = get_goal(services, user.id, group_id)
    saved = set_goal(services, user.id, group_id, body)
    if saved.status == "active" and (prior is None or prior.status != "active"):
        assert server.app_runtime is not None
        background_tasks.add_task(
            run_confirmed_goal, services, server.app_runtime, user, group_id, saved
        )
    return saved


@router.get("/{group_id}/memory", summary="Read this group's shared memory")
def memory(group_id: str, services: Services, user: Owner) -> RoomMemory:
    return RoomMemory(text=group_row(services, user.id, group_id)["memory"])


@router.put("/{group_id}/memory", summary="Edit this group's shared memory")
def save_memory(group_id: str, body: RoomMemory, services: Services, user: Owner) -> RoomMemory:
    group_row(services, user.id, group_id)
    services.repos.bot_group_repo.set_memory(group_id, user.id, body.text)
    return body
