"""Route one explicitly linked external conversation to its owner's Bot room."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING

from octop_gateway.channel import MessageProcessor
from octop_gateway.models import InboundMessage, MessageEvent
from pydantic import BaseModel

from octop.i18n import tr
from octop.infra.bot_groups.service import group_row
from octop.infra.bot_groups.turns import send_message
from octop.infra.db.repos.channels import ChannelRow
from octop.infra.db.services import SharedServices
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.gateway.process.message_keys import session_key_from_message
from octop.infra.users.permissions import user_has_permission

if TYPE_CHECKING:
    from octop.infra.server import AppRuntime


class ImSession(BaseModel):
    channel_id: str
    session_key: str
    channel_name: str
    platform: str
    subject: str
    chat_type: str
    linked: bool
    linked_elsewhere: bool


def binding_key(owner: int, channel_id: str, session_key: str) -> str:
    identity = json.dumps([channel_id, session_key]).encode()
    return f"bot-room-im:{owner}:{hashlib.sha256(identity).hexdigest()}"


def im_sessions(services: SharedServices, owner: int, group_id: str) -> list[ImSession]:
    group_row(services, owner, group_id)
    links = services.settings_repo.with_prefix(f"bot-room-im:{owner}:")
    sessions = []
    for row in services.repos.bot_group_repo.im_sessions(owner):
        linked = links.get(binding_key(owner, row["channel_id"], row["session_key"]))
        sessions.append(
            ImSession(
                channel_id=row["channel_id"],
                session_key=row["session_key"],
                channel_name=row["name"],
                platform=row["kind"],
                subject=row["channel_subject_id"],
                chat_type=row["channel_chat_type"] or "",
                linked=linked == group_id,
                linked_elsewhere=bool(linked and linked != group_id),
            )
        )
    return sessions


def set_binding(
    services: SharedServices,
    owner: int,
    group_id: str,
    channel_id: str,
    session_key: str,
    linked: bool,
) -> list[ImSession]:
    sessions = im_sessions(services, owner, group_id)
    if not any(s.channel_id == channel_id and s.session_key == session_key for s in sessions):
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    key = binding_key(owner, channel_id, session_key)
    if linked:
        if services.settings_repo.get_or_insert(key, group_id) != group_id:
            raise OctopError(ErrorCode.SLASH_BAD_ARGS, "IM conversation already linked", status=409)
    else:
        services.repos.bot_group_repo.unlink_im(key, group_id)
    return im_sessions(services, owner, group_id)


class GroupImRouter:
    def __init__(
        self,
        services: Callable[[], SharedServices | None],
        runtime: Callable[[], AppRuntime | None],
    ) -> None:
        self.services = services
        self.runtime = runtime

    def wrap(self, channel: ChannelRow, direct: MessageProcessor) -> MessageProcessor:
        async def process(msg: InboundMessage) -> AsyncIterator[MessageEvent]:
            services = self.services()
            if services is None:
                raise OctopError.localized(ErrorCode.INTERNAL_ERROR)
            if msg.channel_id != channel.channel_id or msg.tenant_id not in (
                None,
                channel.agent_id,
            ):
                return
            key = None
            if (
                msg.channel_type == channel.kind
                and msg.channel_subject
                and msg.channel_subject.subject_id
            ):
                # A transport cannot choose another contact's bound session via metadata.
                routing_msg = msg.model_copy(
                    update={
                        "metadata": {k: v for k, v in msg.metadata.items() if k != "session_key"}
                    }
                )
                key = binding_key(
                    channel.user_id,
                    channel.channel_id,
                    session_key_from_message(routing_msg, agent_id=channel.agent_id),
                )
            group_id = await asyncio.to_thread(services.settings_repo.get, key) if key else None
            if not group_id or key is None:
                async for event in direct(msg):
                    yield event
                return
            runtime = self.runtime()
            if runtime is None:
                raise OctopError.localized(ErrorCode.INTERNAL_ERROR)
            owner = runtime.user_manager.get_by_id(channel.user_id)
            if owner is None or not user_has_permission(owner, "channels"):
                raise OctopError.localized(ErrorCode.FORBIDDEN)
            if msg.metadata.get("is_bot") is True or msg.metadata.get("from_self") is True:
                yield MessageEvent.completed()
                return
            if msg.allowed_tools is not None:
                # Room members can include native CLI agents without per-turn tool ceilings.
                yield MessageEvent.text(tr("bot_rooms.im_restricted", owner.locale))
                yield MessageEvent.completed()
                return
            if msg.has_media or not msg.text.strip():
                yield MessageEvent.text(tr("bot_rooms.im_text_only", owner.locale))
                yield MessageEvent.completed()
                return
            platform_id = (
                msg.metadata.get("message_id")
                or msg.metadata.get("msg_id")
                or msg.metadata.get("event_id")
            )
            # Adapters without platform IDs still keep retries of one normalized event stable.
            event_identity = [key, platform_id] if platform_id else [key, msg.timestamp, msg.text]
            request_id = (
                "im-" + hashlib.sha256(json.dumps(event_identity, default=str).encode()).hexdigest()
            )
            replies = await send_message(
                services,
                runtime,
                owner,
                group_id,
                text=msg.text,
                mention_ids=[],
                request_id=request_id,
            )
            if not await asyncio.to_thread(
                services.repos.bot_group_repo.claim_im_reply,
                channel.user_id,
                key,
                group_id,
                request_id,
            ):
                yield MessageEvent.completed()
                return
            for reply in replies:
                if reply.role == "user" or not reply.text:
                    continue
                agent = (
                    await asyncio.to_thread(services.agent_repo.get, reply.agent_id)
                    if reply.agent_id
                    else None
                )
                speaker = agent.name if agent is not None else reply.agent_id
                yield MessageEvent.text(f"{speaker}\n{reply.text}" if speaker else reply.text)
            yield MessageEvent.completed()

        return process
