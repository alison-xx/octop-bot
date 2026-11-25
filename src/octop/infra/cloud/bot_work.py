"""Bind hosted work to the signed-in Lynxce account and its persisted Octop Bot namespace."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from pydantic.alias_generators import to_camel

from octop.infra.agents.bot_workspace import can_join_bot_group
from octop.infra.auth import lynxce_cloud
from octop.infra.cloud import bot_work_models as dto
from octop.infra.db.services import SharedServices
from octop.infra.errors import ErrorCode, OctopError

_WORK = "/api/user/cloud-work"
_SESSIONS = "/api/user/web-chat-sessions"
_SCHEDULES = "/api/user/scheduled-tasks"
_SESSION_PREFIX = "octop-bot-v1-"
_SCHEDULE_PREFIX = "[Octop Bot/v1] "
_ROLE = "\n\n[Octop Bot role/v1] "
_UUID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")


class _Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)


class _Capabilities(_Wire):
    enabled: bool
    supported_model_ids: list[str]
    default_model_id: str | None = None
    reason: str | None = None


class _Question(_Wire):
    title: str


class _Task(_Wire):
    id: dto.Id
    session_id: dto.Id
    executor: str = "cloud"
    model: str
    status: dto.Status
    instruction: str
    created_at: str
    updated_at: str
    result: str | None = None
    error: str | None = None
    question: str | None = None
    questions: list[_Question] = Field(default_factory=list)
    takeover_available: bool = False
    waiting_for: str | None = None

    @field_validator("waiting_for", mode="before")
    @classmethod
    def platform_wait(cls, value: object) -> str | None:
        if value is None or isinstance(value, str) and value in {"media", "presentation"}:
            return value
        # Unknown platform wait shapes are never an invitation to answer or authorize.
        return "platform"

    def view(self) -> dto.Task:
        question = self.question or "\n".join(q.title for q in self.questions) or None
        return dto.Task(
            **self.model_dump(exclude={"question"}),
            question=question,
            can_answer=bool(
                self.executor == "cloud"
                and self.status == "waiting_user"
                and question
                and not self.waiting_for
                and not self.takeover_available
            ),
        )


class _Tasks(_Wire):
    items: list[_Task]


class _Item(_Wire):
    role: Literal["user", "assistant"]
    content: str
    created_at: str | None = None
    cloud_work_task_id: str | None = None


class _Session(_Wire):
    id: str
    title: str
    model: str
    updated_at: str
    items: list[_Item]


class _Summary(_Wire):
    id: str
    title: str
    model: str
    updated_at: str
    message_count: int


class _Sessions(_Wire):
    items: list[_Summary]
    next_cursor: str | None


class _ScheduleRule(_Wire):
    frequency: str


class _Schedule(_Wire):
    id: dto.Id
    name: str
    instruction: str
    rule: _ScheduleRule
    rule_text: str
    enabled: bool
    next_run_at: str | None
    last_run_at: str | None
    last_status: str
    last_result_preview: str
    last_error: str
    session_id: dto.Id
    run_count: int
    source: str

    def belongs(self) -> bool:
        return (
            self.source == "manual"
            and self.name.startswith(_SCHEDULE_PREFIX)
            and _UUID.fullmatch(self.id) is not None
            and self.session_id == f"sched-{self.id}"
        )

    def view(self) -> dto.Schedule:
        instruction, role = _split_role(self.instruction)
        return dto.Schedule(
            **self.model_dump(exclude={"instruction", "name", "rule"}),
            finished_once=self.rule.frequency == "once" and not self.enabled and self.run_count > 0,
            name=self.name.removeprefix(_SCHEDULE_PREFIX),
            instruction=instruction,
            bot_name=role.name if role else None,
        )


class _Schedules(_Wire):
    items: list[_Schedule]


class _Role(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(max_length=800)


def _split_role(text: str) -> tuple[str, _Role | None]:
    prompt, separator, metadata = text.rpartition(_ROLE)
    if separator:
        try:
            return prompt, _Role.model_validate_json(metadata)
        except ValidationError:
            pass
    return text, None


def _utf16_length(value: str) -> int:
    # The hosted Zod schemas count JavaScript UTF-16 code units.
    return len(value.encode("utf-16-le")) // 2


def _instruction(message: str, role: _Role | None, limit: int) -> str:
    if role:
        message += _ROLE + json.dumps(role.model_dump(), ensure_ascii=False, separators=(",", ":"))
    if _utf16_length(message) > limit:
        raise OctopError.localized(ErrorCode.BOT_CLOUD_REQUEST_REJECTED, status=422)
    return message


def _local_role(services: SharedServices, owner: int, bot_id: str) -> _Role:
    bot = services.agent_repo.get(bot_id)
    if bot is None or bot.user_id != owner or bot.kind != "expert" or not can_join_bot_group(bot):
        raise OctopError.localized(ErrorCode.AGENT_NOT_FOUND)
    return _Role(name=bot.name[:120], description=(bot.description or "")[:800])


async def role_instruction(
    services: SharedServices, owner: int, bot_id: str | None, message: str, limit: int
) -> str:
    """Attach only an explicitly selected Bot's public role to confirmed hosted text."""
    role = await asyncio.to_thread(_local_role, services, owner, bot_id) if bot_id else None
    return _instruction(message, role, limit)


def _title(title: str) -> str:
    # The hosted service initializes titles with the first 80 chars of the instruction.
    return title.removeprefix(_SCHEDULE_PREFIX).split("\n", 1)[0]


def is_regular_session(value: str) -> bool:
    return value.startswith(_SESSION_PREFIX) and bool(
        _UUID.fullmatch(value[len(_SESSION_PREFIX) :])
    )


def _missing() -> OctopError:
    return OctopError.localized(ErrorCode.NOT_FOUND)


def _protocol_error() -> OctopError:
    return OctopError.localized(ErrorCode.NETWORK_ERROR)


Wire = TypeVar("Wire", bound=_Wire)


class CloudWorkspace:
    """One request's account snapshot, pinned across upstream reads and writes."""

    def __init__(
        self, services: SharedServices, owner: int, account_id: str, *, pinned_read: bool = False
    ):
        self.services = services
        self.owner = owner
        self.account_id = account_id
        self.pinned_read = pinned_read

    @classmethod
    async def current(
        cls, services: SharedServices, owner: int, expected: str | None = None
    ) -> CloudWorkspace:
        status = await asyncio.to_thread(lynxce_cloud.cloud_status, services, owner)
        if expected is not None and status.account_id != expected:
            raise OctopError.localized(ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED, status=409)
        if not status.connected or not status.account_id:
            raise OctopError.localized(ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED)
        return cls(services, owner, status.account_id, pinned_read=expected is not None)

    async def _call(
        self,
        model: type[Wire],
        method: Literal["GET", "POST"],
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> Wire:
        try:
            data = await lynxce_cloud.request_cloud(
                self.services,
                self.owner,
                method,
                path,
                json=payload,
                params=params,
                expected_account_id=self.account_id,
            )
        except OctopError as exc:
            if self.pinned_read and exc.code == ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED:
                raise OctopError.localized(
                    ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED, status=409
                ) from exc
            raise
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            raise _protocol_error() from exc

    async def capabilities(self) -> dto.Capabilities:
        row = await self._call(_Capabilities, "GET", _WORK + "/capabilities")
        models = row.supported_model_ids
        default = (
            row.default_model_id if row.default_model_id in models else next(iter(models), None)
        )
        return dto.Capabilities(
            enabled=row.enabled, reason=row.reason, models=models, default_model=default
        )

    async def _schedule(self, task_id: str) -> _Schedule:
        if not _UUID.fullmatch(task_id):
            raise _missing()
        row = await self._call(_Schedule, "GET", f"{_SCHEDULES}/{task_id}", params={"runs": "1"})
        if row.id != task_id or not row.belongs():
            raise _missing()
        return row

    async def _verify_session(self, session_id: str) -> _Schedule | None:
        if is_regular_session(session_id):
            return None
        if session_id.startswith("sched-"):
            return await self._schedule(session_id.removeprefix("sched-"))
        raise _missing()

    async def list_sessions(self, cursor: str | None) -> dto.Sessions:
        params = {"limit": "50"}
        if cursor:
            params["cursor"] = cursor
        rows = await self._call(_Sessions, "GET", _SESSIONS, params=params)
        scheduled_ids: set[str] = set()
        if any(item.id.startswith("sched-") for item in rows.items):
            scheduled_ids = {s.session_id for s in (await self.list_schedules()).items}
        return dto.Sessions(
            items=[
                dto.SessionSummary(**item.model_dump(exclude={"title"}), title=_title(item.title))
                for item in rows.items
                if is_regular_session(item.id) or item.id in scheduled_ids
            ],
            next_cursor=rows.next_cursor,
        )

    async def _read(self, session_id: str) -> _Session:
        row = await self._call(_Session, "GET", f"{_SESSIONS}/{session_id}")
        if row.id != session_id:
            raise _protocol_error()
        return row

    async def _tasks(self, session_id: str) -> list[_Task]:
        data = await self._call(_Tasks, "GET", _WORK + "/tasks", params={"sessionId": session_id})
        return [
            task
            for task in data.items
            if task.session_id == session_id and task.executor == "cloud"
        ]

    async def _task(self, session_id: str, task_id: str) -> _Task:
        for task in await self._tasks(session_id):
            if task.id == task_id:
                return task
        raise _missing()

    async def _action(self, task: _Task, payload: dict[str, str]) -> dto.Task:
        row = await self._call(_Task, "POST", f"{_WORK}/tasks/{task.id}/actions", payload=payload)
        if row.id != task.id or row.session_id != task.session_id or row.executor != "cloud":
            raise _protocol_error()
        return row.view()

    async def cancel_task(self, task_id: str, body: dto.CancelTask) -> dto.Task:
        await self._verify_session(body.session_id)
        task = await self._task(body.session_id, task_id)
        if task.status in {"completed", "failed", "cancelled"}:
            return task.view()
        return await self._action(task, {"requestId": str(body.request_id), "action": "cancel"})

    async def session(self, session_id: str) -> dto.Session:
        await self._verify_session(session_id)
        session, tasks = await asyncio.gather(self._read(session_id), self._tasks(session_id))
        return dto.Session(
            id=session.id,
            title=_title(session.title),
            model=session.model,
            updated_at=session.updated_at,
            items=[
                dto.Message(
                    role=m.role,
                    content=_split_role(m.content)[0] if m.role == "user" else m.content,
                    created_at=m.created_at,
                    task_id=m.cloud_work_task_id,
                )
                for m in session.items
            ],
            tasks=[t.view() for t in tasks],
        )

    async def submit(self, turn: dto.Turn) -> dto.Task:
        session_id = turn.session_id or f"{_SESSION_PREFIX}{turn.request_id}"
        role: _Role | None = None
        previous_model: str | None = None
        if turn.session_id:
            schedule = await self._verify_session(session_id)
            session = await self._read(session_id)
            previous_model = session.model
            if turn.input_task_id:
                task = await self._task(session_id, turn.input_task_id)
                if not task.view().can_answer:
                    raise OctopError.localized(ErrorCode.BOT_CLOUD_REQUEST_REJECTED, status=409)
                return await self._action(
                    task,
                    {
                        "requestId": str(turn.request_id),
                        "action": "input",
                        "text": turn.message,
                    },
                )
            for item in reversed(session.items):
                if item.role == "user" and (role := _split_role(item.content)[1]):
                    break
            if role is None and schedule:
                role = _split_role(schedule.instruction)[1]
        if turn.bot_id:
            role = await asyncio.to_thread(_local_role, self.services, self.owner, turn.bot_id)
        capabilities = await self.capabilities()
        model = turn.model or (
            previous_model if previous_model in capabilities.models else capabilities.default_model
        )
        if not capabilities.enabled or not model or model not in capabilities.models:
            raise OctopError.localized(ErrorCode.BOT_CLOUD_REQUEST_REJECTED, status=409)
        row = await self._call(
            _Task,
            "POST",
            _WORK + "/tasks",
            payload={
                "requestId": str(turn.request_id),
                "sessionId": session_id,
                "model": model,
                "message": _instruction(turn.message, role, 32000),
                "executor": "cloud",
                "mode": "cloud",
                "attachments": [],
            },
        )
        if row.session_id != session_id or row.executor != "cloud":
            raise _protocol_error()
        return row.view()

    async def list_schedules(self) -> dto.Schedules:
        rows = await self._call(_Schedules, "GET", _SCHEDULES)
        return dto.Schedules(items=[row.view() for row in rows.items if row.belongs()])

    async def create_schedule(self, body: dto.CreateSchedule) -> dto.Schedule:
        name = _SCHEDULE_PREFIX + body.name
        if _utf16_length(name) > 60:
            raise OctopError.localized(ErrorCode.BOT_CLOUD_REQUEST_REJECTED, status=422)
        row = await self._call(
            _Schedule,
            "POST",
            _SCHEDULES,
            payload={
                "name": name,
                "instruction": await role_instruction(
                    self.services, self.owner, body.bot_id, body.instruction, 4000
                ),
                "source": "manual",
                "webSearch": False,
                "rule": body.rule.model_dump(mode="json", by_alias=True, exclude_none=True),
            },
        )
        if not row.belongs():
            raise _protocol_error()
        return row.view()

    async def enable_schedule(self, task_id: str, enabled: bool) -> dto.Schedule:
        await self._schedule(task_id)
        row = await self._call(
            _Schedule, "POST", f"{_SCHEDULES}/{task_id}/enabled", payload={"enabled": enabled}
        )
        if row.id != task_id or not row.belongs():
            raise _protocol_error()
        return row.view()
