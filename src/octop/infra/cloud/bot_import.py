"""Preview an owner's private dashboard text and explicitly append it to their hosted session."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, Field

from octop.i18n.domains.attachment import attachment_empty_image, attachment_empty_message
from octop.infra.agents.bot_side import visible_content_text
from octop.infra.agents.bot_workspace import is_private_bot
from octop.infra.auth.lynxce_cloud import request_cloud
from octop.infra.bridge.ids import is_bridge_agent_id
from octop.infra.cloud.bot_work import CloudWorkspace, role_instruction
from octop.infra.cloud.bot_work_models import Write
from octop.infra.db.repos.agents import AgentRow
from octop.infra.db.repos.thread_messages import ThreadMessageRow
from octop.infra.db.repos.threads import ThreadRow
from octop.infra.db.services import SharedServices
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.gateway.process.message_keys import AUTHOR_USER_ID_KEY, STREAM_ERROR_FLAG
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.history.attachment_text import (
    OFFLOAD_PLACEHOLDER_RE,
    extract_dumped_image_refs_from_text,
)
from octop.infra.utils.llm_text import strip_thinking

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MAX_ITEMS = 20
_MAX_CHARS = 24000
_PER_ITEM = 6000
_EMPTY_MEDIA = {
    make(locale)
    for locale in ("en", "zh")
    for make in (attachment_empty_image, attachment_empty_message)
}
_ATTACHMENT_TAIL = re.compile(r"(?m)^\s*\[(?:Attachment(?:\]| text:)|附件(?:\]|正文：))")
_LOCAL_LINK = re.compile(
    r"(!?)\[([^\]]*)\]\((?:workspace://|data:|(?:[^) ]*)/api/|api/)[^)]*\)", re.I
)


class Item(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class Preview(BaseModel):
    title: str
    items: list[Item]
    revision: str


class ImportRequest(Write):
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    model: str = Field(min_length=1, max_length=160)


class Imported(BaseModel):
    session_id: str


@dataclass
class _Snapshot:
    preview: Preview
    dates: list[str]
    attach_role: bool


def _display(row: ThreadMessageRow, owner: int) -> Item | None:
    if row.role not in {"human", "user", "ai", "assistant"}:
        return None
    try:
        wire = json.loads(row.message_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(wire, dict):
        return None
    data = wire.get("data", wire)
    if not isinstance(data, dict):
        return None
    meta = data.get("additional_kwargs") or {}
    if not isinstance(meta, dict):
        return None
    if (
        meta.get("lc_source") == "summarization"
        or meta.get(STREAM_ERROR_FLAG)
        or meta.get("hidden")
        or data.get("hidden")
        or meta.get("team_wrapup")
    ):
        return None
    role: Literal["user", "assistant"] = "user" if row.role in {"user", "human"} else "assistant"
    if role == "user" and str(meta.get(AUTHOR_USER_ID_KEY, owner)) != str(owner):
        return None
    content = data.get("content")
    blocks = content if isinstance(content, list) else [content]
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, dict):
            if block.get("type") != "text" or block.get("hidden"):
                continue
            block = block.get("text")
        if not isinstance(block, str):
            continue
        if OFFLOAD_PLACEHOLDER_RE.match(block):
            continue
        if role == "user":
            # The gateway appends attachment hints and whole extracted documents after the caption.
            body = _ATTACHMENT_TAIL.split(block, maxsplit=1)
            text, _ = extract_dumped_image_refs_from_text(body[0])
            if text.strip() not in _EMPTY_MEDIA:
                parts.append(text)
            if len(body) > 1:
                break
        else:
            parts.append(block)
    text = visible_content_text(parts, role)
    if role == "assistant":
        text = strip_thinking(text)
    text = _LOCAL_LINK.sub(lambda m: "" if m[1] else m[2], text).strip()
    return Item(role=role, content=text) if text else None


def _source(
    services: SharedServices, owner: int, bot_id: str, thread_id: str
) -> tuple[AgentRow, ThreadRow]:
    bot = services.agent_repo.get(bot_id)
    thread = services.thread_repo.get(thread_id)
    if (
        bot is None
        or bot.user_id != owner
        or bot.kind == "team"
        or bot.is_shared
        or is_bridge_agent_id(bot_id)
        or is_private_bot(bot)
        or thread is None
        or thread.agent_id != bot_id
        or thread.user_id != owner
        or thread.channel_type != "dashboard"
        or thread.contributed
        or "~" in thread_id
        or thread.session_key != ThreadRegistry.dashboard_key(agent_id=bot_id, user_id=owner)
        or services.thread_share_repo.get_active_by_thread(thread_id) is not None
    ):
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    return bot, thread


def _snapshot(services: SharedServices, owner: int, bot_id: str, thread_id: str) -> _Snapshot:
    bot, thread = _source(services, owner, bot_id, thread_id)
    repo = services.thread_message_repo
    if repo.projection_status(thread_id) != "ready":
        raise OctopError.localized(ErrorCode.AGENT_BUSY)

    head = repo.head(thread_id)
    end = head
    remaining = _MAX_CHARS
    entries: list[Item] = []
    sequences: list[int] = []
    clocks: list[tuple[int, int]] = []
    while end > 0 and remaining and len(entries) < _MAX_ITEMS:
        start = max(0, end - 32)
        for row in reversed(repo.range_rows(thread_id, start, end)):
            clocks.append((row.seq, row.created_at or thread.created_at))
            item = _display(row, owner)
            if item is None:
                continue
            limit = min(remaining, _PER_ITEM)
            if len(item.content) > limit:
                item.content = item.content[: limit - 1] + "…"
            entries.append(item)
            sequences.append(row.seq)
            remaining -= len(item.content)
            if len(entries) == _MAX_ITEMS or not remaining:
                break
        end = start
    entries.reverse()
    sequences.reverse()
    dates: dict[int, str] = {}
    if clocks:
        # Carry the same prefix maximum across windows. Equal/missing timestamps then
        # retain distinct, stable millisecond IDs even after earlier rows leave the preview.
        base = repo.timestamp_base(thread_id, clocks[-1][0] - 1, thread.created_at)
        needed = set(sequences)
        for seq, seconds in reversed(clocks):
            base = max(base, seconds * 1000 - seq)
            if seq in needed:
                stamp = _EPOCH + timedelta(milliseconds=base + seq)
                dates[seq] = stamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    ordered_dates = [dates[seq] for seq in sequences]
    title = (thread.title or bot.name).strip()[:80] or bot_id
    # The hosted controller counts titles in UTF-16 code units.
    title = title.encode("utf-16-le")[:160].decode("utf-16-le", errors="ignore")
    role = (bot.name[:120], (bot.description or "")[:800]) if bot.kind == "expert" else None
    revision = hashlib.sha256(
        json.dumps(
            [
                owner,
                bot_id,
                thread_id,
                title,
                role,
                ordered_dates,
                [i.model_dump() for i in entries],
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return _Snapshot(
        Preview(title=title, items=entries, revision=revision), ordered_dates, role is not None
    )


def preview(services: SharedServices, owner: int, bot_id: str, thread_id: str) -> Preview:
    return _snapshot(services, owner, bot_id, thread_id).preview


def hosted_session_id(owner: int, bot_id: str, thread_id: str) -> str:
    """The stable ID used when exporting a local conversation to Lynxce."""
    name = json.dumps(["octop-bot/import/v1", owner, bot_id, thread_id], separators=(",", ":"))
    return f"octop-bot-v1-{uuid5(NAMESPACE_URL, name)}"


async def import_chat(
    services: SharedServices, owner: int, bot_id: str, thread_id: str, body: ImportRequest
) -> Imported:
    await asyncio.to_thread(_source, services, owner, bot_id, thread_id)
    workspace = CloudWorkspace(services, owner, body.account_id)
    caps = await workspace.capabilities()
    if not caps.enabled or body.model not in caps.models:
        raise OctopError.localized(ErrorCode.BOT_CLOUD_REQUEST_REJECTED, status=422)
    sid = hosted_session_id(owner, bot_id, thread_id)
    path = f"/api/user/web-chat-sessions/{sid}"
    existing: set[tuple[str, str]] = set()
    model = body.model
    try:
        remote = await request_cloud(
            services, owner, "GET", path, expected_account_id=body.account_id
        )
    except OctopError as exc:
        if exc.code != ErrorCode.NOT_FOUND:
            raise
    else:
        if (
            not isinstance(remote, dict)
            or remote.get("id") != sid
            or not isinstance(remote.get("items"), list)
        ):
            raise OctopError.localized(ErrorCode.NETWORK_ERROR)
        existing = {
            (m["role"], m["createdAt"])
            for m in remote["items"]
            if isinstance(m, dict) and "role" in m and "createdAt" in m
        }
        model = remote.get("model") or model

    snap = await asyncio.to_thread(_snapshot, services, owner, bot_id, thread_id)
    if snap.preview.revision != body.revision:
        raise OctopError.localized(ErrorCode.BOT_CLOUD_REQUEST_REJECTED, status=409)
    if not snap.preview.items:
        raise OctopError.localized(ErrorCode.BOT_CLOUD_REQUEST_REJECTED, status=422)
    items = [
        {**item.model_dump(), "createdAt": date}
        for item, date in zip(snap.preview.items, snap.dates, strict=True)
        if (item.role, date) not in existing
    ]
    if not items:
        return Imported(session_id=sid)
    if snap.attach_role:
        for item in reversed(items):
            if item["role"] == "user":
                item["content"] = await role_instruction(
                    services, owner, bot_id, item["content"], 40000
                )
                break
    result = await request_cloud(
        services,
        owner,
        "POST",
        path + "/items",
        json={"title": snap.preview.title, "model": model, "items": items},
        expected_account_id=body.account_id,
    )
    if (
        not isinstance(result, dict)
        or result.get("id") != sid
        or result.get("appended") != len(items)
    ):
        raise OctopError.localized(ErrorCode.NETWORK_ERROR)
    return Imported(session_id=sid)
