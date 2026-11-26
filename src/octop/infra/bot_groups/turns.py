"""Execute a room turn via the normal Octop gateway and per-member checkpoints."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from octop_gateway.models import ChannelSubject, InboundMessage, TextContent
from pydantic import ValidationError

from octop.i18n import tr
from octop.i18n.domains.stream import format_stream_error
from octop.infra.bot_groups.service import (
    Goal,
    Group,
    Message,
    eligible_members,
    group_row,
    list_messages,
)
from octop.infra.db.services import SharedServices
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.users.identity import User
from octop.infra.utils.ulid import new_ulid

if TYPE_CHECKING:
    from octop.infra.db.repos.bot_groups import BotGroupRepo
    from octop.infra.server import AppRuntime

_GOAL_BLOCK = re.compile(r"(?:^|\n)```octop-goal\s*\n(.*?)\n```\s*$", re.DOTALL)


def mentions(text: str, names: dict[str, str]) -> list[str]:
    """Use @id for ambiguous names. Longest names win, including names with spaces."""
    handles: dict[str, list[str]] = {}
    for key, name in names.items():
        for label in {key, name}:
            handles.setdefault(label, []).append(key)
    if not handles:
        return []
    pattern = (
        r"(?<![a-zA-Z0-9_@])@("
        + "|".join(re.escape(s) for s in sorted(handles, key=len, reverse=True))
        + r")(?![a-zA-Z0-9_-])"
    )
    return list(
        dict.fromkeys(
            handles[m[1]][0] for m in re.finditer(pattern, text) if len(handles[m[1]]) == 1
        )
    )


def _goal_edit(
    text: str, row: dict[str, Any], group: Group, history: list[dict[str, Any]]
) -> tuple[str, Goal | None]:
    block = _GOAL_BLOCK.search(text)
    if block is None:
        return text, None
    try:
        proposed = Goal.model_validate_json(block[1])
    except ValidationError:
        return text, None
    if any(
        stage.assignee_id and stage.assignee_id not in group.member_ids for stage in proposed.stages
    ):
        return text, None
    old = Goal.model_validate_json(row["goal"]) if row["goal"] else None
    if old is None or old.status == "draft":
        if proposed.status != "draft":
            return text, None
    else:
        if old.status == "done" or proposed.status == "draft":
            return text, None
        if (old.title, old.criteria) != (proposed.title, proposed.criteria):
            return text, None
        if [(s.title, s.assignee_id) for s in old.stages] != [
            (s.title, s.assignee_id) for s in proposed.stages
        ]:
            return text, None
        for before, after in zip(old.stages, proposed.stages, strict=True):
            if before.status == "done" and before != after:
                return text, None
            if (
                after.status == "done"
                and before.status != "done"
                and not any(
                    m["role"] == "assistant"
                    and m["message_id"] in after.evidence
                    and (after.assignee_id is None or m["agent_id"] == after.assignee_id)
                    for m in history
                )
            ):
                return text, None
    return text[: block.start()].strip() or proposed.title, proposed


def _stage_acceptance(
    text: str, saved: str, index: int, delivery: dict[str, Any], admin_id: str
) -> tuple[str, Goal] | None:
    lines = text.rstrip().splitlines()
    if not lines or lines[-1].strip() != f"[ACCEPT {delivery['message_id']}]":
        return None
    goal = Goal.model_validate_json(saved)
    if goal.status != "active" or index >= len(goal.stages):
        return None
    stage = goal.stages[index]
    if stage.status == "done" or (stage.assignee_id or admin_id) != delivery["agent_id"]:
        return None
    stage.status, stage.evidence = "done", delivery["message_id"]
    if all(item.status == "done" for item in goal.stages):
        goal.status = "done"
    return "\n".join(lines[:-1]).strip() or stage.title, goal


def room_request(prompt: str) -> str | None:
    """What the user said in the room, from the prompt a member received for it."""
    for part in reversed(prompt.split("\n\n")):
        if not part.startswith("{"):
            continue
        try:
            context = json.loads(part)
        except ValueError:
            continue
        if isinstance(context, dict) and isinstance(context.get("user_request"), str):
            return str(context["user_request"])
    return None


def show_room_history(messages: list[dict[str, Any]], repo: BotGroupRepo, thread_id: str) -> None:
    """Present the user's request and the answer actually published to the room."""
    for message in messages:
        if not isinstance(message.get("content"), list):
            continue
        text = "".join(
            str(block.get("text") or "")
            for block in message["content"]
            if isinstance(block, dict) and block.get("type") == "text"
        )
        visible = None
        if message.get("role") == "user":
            visible = room_request(text)
        elif message.get("role") == "assistant" and (block := _GOAL_BLOCK.search(text)):
            try:
                goal = Goal.model_validate_json(block[1])
            except ValidationError:
                continue
            visible = repo.published_reply(
                thread_id,
                text.strip(),
                text[: block.start()].strip() or goal.title,
                message.get("timestamp") or 0,
            )
        if visible is not None and visible != text:
            message["content"] = [
                *(
                    b
                    for b in message["content"]
                    if not (isinstance(b, dict) and b.get("type") == "text")
                ),
                {"type": "text", "text": visible},
            ]


def _is_pass(reply: str) -> bool:
    return reply.strip().rstrip("。.!！").strip().upper() == "[PASS]"


class RoomTurn:
    def __init__(
        self,
        services: SharedServices,
        runtime: AppRuntime,
        user: User,
        group: Group,
        request_id: str,
        token: str,
        text: str,
        attachment_paths: list[str],
    ) -> None:
        self.services = services
        self.repo = services.repos.bot_group_repo
        self.runtime = runtime
        self.user = user
        self.group = group
        self.request_id = request_id
        self.token = token
        self.text = text
        self.attachment_paths = attachment_paths

    async def speak(
        self,
        agent_id: str,
        names: dict[str, str],
        *,
        wrap: bool = False,
        stage_index: int | None = None,
        assignment: str | None = None,
        may_pass: bool = False,
    ) -> str:
        """Run one member's turn and store its reply.

        Only a member that may stay silent (``may_pass``: a non-administrator in
        an all-members round it was not mentioned in) is offered ``[PASS]``.
        Everyone else must answer: a ``[PASS]`` from them is asked again once,
        and a second one leaves a visible notice instead of an empty turn.
        """
        group = self.group
        slot = "wrap:" + agent_id if wrap else "reply:" + agent_id
        if stage_index is not None:
            slot = f"stage-{stage_index}:{slot}"
        # On retry, continue from existing member replies (including silent [PASS] turns).
        for saved in await asyncio.to_thread(
            self.repo.messages, group.group_id, request_id=self.request_id, internal=True
        ):
            if saved["slot"] == slot:
                return str(saved["text"]) if saved["role"] == "assistant" else ""
        thread_id = None
        try:
            room = await asyncio.to_thread(group_row, self.services, self.user.id, group.group_id)
            current_members = Group.from_record(room).member_ids
            if agent_id not in current_members:
                raise OctopError.localized(ErrorCode.TEAM_MEMBER_INVALID)
            live_members = await asyncio.to_thread(
                eligible_members, self.services, self.user.id, current_members
            )
            row = live_members[agent_id]
            if not row.enabled:
                raise OctopError.localized(ErrorCode.AGENT_NOT_RUNNING)
            # Recheck membership for each handoff. Removed and private agents receive no group data.
            active_names = {key: value for key, value in names.items() if key in current_members}
            history = await asyncio.to_thread(self.repo.messages, group.group_id, recent=40)
            quoted = [
                {
                    "message_id": m["message_id"],
                    "speaker": m["agent_id"] or "user",
                    "text": m["text"][-2200:],
                    **(
                        {"attachment_paths": m["attachment_paths"]} if m["attachment_paths"] else {}
                    ),
                }
                for m in history
                if m["role"] != "error"
                and not (m["role"] == "user" and m["request_id"] == self.request_id)
            ]
            prompt = [
                tr(
                    "bot_rooms.context",
                    self.user.locale,
                    name=row.name,
                    room=group.name,
                    members=", ".join(f"{n} ({i})" for i, n in active_names.items()),
                )
            ]
            prompt.append(
                tr("bot_rooms.may_pass" if may_pass else "bot_rooms.must_answer", self.user.locale)
            )
            if agent_id == group.admin_id and not (wrap and stage_index is not None):
                prompt.append(
                    tr(
                        "bot_rooms.admin",
                        self.user.locale,
                        schema=json.dumps(
                            Goal.model_json_schema(), ensure_ascii=False, separators=(",", ":")
                        ),
                    )
                )
            if agent_id == group.admin_id and not room["goal"] and not wrap and not assignment:
                prompt.append(tr("bot_rooms.first_answer", self.user.locale))
            context = {
                "team_memory": await asyncio.to_thread(
                    self.services.settings_repo.get, f"octop_bot:memory:{self.user.id}"
                )
                or "",
                "group_memory": room["memory"],
                "goal": json.loads(room["goal"]) if room["goal"] else None,
                "recent_messages": quoted,
                "user_request": self.text,
                **({"attachment_paths": self.attachment_paths} if self.attachment_paths else {}),
            }
            if self.attachment_paths:
                prompt.append(tr("bot_rooms.attachments", self.user.locale))
            prompt.append(json.dumps(context, ensure_ascii=False))
            delivery = None
            if wrap:
                prompt.append(tr("bot_rooms.wrap", self.user.locale))
                if stage_index is not None:
                    delivery = next(
                        (
                            m
                            for m in reversed(history)
                            if m["request_id"] == self.request_id
                            and m["slot"].startswith(f"stage-{stage_index}:reply:")
                            and m["role"] == "assistant"
                        ),
                        None,
                    )
                    if delivery:
                        prompt.append(
                            tr(
                                "bot_rooms.stage_review",
                                self.user.locale,
                                stage=stage_index + 1,
                                message_id=delivery["message_id"],
                            )
                        )
            elif assignment:
                prompt.append(tr("bot_rooms.stage", self.user.locale, title=assignment))
            registry = self.runtime.gateway.thread_registry
            channel_type = ThreadRegistry.CHANNEL_BOT_GROUP
            session_key = ThreadRegistry.make_key(
                agent_id=agent_id,
                channel_type=channel_type,
                channel_subject_id=str(self.user.id),
                channel_chat_type=group.group_id,
            )
            thread_id = await registry.get_or_create_by_key(
                session_key=session_key,
                agent_id=agent_id,
                user_id=self.user.id,
                channel_type=channel_type,
                channel_channel_id="octop-bot",
            )
            # Named after the room, so the member's history lists it and no title is generated.
            await asyncio.to_thread(
                registry.update_title,
                thread_id,
                tr("bot_rooms.thread_title", self.user.locale, room=group.name),
            )

            def inbound(text: str) -> InboundMessage:
                return InboundMessage(
                    channel_id="octop-bot",
                    channel_type=channel_type,
                    tenant_id=agent_id,
                    channel_subject=ChannelSubject(subject_id=str(self.user.id)),
                    channel_session_id=session_key,
                    content=[TextContent(text=text)],
                    metadata={
                        "thread_id": thread_id,
                        "session_key": session_key,
                        "user_is_admin": self.user.is_admin,
                    },
                )

            async def stream(text: str) -> tuple[str, str]:
                pieces: list[str] = []
                role = "assistant"
                flushed_at = 0.0
                started = time.monotonic()
                last_draft = ""
                phase = ""
                async for chunk in self.runtime.gateway.processor.iter_turn_chunks(inbound(text)):
                    kind = chunk.get("type")
                    if kind in {"token", "delta"}:
                        pieces.append(str(chunk.get("content") or chunk.get("text") or ""))
                        if not last_draft or time.monotonic() - flushed_at >= 0.5:
                            draft = "".join(pieces).split("```octop-goal", 1)[0]
                            if (
                                not draft.strip()
                                or draft == last_draft
                                or (not last_draft and re.fullmatch(r"[\s*_`#>~-]+", draft))
                            ):
                                flushed_at = time.monotonic()
                                continue
                            await asyncio.to_thread(
                                self.repo.draft,
                                group.group_id,
                                self.request_id,
                                self.token,
                                slot,
                                agent_id,
                                draft,
                            )
                            flushed_at = time.monotonic()
                            if not last_draft:
                                logging.getLogger(__name__).info(
                                    "Group reply first draft thread=%s request=%s elapsed_ms=%d",
                                    thread_id,
                                    self.request_id,
                                    (flushed_at - started) * 1000,
                                )
                            last_draft = draft
                    elif (
                        not last_draft
                        and kind in {"reasoning", "tool_call_chunk"}
                        and kind != phase
                    ):
                        phase = kind
                        await asyncio.to_thread(
                            self.repo.draft,
                            group.group_id,
                            self.request_id,
                            self.token,
                            slot,
                            agent_id,
                            tr(
                                "bot_rooms.thinking"
                                if kind == "reasoning"
                                else "bot_rooms.using_tool",
                                self.user.locale,
                            ),
                        )
                    elif kind == "hitl_required":
                        pieces.append("\n" + tr("bot_rooms.approval", self.user.locale))
                    elif kind == "error":
                        role = "error"
                        pieces.append(
                            str(
                                chunk.get("message")
                                or tr("errors.INTERNAL_ERROR", self.user.locale)
                            )
                        )
                logging.getLogger(__name__).info(
                    "Group reply finished thread=%s request=%s elapsed_ms=%d",
                    thread_id,
                    self.request_id,
                    (time.monotonic() - started) * 1000,
                )
                reply = "".join(pieces).strip()
                if role == "assistant" and _is_pass(reply):
                    return "pass", reply
                if not reply:
                    return "error", tr("bot_rooms.no_reply", self.user.locale)
                return role, reply

            began = await asyncio.to_thread(
                self.repo.begin_reply, group.group_id, self.request_id, self.token, slot, agent_id
            )
            if not began:
                # The old process may already have executed tools. A missing final response
                # does not establish that repeating its side effects is safe.
                await asyncio.to_thread(
                    self.repo.reply,
                    group.group_id,
                    self.request_id,
                    self.token,
                    slot,
                    "error",
                    agent_id,
                    tr("bot_rooms.interrupted", self.user.locale),
                    thread_id,
                )
                return ""
            role, reply = await stream("\n\n".join(prompt))
            if role == "pass" and not may_pass:
                # This member has to answer this turn; ask once more in the same thread.
                role, reply = await stream(tr("bot_rooms.pass_retry", self.user.locale))
                if role == "pass":
                    role, reply = "error", tr("bot_rooms.pass_fallback", self.user.locale)
            if agent_id == group.admin_id and role == "assistant" and (stage_index is None or wrap):
                safe_text, proposed = _goal_edit(reply, room, group, history)
                review = None
                if wrap and stage_index is not None and delivery is not None and room["goal"]:
                    review = _stage_acceptance(
                        reply, room["goal"], stage_index, delivery, group.admin_id
                    )
                    if review:
                        safe_text, proposed = review
                if proposed is not None and await asyncio.to_thread(
                    self.repo.set_goal,
                    group.group_id,
                    self.user.id,
                    proposed.model_dump_json(),
                    room["goal"],
                ):
                    reply = safe_text
                elif review:
                    reply = safe_text + "\n\n" + tr("bot_rooms.goal_not_saved", self.user.locale)
                elif block := _GOAL_BLOCK.search(reply):
                    reply = (
                        reply[: block.start()].strip()
                        + "\n\n"
                        + tr("bot_rooms.goal_not_saved", self.user.locale)
                    ).strip()
        except Exception as exc:
            role, reply = "error", format_stream_error(exc, self.user.locale)
        await asyncio.to_thread(
            self.repo.reply,
            group.group_id,
            self.request_id,
            self.token,
            slot,
            role,
            agent_id,
            reply,
            thread_id,
        )
        return reply if role == "assistant" else ""

    async def run(self, names: dict[str, str], explicit: list[str]) -> None:
        group = self.group
        first = explicit or mentions(self.text, names)
        sequential = not first and group.reply_mode == "all_members"
        targets = first or (list(names) if sequential else [group.admin_id])
        visited: set[str] = set()
        delegated = False
        while targets:
            visited.update(targets)
            if sequential:
                # Everyone answers in turn; members other than the administrator may pass.
                replies = [
                    await self.speak(key, names, may_pass=key != group.admin_id and len(names) > 1)
                    for key in targets
                ]
                sequential = False
            else:
                replies = await asyncio.gather(*(self.speak(key, names) for key in targets))
            targets = list(
                dict.fromkeys(
                    key for reply in replies for key in mentions(reply, names) if key not in visited
                )
            )
            if targets:
                room = await asyncio.to_thread(
                    group_row, self.services, self.user.id, group.group_id
                )
                if room["goal"] and Goal.model_validate_json(room["goal"]).status == "draft":
                    # The first round already honored user mentions. Names in a proposed
                    # plan are future assignments until the user activates that plan.
                    break
            delegated |= bool(targets)
        if delegated and group.admin_id in visited:
            await self.speak(group.admin_id, names, wrap=True)

    async def run_goal(self, names: dict[str, str]) -> None:
        """Advance only while the administrator has accepted the previous evidence."""
        while True:
            row = await asyncio.to_thread(
                group_row, self.services, self.user.id, self.group.group_id
            )
            if not row["goal"]:
                return
            goal = Goal.model_validate_json(row["goal"])
            if goal.status != "active":
                return
            current = next(
                ((idx, s) for idx, s in enumerate(goal.stages) if s.status != "done"), None
            )
            if current is None:
                goal.status = "done"
                await asyncio.to_thread(
                    self.repo.set_goal,
                    self.group.group_id,
                    self.user.id,
                    goal.model_dump_json(),
                    row["goal"],
                )
                return
            idx, stage = current
            actor = stage.assignee_id or self.group.admin_id
            if not await self.speak(actor, names, stage_index=idx, assignment=stage.title):
                return
            await self.speak(self.group.admin_id, names, stage_index=idx, wrap=True)
            updated = await asyncio.to_thread(
                group_row, self.services, self.user.id, self.group.group_id
            )
            revised = Goal.model_validate_json(updated["goal"])
            if (
                len(revised.stages) <= idx
                or revised.stages[idx].title != stage.title
                or revised.stages[idx].status != "done"
            ):
                return


async def run_confirmed_goal(
    services: SharedServices, runtime: AppRuntime, user: User, group_id: str, goal: Goal
) -> None:
    digest = hashlib.sha256(goal.model_dump_json().encode()).hexdigest()
    await send_message(
        services,
        runtime,
        user,
        group_id,
        text=tr("bot_rooms.activation", user.locale, title=goal.title),
        mention_ids=[],
        request_id=f"goal-{digest}",
        goal_run=True,
    )


async def send_message(
    services: SharedServices,
    runtime: AppRuntime,
    user: User,
    group_id: str,
    *,
    text: str,
    mention_ids: list[str],
    request_id: str,
    goal_run: bool = False,
    attachment_paths: list[str] | None = None,
    owner_commands: bool = False,
) -> list[Message]:
    from octop.infra.bot_groups.workspace import require_artifacts

    row = await asyncio.to_thread(group_row, services, user.id, group_id)
    group = Group.from_record(row)
    explicit = list(dict.fromkeys(mention_ids))
    if any(key not in group.member_ids for key in explicit):
        raise OctopError.localized(ErrorCode.TEAM_MEMBER_INVALID)
    repo = services.repos.bot_group_repo
    paths = list(dict.fromkeys(attachment_paths or ()))
    if not text.strip() and not paths:
        raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS)
    if paths and not await asyncio.to_thread(repo.has_turn, group_id, request_id):
        await asyncio.to_thread(require_artifacts, services, user.id, group_id, paths)
    activate = None
    command = text.strip().casefold().rstrip("。.!！")
    resume = command in {"继续执行目标", "resume goal"}
    if (
        owner_commands
        and not explicit
        and not paths
        and (
            resume
            or command
            in {
                "激活",
                "激活目标",
                "确认激活",
                "开始执行",
                "activate",
                "activate goal",
                "start the plan",
            }
        )
        and row["goal"]
    ):
        goal = Goal.model_validate_json(row["goal"])
        previous_run = await asyncio.to_thread(repo.was_goal_run, group_id, request_id)
        if previous_run is not None:
            goal_run = previous_run
        elif resume and goal.status == "active":
            activate = (user.id, row["goal"], row["goal"])
            goal_run = True
        elif not resume and goal.status == "draft" and goal.criteria.strip() and goal.stages:
            # The saved draft is the plan the owner approved. A generated status
            # block cannot approve a plan or substitute different assignments.
            goal.status = "active"
            activate = (user.id, row["goal"], goal.model_dump_json())
            goal_run = True
        else:
            raise OctopError.localized(
                ErrorCode.SLASH_BAD_ARGS,
                details={"reason": tr("bot_rooms.no_activatable_goal", user.locale)},
            )
    token = new_ulid()
    inputs: list[Any] = [text, explicit, goal_run]
    if paths:
        inputs.append(paths)
    input_json = json.dumps(inputs, ensure_ascii=False)
    state = await asyncio.to_thread(
        repo.claim,
        group_id,
        request_id,
        input_json,
        text,
        token,
        activate=activate,
        goal_run=goal_run,
    )
    if state == "conflict":
        raise OctopError.localized(ErrorCode.THREAD_TURN_ACTIVE)
    if state in {"busy", "finished"}:
        return await asyncio.to_thread(
            list_messages, services, user.id, group_id, request_id=request_id
        )

    async def refresh_lease() -> None:
        while True:
            await asyncio.sleep(repo.LEASE_SECONDS / 3)
            if not await asyncio.to_thread(repo.lease, group_id, request_id, token):
                return

    heartbeat = asyncio.create_task(refresh_lease())
    finished = False
    try:
        members = await asyncio.to_thread(eligible_members, services, user.id, group.member_ids)
        turn = RoomTurn(services, runtime, user, group, request_id, token, text, paths)
        names = {key: row.name for key, row in members.items()}
        if goal_run:
            await turn.run_goal(names)
        else:
            await turn.run(names, explicit)
        finished = True
    finally:
        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat
        await asyncio.to_thread(
            repo.lease, group_id, request_id, token, close=True, finished=finished
        )
    return await asyncio.to_thread(
        list_messages, services, user.id, group_id, request_id=request_id
    )


async def recover_room_turns(services: SharedServices, runtime: AppRuntime) -> None:
    pending = await asyncio.to_thread(services.repos.bot_group_repo.unfinished)

    async def recover(turn: dict[str, Any]) -> None:
        await asyncio.sleep(max(0, turn["lease_until"] - time.time() + 0.1))
        user = runtime.user_manager.get_by_id(turn["user_id"])
        if user is None:
            return
        try:
            inputs = json.loads(turn["input_json"])
            text, explicit, goal_run = inputs[:3]
            await send_message(
                services,
                runtime,
                user,
                turn["group_id"],
                text=text,
                mention_ids=explicit,
                request_id=turn["request_id"],
                goal_run=goal_run,
                attachment_paths=inputs[3] if len(inputs) > 3 else None,
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "Could not resume Bot group %s turn %s", turn["group_id"], turn["request_id"]
            )

    await asyncio.gather(*(recover(turn) for turn in pending))
