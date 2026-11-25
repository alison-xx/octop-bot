"""Restore ordinary legacy mobile conversations from a cloud tenant's own Lynxce history."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from filelock import AsyncFileLock
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel, Field

from octop.infra.agents.bot_workspace import ensure_chief
from octop.infra.agents.manager import AgentManager
from octop.infra.agents.memory.thread_cleanup import checkpoint_publication_lock
from octop.infra.agents.threads.fork import write_checkpoint_messages
from octop.infra.auth import lynxce_cloud
from octop.infra.cloud.bot_cloud.accounts import SSO_KIND
from octop.infra.cloud.bot_import import hosted_session_id
from octop.infra.cloud.bot_work import is_regular_session
from octop.infra.db.services import SharedServices
from octop.infra.desktop import bot_cloud_enabled
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.gateway.process.message_keys import CHECKPOINT_TS_KEY
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.history.projection import message_input
from octop.infra.utils.ulid import new_ulid

_SESSIONS = "/api/user/web-chat-sessions"


class RestoredThread(BaseModel):
    legacy_id: str
    agent_id: str
    thread_id: str


class RestorePage(BaseModel):
    scanned: int
    restored: int = 0
    existing: int = 0
    skipped: int = 0
    next_cursor: str | None
    threads: list[RestoredThread] = Field(default_factory=list)


def _account(services: SharedServices, owner: int) -> str:
    row = services.user_repo.get(owner)
    provider = services.sso_repo.get_by_kind(SSO_KIND)
    if not bot_cloud_enabled() or not row or row.disabled or not provider:
        raise OctopError.localized(ErrorCode.FORBIDDEN)
    if row.sso_provider_id != provider.id or not row.sso_subject:
        raise OctopError.localized(ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED)
    return row.sso_subject


def _timestamp(value: str) -> int:
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("source timestamp requires a timezone")
    return int(stamp.timestamp() * 1000)


def _messages(items: list[Any], source_id: str, updated: int) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict) or item.get("role") not in ("user", "assistant"):
            raise ValueError("unsupported source message")
        text = item.get("content")
        if not isinstance(text, str):
            raise ValueError("missing source content")
        stamp = _timestamp(item["createdAt"]) if "createdAt" in item else updated
        kwargs: dict[str, Any] = {CHECKPOINT_TS_KEY: stamp}
        if isinstance(item.get("thinking"), str):
            kwargs["reasoning_content"] = item["thinking"]
        # Keep source-only fields with the saved message, outside model instructions.
        metadata = {k: v for k, v in item.items() if k not in ("role", "content")}
        cls = HumanMessage if item["role"] == "user" else AIMessage
        messages.append(
            cls(
                content=text,
                id=f"{source_id}:{index}",
                additional_kwargs=kwargs,
                response_metadata={"lynxce_legacy": metadata},
            )
        )
    return messages


async def _publish(
    services: SharedServices,
    registry: AgentManager,
    owner: int,
    chief_id: str,
    key: str,
    pending_id: str | None,
    detail: dict[str, Any],
    updated: int,
    messages: list[BaseMessage],
) -> str:
    try:
        harness = registry.get_agent(chief_id)
    except OctopError as exc:
        if exc.code != ErrorCode.AGENT_NOT_RUNNING:
            raise
        await registry.start(chief_id)
        harness = registry.get_agent(chief_id)
    if pending_id:
        tid = pending_id
        # A crashed worker can leave an unpublished checkpoint. Only this
        # reserved ID may be reset. Published threads are never rewritten.
        if await asyncio.to_thread(services.thread_repo.get, tid) is not None:
            raise OctopError.localized(ErrorCode.AGENT_BUSY)
        await registry.delete_thread_checkpoint(chief_id, tid, reclaim=False)
    else:
        proposed = json.dumps({"thread_id": f"thr_{new_ulid()}"})
        reservation = await asyncio.to_thread(services.settings_repo.get_or_insert, key, proposed)
        if reservation != proposed:
            raise OctopError.localized(ErrorCode.AGENT_BUSY)
        tid = json.loads(reservation)["thread_id"]
    for start in range(0, len(messages), 32):
        await write_checkpoint_messages(
            harness, thread_id=tid, messages=messages[start : start + 32]
        )
    initial = [message_input(m) for m in messages]
    if any(m is None for m in initial):
        raise OctopError.localized(ErrorCode.NETWORK_ERROR)
    await lynxce_cloud._finish(
        asyncio.to_thread(
            services.thread_repo.insert,
            thread_id=tid,
            agent_id=chief_id,
            user_id=owner,
            channel_type=ThreadRegistry.CHANNEL_DASHBOARD,
            session_key=ThreadRegistry.dashboard_key(agent_id=chief_id, user_id=owner),
            title=detail["title"],
            last_active=updated // 1000 if messages else 0,
            created_at=int(messages[0].additional_kwargs[CHECKPOINT_TS_KEY]) // 1000
            if messages
            else updated // 1000,
            pinned=detail.get("pinned") is True,
            initial_messages=[m for m in initial if m is not None],
            restore_entry=(
                key,
                json.dumps({"thread_id": tid, "updated_at": detail["updatedAt"]}),
            ),
        )
    )
    return str(tid)


async def restore_page(
    services: SharedServices, registry: AgentManager, owner: int, cursor: str | None
) -> RestorePage:
    account = await asyncio.to_thread(_account, services, owner)

    cursor_owner = hashlib.sha256(f"{owner}:{account}".encode()).hexdigest()[:24] + "."
    if cursor and not cursor.startswith(cursor_owner):
        raise OctopError.localized(ErrorCode.BOT_CLOUD_REQUEST_REJECTED, status=409)

    async def read(path: str, params: dict[str, str | int] | None = None) -> Any:
        return await lynxce_cloud.request_cloud(
            services, owner, "GET", path, params=params, expected_account_id=account
        )

    async with AsyncFileLock(services.paths.root / f".legacy-conversations-{owner}.lock"):
        profile = await lynxce_cloud.tenant_call(services, owner, "GET", "/api/user/profile")
        if not isinstance(profile, dict) or profile.get("id") != account:
            raise OctopError.localized(ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED)
        params: dict[str, str | int] = {"limit": 5}
        if cursor:
            params["cursor"] = cursor.removeprefix(cursor_owner)
        page = await read(_SESSIONS, params)
        if not isinstance(page, dict) or not isinstance(page.get("items"), list):
            raise OctopError.localized(ErrorCode.NETWORK_ERROR)
        following = page.get("nextCursor")
        if following is not None and (
            not isinstance(following, str) or not following or cursor_owner + following == cursor
        ):
            raise OctopError.localized(ErrorCode.NETWORK_ERROR)
        result = RestorePage(
            scanned=len(page["items"]), next_cursor=cursor_owner + following if following else None
        )
        exports: dict[str, tuple[str, str]] | None = None
        chief_id: str | None = None
        for summary in page["items"]:
            if (
                not isinstance(summary, dict)
                or not isinstance(sid := summary.get("id"), str)
                or not is_regular_session(sid)
            ):
                continue
            binding = hashlib.sha256(json.dumps([account, sid]).encode()).hexdigest()
            key = f"octop:legacy-restore:{owner}:{binding}"
            known = await asyncio.to_thread(services.settings_repo.get, key)
            saved = json.loads(known) if known else {}
            if "updated_at" in saved:
                row = await asyncio.to_thread(services.thread_repo.get, saved["thread_id"])
                if (
                    not row
                    or row.user_id != owner
                    or saved["updated_at"] != summary.get("updatedAt")
                ):
                    # Respect a local deletion or a changed upstream snapshot. Never overwrite a continued thread.
                    result.skipped += 1
                    continue
                result.existing += 1
                result.threads.append(
                    RestoredThread(legacy_id=sid, agent_id=row.agent_id, thread_id=row.thread_id)
                )
                continue
            if UUID(sid.removeprefix("octop-bot-v1-")).version == 5:
                # An explicit prior cloud -> Lynxce export can refer to the very same owned thread.
                if exports is None:
                    rows = await asyncio.to_thread(services.thread_repo.list_for_user, owner)
                    exports = {hosted_session_id(owner, aid, tid): (aid, tid) for aid, tid in rows}
                if sid in exports:
                    aid, tid = exports[sid]
                    result.existing += 1
                    result.threads.append(
                        RestoredThread(legacy_id=sid, agent_id=aid, thread_id=tid)
                    )
                    continue
            try:
                detail = await read(f"{_SESSIONS}/{sid}")
            except OctopError as exc:
                if exc.status not in (403, 404):
                    raise
                result.skipped += 1
                continue
            if (
                not isinstance(detail, dict)
                or detail.get("id") != sid
                or detail.get("workspaceProjectId")
                or not isinstance(items := detail.get("items"), list)
                or summary.get("messageCount") != len(items)
                or not isinstance(detail.get("title"), str)
                or detail.get("updatedAt") != summary.get("updatedAt")
            ):
                result.skipped += 1
                continue
            try:
                updated = _timestamp(detail["updatedAt"])
                messages = _messages(items, sid, updated)
            except (ValueError, TypeError, OverflowError, KeyError):
                result.skipped += 1
                continue
            if chief_id is None:
                chief_id = await ensure_chief(services, registry, owner)
            async with AsyncFileLock(checkpoint_publication_lock(services.paths.root, chief_id)):
                tid = await lynxce_cloud._finish(
                    _publish(
                        services,
                        registry,
                        owner,
                        chief_id,
                        key,
                        saved.get("thread_id"),
                        detail,
                        updated,
                        messages,
                    )
                )
            result.restored += 1
            result.threads.append(RestoredThread(legacy_id=sid, agent_id=chief_id, thread_id=tid))
        return result
