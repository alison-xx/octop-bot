"""Octop Bot cloud: take in the Bots, chats and groups a desktop app kept on its own computer.

Every item names its ``source`` (an id that is stable on the computer it came from). The
cloud remembers what each source became, so a move that stopped halfway can be sent again
without adding anything twice.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING, Annotated, Any, Literal

from langchain_core.messages import messages_from_dict
from pydantic import BaseModel, Field, StringConstraints

from octop.infra.agents.bot_appearance import Character, set_character
from octop.infra.agents.bot_workspace import (
    can_join_bot_group,
    chief_key,
    ensure_chief,
    require_own_bot,
)
from octop.infra.agents.threads.fork import write_checkpoint_messages
from octop.infra.bot_groups.service import Goal, ReplyMode, create_group
from octop.infra.db.services import SharedServices
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.history.projection import message_inputs
from octop.infra.users.identity import User

if TYPE_CHECKING:
    from octop.infra.agents.manager import AgentManager

Source = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Text = Annotated[str, StringConstraints(max_length=200_000)]


class MovedBot(BaseModel):
    source: Source
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    description: str | None = Field(default=None, max_length=4000)
    system_prompt: str | None = Field(default=None, max_length=100_000)
    welcome_message: str | None = Field(default=None, max_length=4000)
    look: Character | None = Field(default=None, description="The Bot's character and color.")
    chief: bool = Field(default=False, description="The desktop's Chief: joins the cloud Chief.")


class MovedThread(BaseModel):
    source: Source
    bot_id: str = Field(min_length=1, max_length=64, description="The Bot on this server.")
    title: str | None = Field(default=None, max_length=500)
    last_active: int = Field(default=0, ge=0)
    messages: list[dict[str, Any]] = Field(
        min_length=1,
        max_length=5000,
        description="The conversation as LangChain message dicts (``messages_to_dict``).",
    )


class MovedGroupMessage(BaseModel):
    request_id: Source
    slot: Source
    role: Literal["user", "assistant", "error", "pass"]
    agent_id: str | None = Field(default=None, max_length=64)
    text: Text
    created_at: int = Field(ge=0)


class MovedGroup(BaseModel):
    source: Source
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    admin_id: str = Field(min_length=1, max_length=64)
    member_ids: list[str] = Field(max_length=64)
    reply_mode: ReplyMode = "admin_first"
    memory: str = Field(default="", max_length=200_000)
    goal: Goal | None = None
    messages: list[MovedGroupMessage] = Field(default_factory=list, max_length=20_000)


class MovedNotes(BaseModel):
    text: Text


class Moved(BaseModel):
    id: str = Field(description="What the source became on this server.")


def _key(user_id: int, kind: str, source: str) -> str:
    digest = hashlib.sha256(source.encode()).hexdigest()[:40]
    return f"octop_bot:moved:{user_id}:{kind}:{digest}"


async def move_bot(
    services: SharedServices, registry: AgentManager, user: User, body: MovedBot
) -> Moved:
    from octop.infra.agents.manager import AgentCreateSpec  # noqa: PLC0415

    chief_id = await ensure_chief(services, registry, user.id)
    if body.chief:
        return Moved(id=chief_id)
    key = _key(user.id, "bot", body.source)
    known = await asyncio.to_thread(services.settings_repo.get, key)
    if known and _own_bot(services, user.id, known):
        return Moved(id=known)
    rows = await asyncio.to_thread(services.agent_repo.list_by_user, user.id)
    # The same Bot made on a phone already: its chats and groups join that one.
    row = next(
        (r for r in rows if r.kind != "team" and r.agent_id != chief_id and r.name == body.name),
        None,
    )
    if row is None:
        row = await registry.create(
            AgentCreateSpec(
                name=body.name,
                user_id=user.id,
                description=body.description,
                system_prompt=body.system_prompt,
                welcome_message=body.welcome_message,
            )
        )
        if body.look is not None:
            await asyncio.to_thread(set_character, services.settings_repo, row, chief_id, body.look)
    await asyncio.to_thread(services.settings_repo.set, key, row.agent_id)
    return Moved(id=row.agent_id)


def _own_bot(services: SharedServices, user_id: int, agent_id: str) -> bool:
    try:
        require_own_bot(services, user_id, agent_id)
    except OctopError:
        return False
    return True


async def move_thread(
    services: SharedServices,
    registry: AgentManager,
    threads: ThreadRegistry,
    user: User,
    body: MovedThread,
) -> Moved:
    key = _key(user.id, "thread", body.source)
    known = await asyncio.to_thread(services.settings_repo.get, key)
    if known and await asyncio.to_thread(threads.get_thread, known) is not None:
        return Moved(id=known)
    await asyncio.to_thread(require_own_bot, services, user.id, body.bot_id)
    try:
        messages = messages_from_dict(body.messages)
    except (KeyError, TypeError, ValueError):
        raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS, status=422) from None
    try:
        harness = registry.get_agent(body.bot_id)
    except OctopError:
        await registry.start(body.bot_id)
        harness = registry.get_agent(body.bot_id)
    thread_id = threads.create_thread(
        agent_id=body.bot_id,
        user_id=user.id,
        channel_type=ThreadRegistry.CHANNEL_DASHBOARD,
        session_key=ThreadRegistry.dashboard_key(agent_id=body.bot_id, user_id=user.id),
        title=body.title,
        last_active=body.last_active,
    )
    try:
        # The Bot remembers the chat (its checkpoint) and the app shows it (the projection).
        await write_checkpoint_messages(harness, thread_id=thread_id, messages=messages)
        await asyncio.to_thread(
            services.thread_message_repo.append_if_ready, thread_id, message_inputs(messages)
        )
    except Exception:
        threads.delete_thread(thread_id)
        raise
    await asyncio.to_thread(services.settings_repo.set, key, thread_id)
    return Moved(id=thread_id)


def move_group(services: SharedServices, user: User, body: MovedGroup) -> Moved:
    key = _key(user.id, "group", body.source)
    known = services.settings_repo.get(key)
    if known and services.repos.bot_group_repo.get(known, user.id) is not None:
        return Moved(id=known)

    # A same-name Bot joined on this server may be private, which keeps it out of groups.
    def joinable(agent_id: str) -> bool:
        row = services.agent_repo.get(agent_id)
        return row is not None and row.user_id == user.id and can_join_bot_group(row)

    chief_id = services.settings_repo.get(chief_key(user.id)) or ""
    admin_id = body.admin_id if joinable(body.admin_id) else chief_id
    group = create_group(
        services,
        user.id,
        name=body.name,
        admin_id=admin_id,
        member_ids=[i for i in body.member_ids if joinable(i)],
        reply_mode=body.reply_mode,
    )
    repo = services.repos.bot_group_repo
    if body.memory:
        repo.set_memory(group.group_id, user.id, body.memory)
    if body.goal is not None:
        repo.set_goal(group.group_id, user.id, body.goal.model_dump_json(), None)
    members = set(group.member_ids)
    repo.import_messages(
        group.group_id,
        [
            {**m.model_dump(), "agent_id": m.agent_id if m.agent_id in members else None}
            for m in body.messages
            if m.role == "user" or m.agent_id in members
        ],
    )
    # The moved timeline counts as read, like it was on the computer it came from.
    repo.mark_read(group.group_id, user.id)
    services.settings_repo.set(key, group.group_id)
    return Moved(id=group.group_id)


def move_notes(services: SharedServices, user: User, body: MovedNotes) -> None:
    """Add the computer's team notes below the cloud's own, once."""
    text = body.text.strip()
    if not text:
        return
    key = f"octop_bot:memory:{user.id}"
    current = services.settings_repo.get(key) or ""
    if text in current:
        return
    merged = f"{current.rstrip()}\n\n{text}" if current.strip() else text
    # The notes editor saves at most this much.
    services.settings_repo.set(key, merged[:12000])


def goal_json(raw: str | None) -> dict[str, Any] | None:
    """A stored Goal as sent to the cloud, or None when it no longer validates."""
    if not raw:
        return None
    try:
        return Goal.model_validate_json(raw).model_dump()
    except ValueError:
        return None
