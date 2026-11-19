"""Read-only side conversations use a bounded snapshot and an unbound model."""

from __future__ import annotations

import asyncio
import json
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING, Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.config import get_config

from octop.i18n import tr
from octop.infra.agents.bot_workspace import is_private_bot
from octop.infra.agents.providers.lynxce import account_selection
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.gateway.process.usage_record import normalize_usage
from octop.infra.users.resource_policy import assert_token_quota_available
from octop.infra.utils.llm_text import llm_text_content

if TYPE_CHECKING:
    from octop.infra.agents.manager import AgentManager
    from octop.infra.db.services import SharedServices
    from octop.infra.users.identity import User


def visible_text(wire: str, role: str) -> str:
    record = json.loads(wire)
    content = record.get("data", record).get("content", "")
    return visible_content_text(content, role)


def visible_content_text(content: Any, role: str) -> str:
    """Read only user-facing text blocks from a projected message."""
    if isinstance(content, str):
        return content if role in {"human", "user"} else llm_text_content(content)
    if isinstance(content, list):
        return "".join(
            block if isinstance(block, str) else str(block.get("text") or "")
            for block in content
            if isinstance(block, str) or (isinstance(block, dict) and block.get("type") == "text")
        )
    return ""


class HistoryHit(TypedDict):
    agent_id: str
    thread_id: str
    title: str
    excerpt: str
    message_seq: int
    message_id: str | None
    part: int


def search_history(
    services: SharedServices, user_id: int, query: str, *, own_thread: str | None = None
) -> list[HistoryHit]:
    eligible = (
        None
        if own_thread
        else {
            row.agent_id
            for row in services.agent_repo.list_by_user(user_id)
            if row.kind != "team" and not is_private_bot(row)
        }
    )
    results: list[HistoryHit] = []
    title_matches: set[str] = set()
    needle = query.casefold()
    for agent_id, tid, title, row, part in services.thread_message_repo.search_owned(
        user_id, query, thread_id=own_thread
    ):
        if eligible is not None and agent_id not in eligible:
            continue
        text = visible_text(row.message_json, row.role)
        match = text.casefold().find(needle) if needle or own_thread else -1
        if not text or (match < 0 and (needle not in title.casefold() or tid in title_matches)):
            continue
        title_matches.add(tid)
        start = max(0, match - 60)
        results.append(
            {
                "agent_id": agent_id,
                "thread_id": tid,
                "title": title,
                "excerpt": text[start : start + 200],
                "message_seq": row.seq,
                "message_id": row.message_id,
                "part": part,
            }
        )
        if len(results) >= 40:
            break
    return results


def reference(
    services: SharedServices,
    user_id: int,
    agent_id: str,
    thread_id: str,
    message_seq: int | None = None,
    message_id: str | None = None,
) -> str:
    row = services.agent_repo.get(agent_id)
    if row is None or row.user_id != user_id or row.kind == "team" or is_private_bot(row):
        raise OctopError(ErrorCode.FORBIDDEN, "conversation cannot be referenced")
    thread = services.thread_repo.get(thread_id)
    if (
        thread is None
        or thread.channel_type != "dashboard"
        or thread.agent_id != agent_id
        or thread.user_id != user_id
    ):
        raise OctopError(ErrorCode.NOT_FOUND, "unknown private conversation")
    if message_seq is not None or message_id:
        return anchored_text(services, thread_id, message_seq, message_id)
    _, entries = snapshot(services, user_id, agent_id, thread_id, None)
    return "\n".join(f"{entry['role']}: {entry['text']}" for entry in entries)


def anchored_text(
    services: SharedServices, thread_id: str, message_seq: int | None, message_id: str | None
) -> str:
    row = services.thread_message_repo.anchored_message(thread_id, message_seq, message_id)
    if row is None or row.role not in {"user", "human", "assistant", "ai"}:
        raise OctopError(ErrorCode.NOT_FOUND, "unknown message")
    return visible_text(row.message_json, row.role)


def own_chat_tool(services: SharedServices, agent_id: str, owner: int) -> StructuredTool:
    def read_own_chat(
        query: str = "", message_seq: int | None = None, offset: int = 0
    ) -> dict[str, Any]:
        """Search this private conversation's original messages across compacted parts.

        Search by words to get excerpts and message_seq anchors. Pass an anchor to read the
        original message, with offset to continue a long quote. Empty query lists recent messages.
        """
        ctx = get_config().get("configurable") or {}
        tid = str(ctx.get("thread_id") or "")
        thread = services.thread_repo.get(tid)
        if (
            ctx.get("octop_bot_browser") is not True
            or str(ctx.get("user")) != str(owner)
            or ctx.get("agent_id") != agent_id
            or thread is None
            or thread.channel_type != "dashboard"
            or thread.user_id != owner
            or thread.agent_id != agent_id
        ):
            raise OctopError(ErrorCode.FORBIDDEN, "requires the current personal conversation")
        if message_seq is not None:
            text = anchored_text(services, tid, message_seq, None)
            start = max(0, offset)
            return {"text": text[start : start + 12000], "has_more": len(text) > start + 12000}
        return {"messages": search_history(services, owner, query[:160], own_thread=tid)}

    return StructuredTool.from_function(read_own_chat)


def snapshot(
    services: SharedServices, user_id: int, agent_id: str, thread_id: str, through: int | None
) -> tuple[int, list[dict[str, str]]]:
    thread = services.thread_repo.get(thread_id)
    if thread is None or thread.agent_id != agent_id or thread.user_id != user_id:
        raise OctopError(ErrorCode.NOT_FOUND, "conversation not found")
    repo = services.thread_message_repo
    if repo.projection_status(thread_id) != "ready":
        raise OctopError(ErrorCode.AGENT_BUSY, "conversation history is loading")
    head = repo.head(thread_id)
    end = min(head, through) if through is not None else head
    entries: list[dict[str, str]] = []
    available = 24000
    for row in reversed(repo.range_rows(thread_id, max(0, end - 80), end)):
        if row.role not in {"human", "ai", "user", "assistant"}:
            continue
        text = visible_text(row.message_json, row.role)
        if text:
            excerpt = text[-available:]
            entries.append({"role": row.role, "text": excerpt})
            available -= len(excerpt)
            if available <= 0:
                break
    entries.reverse()
    return end, entries


async def answer_side(
    services: SharedServices,
    registry: AgentManager,
    user: User,
    agent_id: str,
    thread_id: str,
    question: str,
    through: int | None,
    turns: list[dict[str, str]],
) -> dict[str, Any]:
    row = await asyncio.to_thread(services.agent_repo.get, agent_id)
    if row is None or row.user_id != user.id or row.kind == "team":
        raise OctopError(ErrorCode.AGENT_NOT_FOUND, "bot not found")
    seq, history = await asyncio.to_thread(
        snapshot, services, user.id, agent_id, thread_id, through
    )
    await asyncio.to_thread(
        assert_token_quota_available, services.user_policy_repo, services.usage_repo, user.id
    )
    prompt = json.dumps(
        {"conversation": history, "side_chat": turns, "question": question}, ensure_ascii=False
    )
    personal = await asyncio.to_thread(account_selection, services, user.id)
    model: str | None
    async with AsyncExitStack() as stack:
        if personal:
            from octop_harness.llm.factory import ChatModelFactory

            factory = ChatModelFactory([personal.provider(services)])
            stack.push_async_callback(factory.aclose)
            model = personal.ref
            chat = factory.get_chat_model(model)
        else:
            model = registry.get_thread_model(agent_id, thread_id) or row.default_model
            if not model or model == "auto":
                candidates = registry.providers.list_auto_route_candidates(needs_multimodal=False)
                model = next(
                    (
                        c.ref
                        for c in candidates
                        if registry.model_ref_allowed_for_user(user.id, c.ref)
                    ),
                    None,
                )
            if not model:
                raise OctopError(ErrorCode.AGENT_NOT_RUNNING, "no configured model")
            if not registry.model_ref_allowed_for_user(user.id, model):
                raise OctopError(ErrorCode.FORBIDDEN, "model not available")
            access = registry.host_models.get(model)
            chat = access.chat_model
            model = access.model_ref
        reply = await asyncio.wait_for(
            chat.ainvoke(
                [
                    SystemMessage(content=tr("octop_bot.side_prompt", user.locale)),
                    HumanMessage(content=prompt),
                ]
            ),
            timeout=90,
        )
    usage = normalize_usage(getattr(reply, "usage_metadata", None) or {})
    usage.pop("model", None)
    usage.pop("total_tokens", None)
    await asyncio.to_thread(
        services.usage_repo.record,
        agent_id=agent_id,
        user_id=user.id,
        thread_id=thread_id,
        model=model,
        source="side_chat",
        **usage,
    )
    return {"answer": llm_text_content(reply), "snapshot_seq": seq}
