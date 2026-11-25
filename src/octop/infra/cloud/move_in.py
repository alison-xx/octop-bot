"""Octop Bot cloud: take in the Bots, chats and groups a desktop app kept on its own computer.

Every item names its ``source`` (an id that is stable on the computer it came from). The
cloud remembers what each source became, so a move that stopped halfway can be sent again
without adding anything twice.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import time
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import IO, TYPE_CHECKING, Annotated, Any, Literal

from filelock import AsyncFileLock
from langchain_core.messages import messages_from_dict
from pydantic import BaseModel, Field, StringConstraints, field_validator
from pydantic_core import PydanticKnownError

from octop.infra.agents.bot_appearance import Character, set_character
from octop.infra.agents.bot_workspace import (
    can_join_bot_group,
    chief_key,
    ensure_chief,
    require_own_bot,
)
from octop.infra.agents.memory.thread_cleanup import checkpoint_publication_lock
from octop.infra.agents.threads.fork import write_checkpoint_messages
from octop.infra.auth.lynxce_cloud import _finish
from octop.infra.bot_groups.service import Goal, ReplyMode, create_group
from octop.infra.cloud import move_wire
from octop.infra.db.repos.bot_groups import ImportedTimeline
from octop.infra.db.repos.thread_messages import ThreadMessageInput
from octop.infra.db.services import SharedServices
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.history.projection import message_inputs
from octop.infra.users.identity import User
from octop.infra.utils.ulid import new_ulid

if TYPE_CHECKING:
    from octop.infra.agents.manager import AgentManager

Source = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Text = Annotated[str, StringConstraints(max_length=200_000)]


# Per-account move-in budgets, as (seconds, requests, bytes).
_MOVE_WINDOWS = ((3600, 3000, 300 * 1024 * 1024), (86400, 20000, 1024 * 1024 * 1024))


@dataclass
class _MoveWindow:
    requests: deque[tuple[float, int]] = field(default_factory=deque)
    size: int = 0

    def expire(self, cutoff: float) -> None:
        while self.requests and self.requests[0][0] <= cutoff:
            self.size -= self.requests.popleft()[1]


_move_usage: dict[int, list[_MoveWindow]] = {}
_next_usage_cleanup = 0.0


def charge_move_request(user_id: int, size: int) -> None:
    """Count a request atomically on the server event loop, across all move-in routes."""
    global _next_usage_cleanup
    now = time.monotonic()
    if now >= _next_usage_cleanup:
        cutoff = now - _MOVE_WINDOWS[-1][0]
        for account, windows in list(_move_usage.items()):
            latest = windows[-1].requests
            if not latest or latest[-1][0] <= cutoff:
                del _move_usage[account]
        _next_usage_cleanup = now + _MOVE_WINDOWS[0][0]

    if user_id not in _move_usage:
        _move_usage[user_id] = [_MoveWindow() for _ in _MOVE_WINDOWS]
    windows = _move_usage[user_id]
    for bucket, (duration, max_requests, max_bytes) in zip(windows, _MOVE_WINDOWS, strict=True):
        bucket.expire(now - duration)
        if len(bucket.requests) >= max_requests or bucket.size + size > max_bytes:
            raise OctopError.localized(ErrorCode.BOT_MOVE_IN_LIMITED)
    for bucket in windows:
        bucket.requests.append((now, size))
        bucket.size += size


class MovedBot(BaseModel):
    source: Source
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    description: str | None = Field(default=None, max_length=4000)
    system_prompt: str | None = Field(default=None, max_length=100_000)
    welcome_message: str | None = Field(default=None, max_length=4000)
    look: Character | None = Field(default=None, description="The Bot's character and color.")
    chief: bool = Field(default=False, description="The desktop's Chief: joins the cloud Chief.")


class ThreadHeader(BaseModel):
    source: Source
    bot_id: str = Field(min_length=1, max_length=64, description="The Bot on this server.")
    title: str | None = Field(default=None, max_length=500)
    last_active: int = Field(default=0, ge=0)


class MovedThread(ThreadHeader):
    messages: list[dict[str, Any]] = Field(
        min_length=1,
        max_length=5000,
        description="The conversation as LangChain message dicts (``messages_to_dict``).",
    )

    @field_validator("messages")
    @classmethod
    def bound_message_size(cls, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for message in messages:
            if len(json.dumps(message, ensure_ascii=False, separators=(",", ":"))) > 200_000:
                raise PydanticKnownError("string_too_long", {"max_length": 200_000})
        return messages


class MovedThreadPart(ThreadHeader, move_wire.WirePart):
    message_count: int = Field(ge=1, le=move_wire.MAX_MESSAGES)


class ThreadPartReceipt(BaseModel):
    next_offset: int = Field(description="First byte the cloud still needs.")
    id: str | None = Field(default=None, description="Cloud thread ID after complete publication.")


class MovedGroupMessage(BaseModel):
    request_id: Source
    slot: Source
    role: Literal["user", "assistant", "error", "pass"]
    agent_id: str | None = Field(default=None, max_length=64)
    text: Text
    created_at: int = Field(ge=0)


class GroupHeader(BaseModel):
    source: Source
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    admin_id: str = Field(min_length=1, max_length=64)
    member_ids: list[str] = Field(max_length=64)
    reply_mode: ReplyMode = "admin_first"
    memory: str = Field(default="", max_length=200_000)
    goal: Goal | None = None


class MovedGroup(GroupHeader):
    messages: list[MovedGroupMessage] = Field(default_factory=list, max_length=20_000)


class MovedGroupPart(GroupHeader, move_wire.WirePart):
    message_count: int = Field(ge=1, le=20_000)


class GroupPartReceipt(ThreadPartReceipt):
    id: str | None = Field(default=None, description="Cloud group ID after complete publication.")


class PagedGroupMessage(MovedGroupMessage):
    # Wire bytes and account quotas bound uploads. A stored assistant reply can exceed one page.
    text: str


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
    await asyncio.to_thread(require_own_bot, services, user.id, body.bot_id)
    key = _key(user.id, "thread", body.source)
    async with AsyncFileLock(services.paths.root / f".move-chats-{user.id}.lock"):
        known = await _existing_thread(services, threads, user, body, key)
        if known:
            return Moved(id=known)
        tid = await _finish(
            _publish_thread(services, registry, threads, user, body, key, iter([body.messages]))
        )
        await asyncio.to_thread(move_wire.discard_upload, services.settings_repo, key)
        return Moved(id=tid)


async def _existing_thread(
    services: SharedServices, threads: ThreadRegistry, user: User, body: ThreadHeader, key: str
) -> str | None:
    known = await asyncio.to_thread(services.settings_repo.get, key)
    if known:
        row = await asyncio.to_thread(threads.get_thread, known)
        if row:
            if row.user_id != user.id or row.agent_id != body.bot_id:
                raise OctopError.localized(ErrorCode.FORBIDDEN)
            await asyncio.to_thread(move_wire.discard_upload, services.settings_repo, key)
            return known
    return None


async def move_thread_part(
    services: SharedServices,
    registry: AgentManager,
    threads: ThreadRegistry,
    user: User,
    body: MovedThreadPart,
) -> ThreadPartReceipt:
    await asyncio.to_thread(require_own_bot, services, user.id, body.bot_id)
    key = _key(user.id, "thread", body.source)
    async with AsyncFileLock(services.paths.root / f".move-chats-{user.id}.lock"):
        known = await _existing_thread(services, threads, user, body, key)
        if known:
            return ThreadPartReceipt(next_offset=body.total, id=known)
        offset, page_count = await _finish(
            asyncio.to_thread(move_wire.stage_page, services.settings_repo, key, body)
        )
        if offset < body.total:
            return ThreadPartReceipt(next_offset=offset)
        batches = move_wire.read_batches(
            services.settings_repo, key + ":parts", page_count, body.snapshot, body.message_count
        )
        try:
            tid = await _finish(
                _publish_thread(services, registry, threads, user, body, key, batches)
            )
        except move_wire.InvalidUpload:
            # The durable bytes are missing or inconsistent; resending the same source restarts at zero.
            await _finish(asyncio.to_thread(move_wire.discard_upload, services.settings_repo, key))
            return ThreadPartReceipt(next_offset=0)
        await _finish(asyncio.to_thread(move_wire.discard_upload, services.settings_repo, key))
        return ThreadPartReceipt(next_offset=offset, id=tid)


async def _publish_thread(
    services: SharedServices,
    registry: AgentManager,
    threads: ThreadRegistry,
    user: User,
    body: ThreadHeader,
    key: str,
    batches: Iterator[list[dict[str, Any]]],
) -> str:
    try:
        harness = registry.get_agent(body.bot_id)
    except OctopError as exc:
        if exc.code != ErrorCode.AGENT_NOT_RUNNING:
            raise
        await registry.start(body.bot_id)
        harness = registry.get_agent(body.bot_id)
    tid = f"thr_{new_ulid()}"
    position = 0
    async with AsyncFileLock(checkpoint_publication_lock(services.paths.root, body.bot_id)):
        # Project incrementally on disk. Only the current page or one long message needs decoding.
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as projection:
            try:
                while batch := await asyncio.to_thread(next, batches, None):
                    try:
                        messages = messages_from_dict(batch)
                    except (KeyError, TypeError, ValueError):
                        raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS, status=422) from None
                    for message in messages:
                        if not message.id:
                            message.id = f"{tid}:{position}"
                        position += 1
                    await write_checkpoint_messages(harness, thread_id=tid, messages=messages)
                    await asyncio.to_thread(_save_projection, projection, messages)
                await asyncio.to_thread(
                    services.thread_repo.insert,
                    thread_id=tid,
                    agent_id=body.bot_id,
                    user_id=user.id,
                    channel_type=threads.CHANNEL_DASHBOARD,
                    session_key=threads.dashboard_key(agent_id=body.bot_id, user_id=user.id),
                    title=body.title,
                    last_active=body.last_active,
                    initial_messages=_read_projection(projection),
                    restore_entry=(key, tid),
                )
            except Exception:
                await registry.delete_thread_checkpoint(body.bot_id, tid, reclaim=False)
                raise
    return tid


def _save_projection(projection: IO[str], messages: list[Any]) -> None:
    for m in message_inputs(messages):
        projection.write(
            json.dumps([m.message_id, m.role, m.message_json, m.created_at], ensure_ascii=False)
            + "\n"
        )


def _read_projection(projection: IO[str]) -> Iterator[ThreadMessageInput]:
    projection.seek(0)
    for line in projection:
        yield ThreadMessageInput(*json.loads(line))


def move_group(services: SharedServices, user: User, body: MovedGroup) -> Moved:
    key = _key(user.id, "group", body.source)
    known = services.settings_repo.get(key)
    if known and services.repos.bot_group_repo.get(known, user.id):
        result = Moved(id=known)
    else:
        admin, members = _group_roster(services, user, body)
        result = _publish_group(
            services,
            user,
            body,
            admin,
            members,
            ImportedTimeline(
                key, body.memory, _group_goal(body, members), _group_messages(body, members)
            ),
        )
    move_wire.discard_upload(services.settings_repo, key)
    return result


def _group_roster(services: SharedServices, user: User, body: GroupHeader) -> tuple[str, list[str]]:
    def joinable(agent_id: str) -> bool:
        row = services.agent_repo.get(agent_id)
        return row is not None and row.user_id == user.id and can_join_bot_group(row)

    chief_id = services.settings_repo.get(chief_key(user.id)) or ""
    admin = body.admin_id if joinable(body.admin_id) else chief_id
    members = list(dict.fromkeys([admin, *(i for i in body.member_ids if joinable(i))]))
    return admin, members


def _group_messages(body: MovedGroup, members: list[str]) -> list[dict[str, Any]]:
    return [
        {**m.model_dump(), "agent_id": m.agent_id if m.agent_id in members else None}
        for m in body.messages
        if m.role == "user" or m.agent_id in members
    ]


def _group_goal(body: GroupHeader, members: list[str]) -> str | None:
    if body.goal is None:
        return None
    goal = body.goal.model_copy(deep=True)
    for stage in goal.stages:
        if stage.assignee_id not in members:
            stage.assignee_id = None
    return goal.model_dump_json()


def _publish_group(
    services: SharedServices,
    user: User,
    body: GroupHeader,
    admin: str,
    members: list[str],
    imported: ImportedTimeline,
) -> Moved:
    group = create_group(
        services,
        user.id,
        name=body.name,
        admin_id=admin,
        member_ids=members,
        reply_mode=body.reply_mode,
        imported=imported,
    )
    return Moved(id=group.group_id)


async def receive_group(services: SharedServices, user: User, body: MovedGroup) -> Moved:
    async with AsyncFileLock(services.paths.root / f".move-groups-{user.id}.lock"):
        return await _finish(asyncio.to_thread(move_group, services, user, body))


async def move_group_part(
    services: SharedServices, user: User, body: MovedGroupPart
) -> GroupPartReceipt:
    async with AsyncFileLock(services.paths.root / f".move-groups-{user.id}.lock"):
        return await _finish(asyncio.to_thread(_stage_group_part, services, user, body))


def _stage_group_part(
    services: SharedServices, user: User, body: MovedGroupPart
) -> GroupPartReceipt:
    settings = services.settings_repo
    key = _key(user.id, "group", body.source)
    known = settings.get(key)
    if known and services.repos.bot_group_repo.get(known, user.id):
        move_wire.discard_upload(settings, key)
        return GroupPartReceipt(next_offset=body.total, id=known)
    offset, pages = move_wire.stage_page(settings, key, body)
    if offset < body.total:
        return GroupPartReceipt(next_offset=offset)
    admin, members = _group_roster(services, user, body)
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as timeline:
        try:
            for batch in move_wire.read_batches(
                settings, key + ":parts", pages, body.snapshot, body.message_count
            ):
                for raw in batch:
                    msg = PagedGroupMessage.model_validate(raw)
                    if msg.role != "user" and msg.agent_id not in members:
                        continue
                    if msg.agent_id not in members:
                        msg.agent_id = None
                    timeline.write(msg.model_dump_json() + "\n")
        except move_wire.InvalidUpload:
            move_wire.discard_upload(settings, key)
            return GroupPartReceipt(next_offset=0)
        except ValueError:
            raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS, status=422) from None
        timeline.seek(0)
        imported = ImportedTimeline(
            key, body.memory, _group_goal(body, members), (json.loads(line) for line in timeline)
        )
        group = _publish_group(services, user, body, admin, members, imported)
    move_wire.discard_upload(settings, key)
    return GroupPartReceipt(next_offset=offset, id=group.id)


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
