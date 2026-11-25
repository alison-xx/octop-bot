"""New-user onboarding state for the Octop Bot clients."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from octop.api.deps import current_user, get_server
from octop.infra.agents.bot_onboarding import (
    Action,
    Kind,
    Onboarding,
    OnboardingChoice,
    OnboardingTeam,
    Options,
    Reason,
    Status,
    Step,
    apply_action,
    onboarding_options,
    open_onboarding,
)
from octop.infra.agents.bot_workspace import ensure_chief
from octop.infra.users.identity import User
from octop.infra.utils.locale import resolve_user_locale

router = APIRouter(prefix="/onboarding")


class OnboardingState(BaseModel):
    show: bool = Field(description="Whether the client should guide the owner now.")
    status: Status = Field(
        description="pending: new, not started; active: in progress; done or skipped: never shown again on its own."
    )
    step: Step = Field(
        description="welcome → ask (tell Chief one sentence) → team_ready (Chief built it) → first_message (post in the group)."
    )
    choice: OnboardingChoice | None = Field(
        default=None, description="The industry or job picked on the first screen, if any."
    )
    team: OnboardingTeam | None = Field(
        default=None, description="The team Chief built during onboarding, once it exists."
    )
    reason: Reason | None = Field(
        default=None,
        description="existing: the account already had bots or groups; legacy: the old guide was seen.",
    )

    @classmethod
    def of(cls, state: Onboarding) -> OnboardingState:
        return cls(show=state.show, **state.model_dump(exclude={"updated_at"}))


class OnboardingChange(BaseModel):
    action: Action = Field(
        description="start, step (to ask or first_message), skip, complete, or restart from the menu."
    )
    step: Step | None = None
    reason: Reason | None = None
    kind: Kind = Field(
        default="industry", description="start: which tab the pick came from, industry or role."
    )
    option: str | None = Field(
        default=None, max_length=48, description="start: an id from GET /onboarding/options."
    )
    custom: str | None = Field(
        default=None,
        max_length=60,
        description="start: the owner's own industry or job when none of the list fits.",
    )
    note: str | None = Field(
        default=None, max_length=300, description="start: an optional line about what they need."
    )


@router.get(
    "",
    summary="Read my onboarding",
    response_model=OnboardingState,
    description="The first read decides whether this owner is new: an account with any bot besides Chief, or any group, is marked done.",
)
async def read_onboarding(
    user: User = Depends(current_user), server: Any = Depends(get_server)
) -> OnboardingState:
    services = server.services
    chief_id = await ensure_chief(services, server.app_runtime.agent_registry, user.id)
    state = await asyncio.to_thread(open_onboarding, services, user.id, chief_id)
    return OnboardingState.of(state)


@router.put(
    "",
    summary="Move my onboarding along",
    response_model=OnboardingState,
    description="An action that does not fit the current state returns the state unchanged; follow what comes back.",
)
async def change_onboarding(
    body: OnboardingChange, user: User = Depends(current_user), server: Any = Depends(get_server)
) -> OnboardingState:
    services = server.services
    chief_id = await ensure_chief(services, server.app_runtime.agent_registry, user.id)
    state = await asyncio.to_thread(
        apply_action,
        services,
        user.id,
        chief_id,
        body.action,
        step=body.step,
        reason=body.reason,
        kind=body.kind,
        option=body.option,
        custom=body.custom,
        note=body.note,
    )
    return OnboardingState.of(state)


@router.get(
    "/options",
    summary="List the industries and jobs to pick from",
    response_model=Options,
    description="Two lists for the first screen's tabs, in my language. Industries come from the Bot market's categories plus two of the onboarding's own; jobs are the roles marked for onboarding. Clients add their own \"something else\" entry.",
)
def list_options(user: User = Depends(current_user), server: Any = Depends(get_server)) -> Options:
    locale = resolve_user_locale(user_repo=server.services.user_repo, user_id=user.id)
    return onboarding_options(locale)
