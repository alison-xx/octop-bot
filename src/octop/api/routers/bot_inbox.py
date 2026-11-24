"""Octop Bot inbox: every card waiting for the signed-in user, across their Bots."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from octop.api.deps import current_user, get_server
from octop.infra.bot_tasks.inbox import inbox
from octop.infra.users.identity import User

router = APIRouter()


class InboxEntry(BaseModel):
    pending_id: str = Field(description="Answer it with the chat HITL resume call.")
    agent_id: str
    thread_id: str = Field(description="The conversation the card is in.")
    kind: Literal["question", "approval", "takeover", "tool"] = Field(
        description="question (ask_user_question), approval (request_approval or a guarded "
        "click), takeover (request_takeover) or tool (a tool waiting for approval)."
    )
    text: str = Field(description="The question or what is asked, at most 300 characters.")
    created_at: float = Field(description="Unix seconds.")
    scheduled: bool = Field(description="Raised by a scheduled run, not a chat.")


class InboxResponse(BaseModel):
    items: list[InboxEntry]


@router.get(
    "/inbox",
    summary="Cards waiting for me",
    description="Questions, approvals and takeovers that the signed-in user's Bots are waiting "
    "on, newest first. Cards live in the server process: a restart clears the list.",
    response_model=InboxResponse,
)
async def read_inbox(
    user: User = Depends(current_user), server: Any = Depends(get_server)
) -> InboxResponse:
    store = server.app_runtime.gateway.processor.hitl_coordinator.store
    return InboxResponse(items=[InboxEntry(**item.__dict__) for item in inbox(store, user.id)])
