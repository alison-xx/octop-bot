"""Owner-scoped Octop Bot rooms and durable, evidence-based Goals."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, Field, StringConstraints, model_validator

from octop.infra.agents.bot_workspace import can_join_bot_group
from octop.infra.db.repos.agents import AgentRow
from octop.infra.db.repos.bot_groups import ImportedTimeline
from octop.infra.db.services import SharedServices
from octop.infra.errors import ErrorCode, OctopError

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ReplyMode = Literal["admin_first", "all_members"]
GoalStatus = Literal["draft", "active", "done"]
MAX_GROUP_MEMBERS = 64


class Group(BaseModel):
    group_id: str
    name: str
    admin_id: str
    member_ids: list[str]
    reply_mode: ReplyMode

    @classmethod
    def from_record(cls, row: dict[str, Any]) -> Self:
        return cls.model_validate({**row, "member_ids": json.loads(row["member_ids"])})


class Message(BaseModel):
    message_id: str
    role: Literal["user", "assistant", "error"]
    agent_id: str | None
    text: str
    created_at: int
    request_id: str
    thread_id: str | None = None
    attachment_paths: list[str] = Field(default_factory=list)
    is_wrap_up: bool = Field(
        default=False, description="Administrator's synthesis or stage review."
    )
    stage_number: int | None = Field(
        default=None, description="One-based Goal stage, when assigned."
    )

    @classmethod
    def from_record(cls, row: dict[str, Any]) -> Self:
        # The scheduler persists the slot before delivering a reply, including on retries.
        slot = str(row["slot"])
        stage = None
        if slot.startswith("stage-"):
            prefix, _, slot = slot.partition(":")
            index = prefix.removeprefix("stage-")
            if index.isdecimal():
                stage = int(index) + 1
        return cls.model_validate(
            {**row, "is_wrap_up": slot.startswith("wrap:"), "stage_number": stage}
        )


class GoalStage(BaseModel):
    title: Name
    assignee_id: str | None = None
    status: Literal["pending", "active", "done"] = "pending"
    evidence: str = Field(default="", max_length=8000)


class Goal(BaseModel):
    title: Name
    criteria: str = Field(default="", max_length=8000)
    stages: list[GoalStage] = Field(default_factory=list, max_length=50)
    status: GoalStatus = "draft"

    @model_validator(mode="after")
    def check_progress(self) -> Self:
        if self.status != "draft" and (not self.criteria.strip() or not self.stages):
            raise ValueError("An active Goal needs acceptance criteria and stages.")
        if any(stage.status == "done" and not stage.evidence.strip() for stage in self.stages):
            raise ValueError("Completed stages need evidence.")
        if self.status == "done" and any(stage.status != "done" for stage in self.stages):
            raise ValueError("Every stage must be accepted before completing the Goal.")
        return self


def list_groups(services: SharedServices, user_id: int) -> list[Group]:
    return [Group.from_record(row) for row in services.repos.bot_group_repo.list_by_owner(user_id)]


def group_row(services: SharedServices, user_id: int, group_id: str) -> dict[str, Any]:
    row = services.repos.bot_group_repo.get(group_id, user_id)
    if not row:
        raise OctopError.localized(ErrorCode.TEAM_NOT_FOUND)
    return row


def eligible_members(services: SharedServices, user_id: int, ids: list[str]) -> dict[str, AgentRow]:
    rows = {}
    for agent_id in ids:
        row = services.agent_repo.get(agent_id)
        if row is None or row.user_id != user_id or not can_join_bot_group(row):
            raise OctopError.localized(ErrorCode.TEAM_MEMBER_INVALID)
        rows[agent_id] = row
    return rows


def _roster(
    services: SharedServices, user_id: int, admin_id: str, member_ids: list[str]
) -> list[str]:
    members = list(dict.fromkeys([admin_id, *member_ids]))
    if len(members) > MAX_GROUP_MEMBERS:
        raise OctopError.localized(ErrorCode.TEAM_MEMBER_INVALID)
    eligible_members(services, user_id, members)
    return members


def create_group(
    services: SharedServices,
    user_id: int,
    *,
    name: str,
    admin_id: str,
    member_ids: list[str],
    reply_mode: ReplyMode = "admin_first",
    imported: ImportedTimeline | None = None,
) -> Group:
    from octop.infra.agents.bot_limits import assert_group_capacity

    assert_group_capacity(services.repos.user_repo, services.repos.bot_group_repo, user_id)
    members = _roster(services, user_id, admin_id, member_ids)
    group_id = services.repos.bot_group_repo.create(
        user_id, name, admin_id, members, reply_mode, imported=imported
    )
    return Group.from_record(group_row(services, user_id, group_id))


def update_group(
    services: SharedServices, user_id: int, group_id: str, changes: dict[str, Any]
) -> Group:
    row = group_row(services, user_id, group_id)
    group = Group.model_validate({**Group.from_record(row).model_dump(), **changes})
    group.member_ids = _roster(services, user_id, group.admin_id, group.member_ids)
    services.repos.bot_group_repo.update(
        group_id, user_id, group.name, group.admin_id, group.member_ids, group.reply_mode
    )
    return group


def get_goal(services: SharedServices, user_id: int, group_id: str) -> Goal | None:
    raw = group_row(services, user_id, group_id)["goal"]
    return Goal.model_validate_json(raw) if raw else None


def set_goal(services: SharedServices, user_id: int, group_id: str, goal: Goal) -> Goal:
    row = group_row(services, user_id, group_id)
    members = Group.from_record(row).member_ids
    if any(s.assignee_id is not None and s.assignee_id not in members for s in goal.stages):
        raise OctopError.localized(ErrorCode.TEAM_MEMBER_INVALID)
    if not services.repos.bot_group_repo.set_goal(
        group_id, user_id, goal.model_dump_json(), row["goal"]
    ):
        raise OctopError.localized(ErrorCode.THREAD_TURN_ACTIVE)
    return goal


class GroupActivity(BaseModel):
    group_id: str
    unread_count: int = Field(description="Member replies after the owner last read the room.")
    last_message: Message | None = Field(
        default=None, description="Latest visible room message, for previews and notifications."
    )


def group_activity(services: SharedServices, user_id: int) -> list[GroupActivity]:
    return [
        GroupActivity(
            group_id=row["group_id"],
            unread_count=row["unread_count"],
            last_message=Message.from_record(row["last_message"]) if row["last_message"] else None,
        )
        for row in services.repos.bot_group_repo.activity(user_id)
    ]


def mark_group_read(services: SharedServices, user_id: int, group_id: str) -> None:
    group_row(services, user_id, group_id)
    services.repos.bot_group_repo.mark_read(group_id, user_id)


def list_messages(
    services: SharedServices,
    user_id: int,
    group_id: str,
    *,
    after_id: str | None = None,
    request_id: str | None = None,
) -> list[Message]:
    group_row(services, user_id, group_id)
    return [
        Message.from_record(row)
        for row in services.repos.bot_group_repo.messages(
            group_id, after_id=after_id, request_id=request_id
        )
    ]
