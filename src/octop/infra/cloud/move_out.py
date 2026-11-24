"""Desktop app: move this computer's Bots, chats and groups into the Octop Bot cloud.

Signing in with Lynxce on the desktop means using the cloud, where phones and the web see
the same team. The move hands the Lynxce sign-in to the cloud, then sends every Bot, its
chats (with the context the Bot remembers), the groups with their timelines and the team
notes. The cloud remembers each item's source, so a move can simply run again after a
failure. Nothing is deleted here: switching back to "this computer" shows it all.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import httpx
from langchain_core.messages import messages_from_dict, messages_to_dict
from pydantic import BaseModel, Field

from octop.infra.agents.bot_appearance import bot_appearance
from octop.infra.agents.bot_workspace import chief_key, is_private_bot
from octop.infra.agents.threads.fork import load_checkpoint_messages
from octop.infra.auth import lynxce_cloud
from octop.infra.bridge.ids import is_bridge_agent_id
from octop.infra.cloud.move_in import goal_json
from octop.infra.db.services import SharedServices
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.utils.ulid import new_ulid

if TYPE_CHECKING:
    from octop.infra.agents.manager import AgentManager

logger = logging.getLogger(__name__)

_INSTALL_KEY = "octop_bot:install_id"
# One message bigger than this (a pasted file, a long tool result) is cut, so a chat fits a request.
_MAX_TEXT = 100_000
_MAX_THREADS_PER_BOT = 200


class MoveStatus(BaseModel):
    state: Literal["idle", "running", "done", "failed"] = "idle"
    done: int = Field(default=0, description="Items sent so far.")
    total: int = Field(default=0, description="Bots, chats, groups and the team notes.")
    error_code: str | None = Field(default=None, description="ErrorCode of a failed move.")
    access_token: str | None = Field(
        default=None,
        description="Sign-in for the cloud once the move is done; the desktop opens the "
        "cloud with it.",
    )


@dataclass
class _Run:
    status: MoveStatus = field(default_factory=MoveStatus)
    token: str | None = None
    task: asyncio.Task[None] | None = None


_runs: dict[int, _Run] = {}


def move_status(user_id: int) -> MoveStatus:
    run = _runs.get(user_id)
    return run.status.model_copy() if run else MoveStatus()


def start_move(
    services: SharedServices,
    registry: AgentManager,
    user_id: int,
    origin: str,
    locale: str,
    *,
    client: Callable[[str], httpx.AsyncClient] | None = None,
) -> MoveStatus:
    """Start (or keep running) the move for this user and report where it is."""
    run = _runs.setdefault(user_id, _Run())
    if run.task is not None and not run.task.done():
        return run.status.model_copy()
    run.status = MoveStatus(state="running")
    make = client or (lambda base: httpx.AsyncClient(base_url=base, timeout=120))
    run.task = asyncio.create_task(_move(services, registry, user_id, origin, locale, run, make))
    return run.status.model_copy()


async def _move(
    services: SharedServices,
    registry: AgentManager,
    user_id: int,
    origin: str,
    locale: str,
    run: _Run,
    make: Callable[[str], httpx.AsyncClient],
) -> None:
    try:
        async with make(origin) as http:
            cloud = _Cloud(http, run)
            if run.token is None:
                # A retry keeps the cloud sign-in: the Lynxce session is already there.
                async def accept(refresh_token: str) -> str:
                    data = await cloud.post(
                        "/api/auth/lynxce/session-login",
                        {"refresh_token": refresh_token, "locale": locale},
                        auth=False,
                    )
                    return str(data["access_token"])

                run.token = await lynxce_cloud.hand_over_session(services, user_id, accept)
            await _send_all(services, registry, user_id, cloud, run.status)
        run.status.state = "done"
        run.status.access_token = run.token
    except OctopError as exc:
        logger.warning("moving to the cloud failed: %s", exc.code)
        if exc.code == ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED:
            # The cloud sign-in expired: after signing in here again, hand over a fresh one.
            run.token = None
        run.status.state = "failed"
        run.status.error_code = exc.code.value
    except Exception:
        logger.exception("moving to the cloud failed")
        run.status.state = "failed"
        run.status.error_code = ErrorCode.NETWORK_ERROR.value


class _Cloud:
    def __init__(self, http: httpx.AsyncClient, run: _Run) -> None:
        self._http = http
        self._run = run

    async def post(self, path: str, body: dict[str, Any], *, auth: bool = True) -> Any:
        return await self.send("POST", path, body, auth=auth)

    async def send(self, method: str, path: str, body: dict[str, Any], *, auth: bool = True) -> Any:
        headers = {"Authorization": f"Bearer {self._run.token}"} if auth else {}
        try:
            response = await self._http.request(method, path, json=body, headers=headers)
        except httpx.HTTPError:
            raise OctopError.localized(ErrorCode.NETWORK_ERROR) from None
        renewed = response.headers.get("X-Octop-Access-Token")
        if renewed:
            self._run.token = renewed
        if response.status_code in {401, 403}:
            logger.warning("cloud refused the sign-in at %s: %s", path, response.status_code)
            raise OctopError.localized(ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED)
        if not response.is_success:
            logger.warning("cloud refused %s: %s %s", path, response.status_code, response.text)
            raise OctopError.localized(ErrorCode.NETWORK_ERROR)
        return response.json() if response.content else None


def _source(services: SharedServices, kind: str, item: str) -> str:
    install = services.settings_repo.get_or_insert(_INSTALL_KEY, new_ulid())
    return f"{install}:{kind}:{item}"


def _clip(value: Any) -> Any:
    if isinstance(value, str):
        return value if len(value) <= _MAX_TEXT else value[:_MAX_TEXT]
    if isinstance(value, list):
        return [_clip(item) for item in value]
    if isinstance(value, dict):
        return {key: _clip(item) for key, item in value.items()}
    return value


async def _thread_messages(
    services: SharedServices, registry: AgentManager, agent_id: str, thread_id: str
) -> list[dict[str, Any]]:
    """What the Bot remembers of a chat; the shown history when the Bot is not running."""
    messages: list[Any] = []
    try:
        messages = await load_checkpoint_messages(registry.get_agent(agent_id), thread_id)
    except OctopError:
        messages = []
    if not messages:
        rows, _ = await asyncio.to_thread(
            services.thread_message_repo.page, thread_id, limit=100_000
        )
        messages = messages_from_dict([json.loads(row.message_json) for row in rows])
    return _clip(messages_to_dict(messages))  # type: ignore[no-any-return]


async def _send_all(
    services: SharedServices,
    registry: AgentManager,
    user_id: int,
    cloud: _Cloud,
    status: MoveStatus,
) -> None:
    settings = services.settings_repo
    chief_id = await asyncio.to_thread(settings.get, chief_key(user_id)) or ""
    rows = [
        row
        for row in await asyncio.to_thread(services.agent_repo.list_by_user, user_id)
        if row.kind != "team" and not is_bridge_agent_id(row.agent_id)
    ]
    threads = {
        row.agent_id: [
            thread
            for thread in await asyncio.to_thread(
                services.thread_repo.list_by_agent_user,
                agent_id=row.agent_id,
                user_id=user_id,
                limit=_MAX_THREADS_PER_BOT,
            )
            if thread.channel_type == ThreadRegistry.CHANNEL_DASHBOARD and thread.last_active > 0
        ]
        for row in rows
    }
    groups = await asyncio.to_thread(services.repos.bot_group_repo.list_by_owner, user_id)
    status.total = len(rows) + sum(map(len, threads.values())) + len(groups) + 1

    moved: dict[str, str] = {}
    # Chief first: other Bots of the same name never take its place.
    for row in sorted(rows, key=lambda r: r.agent_id != chief_id):
        look = await asyncio.to_thread(bot_appearance, settings, row, chief_id)
        data = await cloud.post(
            "/api/octop-bot/move-in/bots",
            {
                "source": _source(services, "bot", row.agent_id),
                "name": row.name,
                "description": row.description,
                "system_prompt": row.system_prompt,
                "welcome_message": row.welcome_message,
                "look": {"shape": look.shape, "color": look.color},
                "chief": row.agent_id == chief_id,
            },
        )
        moved[row.agent_id] = str(data["id"])
        if is_private_bot(row) and row.agent_id != chief_id:
            bot_id = moved[row.agent_id]
            await cloud.send("PUT", f"/api/octop-bot/bots/{bot_id}/privacy", {"private": True})
        status.done += 1

    for agent_id, rows_for_bot in threads.items():
        for thread in rows_for_bot:
            messages = await _thread_messages(services, registry, agent_id, thread.thread_id)
            if messages:
                await cloud.post(
                    "/api/octop-bot/move-in/threads",
                    {
                        "source": _source(services, "thread", thread.thread_id),
                        "bot_id": moved[agent_id],
                        "title": thread.title,
                        "last_active": thread.last_active,
                        "messages": messages,
                    },
                )
            status.done += 1

    repo = services.repos.bot_group_repo
    for group in groups:
        members = [moved[i] for i in _ids(group["member_ids"]) if i in moved]
        admin = moved.get(group["admin_id"])
        if admin is not None:
            timeline = await asyncio.to_thread(repo.messages, group["group_id"], internal=True)
            await cloud.post(
                "/api/octop-bot/move-in/groups",
                {
                    "source": _source(services, "group", group["group_id"]),
                    "name": group["name"],
                    "admin_id": admin,
                    "member_ids": members,
                    "reply_mode": group["reply_mode"],
                    "memory": group["memory"] or "",
                    "goal": goal_json(group["goal"]),
                    "messages": [
                        {
                            "request_id": m["request_id"],
                            "slot": m["slot"],
                            "role": m["role"],
                            "agent_id": moved.get(m["agent_id"]) if m["agent_id"] else None,
                            "text": _clip(m["text"]),
                            "created_at": m["created_at"],
                        }
                        for m in timeline
                    ],
                },
            )
        status.done += 1

    notes = await asyncio.to_thread(settings.get, f"octop_bot:memory:{user_id}")
    if notes and notes.strip():
        await cloud.post("/api/octop-bot/move-in/notes", {"text": notes})
    status.done += 1


def _ids(raw: str) -> list[str]:
    value = json.loads(raw)
    return [str(item) for item in value] if isinstance(value, list) else []
