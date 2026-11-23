"""Octop Bot workspace, navigation preferences and snapshot side chats."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, StringConstraints

from octop.api.deps import current_user, get_server
from octop.api.routers.bot_avatar_library import router as avatar_library_router
from octop.api.routers.bot_cloud_account import router as cloud_account_router
from octop.api.routers.bot_cloud_import import router as cloud_import_router
from octop.api.routers.bot_cloud_work import router as cloud_work_router
from octop.api.routers.bot_computer import router as computer_router
from octop.api.routers.bot_lynxce import router as lynxce_router
from octop.api.routers.bot_server import router as server_router
from octop.api.routers.bot_wallet import router as wallet_router
from octop.infra.agents.bot_appearance import Appearance, Character, set_character
from octop.infra.agents.bot_sections import (
    Layout,
    ShortText,
    read_layout,
    save_layout,
    visible_layout,
)
from octop.infra.agents.bot_side import answer_side, reference, search_history
from octop.infra.agents.bot_workspace import (
    bot_activity,
    bot_card,
    chief_key,
    ensure_chief,
    is_private_bot,
    list_bot_cards,
)
from octop.infra.bot_groups.service import GroupActivity, group_activity, list_groups
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import User

router = APIRouter(prefix="/octop-bot")
router.include_router(server_router)
router.include_router(avatar_library_router)
router.include_router(cloud_account_router)
router.include_router(cloud_import_router)
router.include_router(cloud_work_router)
router.include_router(computer_router)
router.include_router(lynxce_router)
router.include_router(wallet_router)


class Bot(BaseModel):
    agent_id: str
    name: str
    description: str | None
    icon_url: str | None
    icon_name: str | None
    color: str | None
    avatar: Appearance
    kind: str
    is_main: bool
    is_private: bool
    can_join_group: bool
    enabled: bool
    default_model: str | None


class Privacy(BaseModel):
    private: bool


def _write_appearance(
    server: Any, user: User, agent_id: str, character: Character | None
) -> Appearance:
    row = server.services.agent_repo.get(agent_id)
    if row is None or row.user_id != user.id or row.kind == "team":
        raise OctopError.localized(ErrorCode.AGENT_NOT_FOUND)
    settings = server.services.settings_repo
    return set_character(settings, row, settings.get(chief_key(user.id)) or "", character)


@router.put("/bots/{agent_id}/appearance", summary="Choose a bot character and color")
def choose_appearance(
    agent_id: str,
    body: Character,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> Appearance:
    return _write_appearance(server, user, agent_id, body)


@router.delete("/bots/{agent_id}/appearance", summary="Restore the bot's original character")
def reset_appearance(
    agent_id: str, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> Appearance:
    return _write_appearance(server, user, agent_id, None)


class RetainedFolder(BaseModel):
    agent_id: str
    name: str
    path: str


@router.get("/retained-folders", summary="List my retained private bot folders")
def retained_folders(
    user: User = Depends(current_user), server: Any = Depends(get_server)
) -> list[RetainedFolder]:
    from octop.infra.agents.bot_privacy import private_dirs

    return [
        RetainedFolder(agent_id=key, name=record["name"], path=record["path"])
        for key, record in private_dirs(server.services.settings_repo).items()
        if record["owner"] == user.id and server.services.agent_repo.get(key) is None
    ]


@router.delete("/retained-folders/{agent_id}", summary="Release a retained folder", status_code=204)
def release_folder(
    agent_id: str, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> None:
    from octop.infra.agents.bot_privacy import release_directory

    release_directory(server.services, user.id, agent_id)


@router.put("/bots/{agent_id}/privacy", summary="Set the privacy of my bot")
async def bot_privacy(
    agent_id: str,
    body: Privacy,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> Bot:
    from octop.infra.agents.bot_privacy import set_privacy

    row = await set_privacy(
        server.services, server.app_runtime.agent_registry, user.id, agent_id, body.private
    )
    return Bot.model_validate(
        await asyncio.to_thread(
            bot_card,
            row,
            server.services.settings_repo.get(chief_key(user.id)) or "",
            server.services.settings_repo,
        )
    )


class TeamMemory(BaseModel):
    text: str = Field(max_length=12000)


@router.get("/memory", summary="Read my team's shared notes")
def read_memory(
    user: User = Depends(current_user), server: Any = Depends(get_server)
) -> TeamMemory:
    return TeamMemory(text=server.services.settings_repo.get(f"octop_bot:memory:{user.id}") or "")


@router.put("/memory", summary="Save the notes my bots share")
def write_memory(
    body: TeamMemory, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> TeamMemory:
    server.services.settings_repo.set(f"octop_bot:memory:{user.id}", body.text)
    return body


class GroupCard(BaseModel):
    group_id: str
    name: str
    admin_id: str
    member_ids: list[str]
    reply_mode: Literal["admin_first", "all_members"]


class Workspace(Layout):
    chief_id: str
    bots: list[Bot]
    groups: list[GroupCard]


@router.get(
    "/workspace",
    summary="Open my bot workspace",
    response_model=Workspace,
    description="Initializes the personal Chief on first entry and lists owned experts and groups.",
)
async def open_workspace(
    user: User = Depends(current_user), server: Any = Depends(get_server)
) -> Workspace:
    services = server.services
    chief_id = await ensure_chief(services, server.app_runtime.agent_registry, user.id)
    cards, groups, layout = await asyncio.gather(
        asyncio.to_thread(list_bot_cards, services, user.id, chief_id),
        asyncio.to_thread(list_groups, services, user.id),
        asyncio.to_thread(read_layout, services, user.id),
    )
    keys = {f"bot:{card['agent_id']}" for card in cards if card["agent_id"] != chief_id}
    layout = visible_layout(layout, keys | {f"group:{g.group_id}" for g in groups})
    return Workspace(
        chief_id=chief_id,
        **layout.model_dump(),
        bots=[Bot.model_validate(card) for card in cards],
        groups=[GroupCard.model_validate(item, from_attributes=True) for item in groups],
    )


class BotActivity(BaseModel):
    agent_id: str
    unread_count: int = Field(description="Unread proactive or room pushes across my threads.")
    last_active: int | None = Field(
        default=None, description="Latest turn time in my own chats with this bot."
    )


class Activity(BaseModel):
    bots: list[BotActivity]
    groups: list[GroupActivity]


@router.get(
    "/activity",
    summary="Poll unread activity across my bots and groups",
    response_model=Activity,
    description="Lightweight snapshot for sidebar badges, the app badge and new-message notifications.",
)
async def read_activity(
    user: User = Depends(current_user), server: Any = Depends(get_server)
) -> Activity:
    bots, groups = await asyncio.gather(
        asyncio.to_thread(bot_activity, server.services, user.id),
        asyncio.to_thread(group_activity, server.services, user.id),
    )
    return Activity(bots=[BotActivity.model_validate(b) for b in bots], groups=groups)


@router.put(
    "/layout",
    summary="Save my bot sidebar sections and pins",
    description="Include the current workspace revision to protect concurrent edits. A stale revision returns HTTP 409.",
)
def update_layout(
    body: Layout, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> Layout:
    return save_layout(server.services, user.id, body)


class SideTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=12000)


class HistoryMatch(BaseModel):
    agent_id: str
    thread_id: str
    title: str
    excerpt: str
    message_seq: int
    message_id: str | None
    part: int = Field(
        description="Conversation part, numbered from one at native compaction boundaries"
    )


class ThreadReference(BaseModel):
    thread_id: ShortText
    message_seq: int | None = Field(None, ge=1)
    message_id: str | None = Field(None, min_length=1, max_length=512)


class HistorySearchStatus(BaseModel):
    matches: list[HistoryMatch]
    indexing: bool = Field(
        description="Legacy checkpoint messages are being indexed. Repeat the search to refresh."
    )


class ReferenceText(BaseModel):
    text: str


@router.get("/history/search", summary="Find a conversation to reference")
async def history_search(
    q: str = Query(default="", max_length=160),
    with_status: bool = False,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> list[HistoryMatch] | HistorySearchStatus:
    from octop.api.routers.chat.share import _queue_projection

    services = server.services
    owners = await asyncio.to_thread(
        services.agent_repo.list_by_user, user.id, include_disabled=False
    )
    indexing = False
    for row in owners:
        if row.kind == "team" or is_private_bot(row):
            continue
        candidates = await asyncio.to_thread(
            services.thread_message_repo.migration_candidates,
            agent_id=row.agent_id,
            user_id=user.id,
            limit=10,
            pending_dashboard_only=True,
        )
        if not candidates:
            continue
        try:
            server.app_runtime.agent_registry.get_agent(row.agent_id)
        except OctopError:
            continue
        indexing = True
        for candidate in candidates:
            _queue_projection(server, row.agent_id, candidate.thread_id, user)
    matches = [
        HistoryMatch.model_validate(item)
        for item in await asyncio.to_thread(search_history, services, user.id, q.strip())
    ]
    return HistorySearchStatus(matches=matches, indexing=indexing) if with_status else matches


@router.post(
    "/bots/{agent_id}/reference",
    summary="Quote an original message or an owned conversation snapshot",
)
def reference_chat(
    agent_id: str,
    body: ThreadReference,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> ReferenceText:
    return ReferenceText(
        text=reference(
            server.services, user.id, agent_id, body.thread_id, body.message_seq, body.message_id
        )
    )


class SideQuestion(BaseModel):
    thread_id: ShortText
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)
    ]
    snapshot_seq: int | None = Field(None, ge=0)
    turns: list[SideTurn] = Field(default_factory=list, max_length=12)


class SideAnswer(BaseModel):
    answer: str
    snapshot_seq: int


@router.post(
    "/bots/{agent_id}/side",
    summary="Ask a side question about a conversation snapshot",
    response_model=SideAnswer,
)
async def side_chat(
    agent_id: str,
    body: SideQuestion,
    user: User = Depends(current_user),
    server: Any = Depends(get_server),
) -> SideAnswer:
    reply = await answer_side(
        server.services,
        server.app_runtime.agent_registry,
        user,
        agent_id,
        body.thread_id,
        body.question,
        body.snapshot_seq,
        [turn.model_dump() for turn in body.turns],
    )
    return SideAnswer.model_validate(reply)
