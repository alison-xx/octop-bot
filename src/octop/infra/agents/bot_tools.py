"""Chief's account-scoped team management tools."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Annotated, Any, Literal

from langchain_core.tools import StructuredTool
from langgraph.config import get_config
from pydantic import BaseModel, Field, GetPydanticSchema

from octop.infra.agents.bot_appearance import Character, bot_appearance, set_character
from octop.infra.agents.bot_sections import SectionAction, SectionName, read_layout, section_action
from octop.infra.agents.bot_workspace import can_join_bot_group, chief_key, is_private_bot
from octop.infra.errors import ErrorCode, OctopError

if TYPE_CHECKING:
    from octop.infra.agents.manager import AgentManager
    from octop.infra.db.services import SharedServices

TEAM_MAX_BOTS = 3
NAME_MAX = 40
ROLE_MAX = 200
INSTRUCTIONS_MAX = 8000
FIRST_TASK_MAX = 500
# One team per thread and name for a while: a retried or repeated call returns the first result.
TEAM_REUSE_SECONDS = 600
_recent_teams: dict[tuple[int, str, str], tuple[float, dict[str, Any]]] = {}
_team_locks: dict[tuple[int, str, str], asyncio.Lock] = {}


class TeamBot(BaseModel):
    # Lengths are checked in the tool so an overlong value is a SLASH_BAD_ARGS, not a schema error;
    # the schema still tells the model the limits.
    name: str = Field(description="Short display name.", json_schema_extra={"maxLength": NAME_MAX})
    role: str = Field(
        description="One line on what this bot does in the team.",
        json_schema_extra={"maxLength": ROLE_MAX},
    )
    instructions: str = Field(
        description="Concrete role instructions (the bot's system prompt).",
        json_schema_extra={"maxLength": INSTRUCTIONS_MAX},
    )
    avatar: Character | None = None


# Advertise the cap to the model while preserving SLASH_BAD_ARGS for older callers.
NewTeamBots = Annotated[
    list[TeamBot],
    GetPydanticSchema(
        get_pydantic_json_schema=lambda schema, handler: {
            **handler(schema),
            "maxItems": TEAM_MAX_BOTS,
        }
    ),
]


def chief_tools(
    registry: AgentManager, services: SharedServices, chief_id: str, owner: int
) -> list[StructuredTool]:
    def require_owner() -> None:
        ctx = get_config().get("configurable") or {}
        if (
            ctx.get("octop_bot_browser") is not True
            or str(ctx.get("user")) != str(owner)
            or ctx.get("agent_id") != chief_id
            or services.settings_repo.get(chief_key(owner)) != chief_id
        ):
            raise OctopError(ErrorCode.FORBIDDEN, "chief tools require the owner")

    def octop_bot_roster() -> dict[str, Any]:
        """List the owner's bots and group chats with their sidebar section names and IDs."""
        from octop.infra.bot_groups.service import list_groups

        require_owner()
        sections = read_layout(services, owner).sections
        memberships = {
            item: s.name for s in sections for item in s.items if item != f"bot:{chief_id}"
        }
        groups = list_groups(services, owner)
        return {
            "bots": [
                {
                    "agent_id": row.agent_id,
                    "name": row.name,
                    "description": row.description,
                    "section": memberships.get(f"bot:{row.agent_id}"),
                    "can_join_group": can_join_bot_group(row),
                    "is_main": row.agent_id == chief_id,
                    "enabled": bool(row.enabled),
                }
                for row in services.agent_repo.list_by_user(owner)
                if row.kind != "team" and not is_private_bot(row)
            ],
            "groups": [
                {**g.model_dump(), "section": memberships.get(f"group:{g.group_id}")}
                for g in groups
            ],
        }

    def octop_bot_sections(
        action: SectionAction,
        section: SectionName = "",
        bot_ids: list[str] | None = None,
        group_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Organize this owner's sidebar by project or role. These sections are folders for existing chats.

        list shows sections and their ordered bot:<id> / group:<id> entries. Use octop_bot_roster
        to resolve names. create finds or creates the named section and can file entries in one step.
        move files the supplied IDs into an existing section; an empty section moves them to Ungrouped.
        dissolve removes the named section and returns its entries to Ungrouped, preserving all chats.
        The Chief always stays at the top. Section names are matched exactly after trimming spaces.
        """
        require_owner()
        layout, changed = section_action(
            services, owner, action, section, bot_ids or [], group_ids or []
        )
        return {
            "action": action,
            "changed": changed,
            "revision": layout.revision,
            "sections": [s.model_dump() for s in layout.sections],
        }

    def file_entry(section: str, *, bot: str | None = None, group: str | None = None) -> None:
        section_action(
            services,
            owner,
            "create" if section.strip() else "move",
            section,
            [bot] if bot else [],
            [group] if group else [],
        )

    def file_new_entry(
        section: str, *, bot: str | None = None, group: str | None = None
    ) -> dict[str, str]:
        # Creation already committed. Return its identity even when filing hits a layout limit.
        try:
            file_entry(section, bot=bot, group=group)
        except OctopError as exc:
            return {"requested_section": section, "section_error": exc.code.value}
        return {}

    async def octop_bot_create(
        name: str,
        instructions: str,
        description: str = "",
        avatar: Character | None = None,
        section: SectionName | None = None,
    ) -> str | dict[str, str]:
        """Create an expert with role instructions and an optional mascot shape and color.

        An omitted avatar gets a stable, role-appropriate character. An optional sidebar section
        is found or created by name. Returns the agent ID. If filing failed, the result includes
        agent_id and section_error; use the existing ID when retrying the section change.
        """
        from octop.infra.agents.manager import AgentCreateSpec

        require_owner()
        if not name.strip() or not instructions.strip():
            raise OctopError(ErrorCode.SLASH_BAD_ARGS, "name and instructions are required")
        row = await registry.create(
            AgentCreateSpec(
                name=name.strip(),
                description=description,
                user_id=owner,
                system_prompt=instructions,
            ),
            defer_bootstrap=True,
        )
        if avatar is not None:
            await asyncio.to_thread(set_character, services.settings_repo, row, chief_id, avatar)
        else:
            await asyncio.to_thread(bot_appearance, services.settings_repo, row, chief_id)
        if section:
            failure = await asyncio.to_thread(file_new_entry, section, bot=row.agent_id)
            if failure:
                return {"agent_id": row.agent_id, **failure}
        return row.agent_id

    async def octop_bot_update(
        agent_id: str,
        name: str | None = None,
        description: str | None = None,
        avatar: Character | None = None,
        section: SectionName | None = None,
    ) -> str:
        """Update an owned bot. A sidebar section name finds or creates it; an empty string unfiles the bot."""
        require_owner()
        row = registry.get_row(agent_id)
        if row is None or row.user_id != owner or row.kind == "team" or is_private_bot(row):
            raise OctopError(ErrorCode.AGENT_NOT_FOUND, "unknown bot")
        if agent_id == chief_id and section is not None:
            raise OctopError.localized(ErrorCode.FORBIDDEN)
        if name is not None and not name.strip():
            raise OctopError(ErrorCode.SLASH_BAD_ARGS, "name is required")
        changes = {}
        if name is not None:
            changes["name"] = name.strip()
        if description is not None:
            changes["description"] = description
        if changes:
            await registry.update(agent_id, **changes)
        if avatar is not None:
            await asyncio.to_thread(set_character, services.settings_repo, row, chief_id, avatar)
        if section is not None:
            await asyncio.to_thread(file_entry, section, bot=agent_id)
        return agent_id

    def octop_bot_list_avatar_photos(offset: int = 0) -> dict[str, Any]:
        """List reusable photos from the owner's avatar library. Pass next as offset for another page."""
        from octop.infra.agents.bot_avatar_library import list_photo_refs

        require_owner()
        return list_photo_refs(services, owner, offset=offset).model_dump()

    async def octop_bot_set_photo(agent_id: str, photo_id: str) -> str:
        """Use an imported avatar photo on an owned bot. Select photo_id from octop_bot_list_avatar_photos."""
        from octop.infra.agents.bot_avatar_library import apply_library_photo

        require_owner()
        row = registry.get_row(agent_id)
        if row is None or row.user_id != owner or row.kind == "team" or is_private_bot(row):
            raise OctopError.localized(ErrorCode.AGENT_NOT_FOUND)
        return await apply_library_photo(services, registry, agent_id, owner, photo_id)

    async def octop_bot_create_group(
        name: str,
        admin_id: str,
        member_ids: list[str],
        reply_mode: Literal["admin_first", "all_members"] = "admin_first",
        section: SectionName | None = None,
    ) -> Any:
        """Create a group chat with a bot administrator and roster; optionally file it in a named sidebar section."""
        from octop.infra.bot_groups.service import create_group

        require_owner()
        group = await asyncio.to_thread(
            create_group,
            services,
            owner,
            name=name,
            admin_id=admin_id,
            member_ids=member_ids,
            reply_mode=reply_mode,
        )
        result = group.model_dump()
        if section:
            result.update(await asyncio.to_thread(file_new_entry, section, group=group.group_id))
        await asyncio.to_thread(
            note_onboarding_team,
            group.group_id,
            [i for i in dict.fromkeys([group.admin_id, *group.member_ids]) if i != chief_id],
            section or None,
            "",
        )
        return result

    def note_onboarding_team(
        group_id: str, bot_ids: list[str], section: str | None, first_task: str
    ) -> None:
        from octop.infra.agents.bot_onboarding import OnboardingTeam, record_team

        team = OnboardingTeam(
            group_id=group_id, bot_ids=bot_ids, section=section, first_task=first_task.strip()
        )
        record_team(services, owner, team)

    async def octop_bot_create_team(
        team_name: str,
        bots: NewTeamBots,
        admin: str,
        first_task: str = "",
        reply_mode: Literal["admin_first", "all_members"] = "admin_first",
        existing_bot_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create the group and its sidebar section in one call. Supply 0–3 NEW bots (name, role,
        concise instructions) plus existing_bot_ids from the owner's roster. Set admin to a new bot's
        name or an included existing bot ID. The group needs at least one member. Only new bots and
        the group are filed in the section; existing bots keep their folders. first_task is an
        optional starter message. Success returns the saved member_ids, admin_id, group_id and
        section; a filing failure returns section_error. bot_ids lists only the newly created bots,
        including those retained on partial failure. Reuse their IDs on retry.
        """
        from octop.infra.bot_groups.service import MAX_GROUP_MEMBERS, eligible_members

        require_owner()
        name = team_name.strip()
        names = [b.name.strip() for b in bots]
        existing = list(dict.fromkeys(existing_bot_ids or []))
        if not name or not (bots or existing) or len(bots) > TEAM_MAX_BOTS:
            raise OctopError(
                ErrorCode.SLASH_BAD_ARGS,
                f"team_name and members required; at most {TEAM_MAX_BOTS} new bots per call",
            )
        if any(not n or not b.instructions.strip() for n, b in zip(names, bots, strict=True)):
            raise OctopError(ErrorCode.SLASH_BAD_ARGS, "every bot needs a name and instructions")
        if len(set(names)) != len(names) or set(names).intersection(existing):
            raise OctopError(ErrorCode.SLASH_BAD_ARGS, "new bot names must be unambiguous")
        if admin.strip() not in names and admin.strip() not in existing:
            raise OctopError(ErrorCode.SLASH_BAD_ARGS, "admin must be a team member")
        if len(existing) + len(names) > MAX_GROUP_MEMBERS:
            raise OctopError.localized(ErrorCode.TEAM_MEMBER_INVALID)
        if (
            len(name) > NAME_MAX
            or len(first_task) > FIRST_TASK_MAX
            or any(
                len(n) > NAME_MAX
                or len(b.role) > ROLE_MAX
                or len(b.instructions) > INSTRUCTIONS_MAX
                for n, b in zip(names, bots, strict=True)
            )
        ):
            raise OctopError(
                ErrorCode.SLASH_BAD_ARGS,
                f"names up to {NAME_MAX} characters, roles {ROLE_MAX}, instructions "
                f"{INSTRUCTIONS_MAX}, first_task {FIRST_TASK_MAX}",
            )
        thread = str((get_config().get("configurable") or {}).get("thread_id") or "")
        key = (owner, thread, name)
        async with _team_locks.setdefault(key, asyncio.Lock()):
            now = time.monotonic()
            for stale in [
                k for k, (at, _) in _recent_teams.items() if now - at > TEAM_REUSE_SECONDS
            ]:
                _recent_teams.pop(stale, None)
            # Locks for calls that are done and no longer remembered go too, so neither map grows.
            for idle in [
                k
                for k, lock in _team_locks.items()
                if k != key and not lock.locked() and k not in _recent_teams
            ]:
                _team_locks.pop(idle, None)
            if thread and key in _recent_teams:
                return {**_recent_teams[key][1], "reused": True}
            if existing:
                await asyncio.to_thread(eligible_members, services, owner, existing)
            result = await _create_team(
                name, bots, names, existing, admin.strip(), first_task, reply_mode
            )
            if thread and "group_id" in result:
                _recent_teams[key] = (time.monotonic(), result)
            return result

    async def _create_team(
        name: str,
        bots: list[TeamBot],
        names: list[str],
        existing: list[str],
        admin: str,
        first_task: str,
        reply_mode: Literal["admin_first", "all_members"],
    ) -> dict[str, Any]:
        from octop.infra.agents.manager import AgentCreateSpec
        from octop.infra.bot_groups.service import create_group

        created: list[str] = []
        try:
            for bot, bot_name in zip(bots, names, strict=True):
                row = await registry.create(
                    AgentCreateSpec(
                        name=bot_name,
                        description=bot.role.strip(),
                        user_id=owner,
                        system_prompt=bot.instructions,
                    ),
                    defer_bootstrap=True,
                )
                created.append(row.agent_id)
                if bot.avatar is not None:
                    await asyncio.to_thread(
                        set_character, services.settings_repo, row, chief_id, bot.avatar
                    )
                else:
                    await asyncio.to_thread(bot_appearance, services.settings_repo, row, chief_id)
            admin_id = admin if admin in existing else created[names.index(admin)]
            group = await asyncio.to_thread(
                create_group,
                services,
                owner,
                name=name,
                admin_id=admin_id,
                member_ids=[*created, *existing],
                reply_mode=reply_mode,
            )
        except OctopError as exc:
            if not created:
                raise
            return {"bot_ids": created, "error": exc.code.value}
        result: dict[str, Any] = {
            "group_id": group.group_id,
            "name": group.name,
            "admin_id": admin_id,
            "bot_ids": created,
            "member_ids": group.member_ids,
        }
        try:
            await asyncio.to_thread(
                section_action, services, owner, "create", name, created, [group.group_id]
            )
        except OctopError as exc:
            # The team exists either way; only filing it in the sidebar failed.
            result.update({"requested_section": name, "section_error": exc.code.value})
        else:
            result["section"] = name
        await asyncio.to_thread(
            note_onboarding_team,
            group.group_id,
            [i for i in [*created, *existing] if i != chief_id],
            result.get("section"),
            first_task,
        )
        return result

    def octop_bot_update_group(
        group_id: str,
        name: str | None = None,
        admin_id: str | None = None,
        member_ids: list[str] | None = None,
        reply_mode: Literal["admin_first", "all_members"] | None = None,
        section: SectionName | None = None,
    ) -> dict[str, Any]:
        """Update specified group chat fields. A section name finds or creates it; an empty string unfiles the chat."""
        from octop.infra.bot_groups.service import Group, group_row, update_group

        require_owner()
        changes = {
            "name": name,
            "admin_id": admin_id,
            "member_ids": member_ids,
            "reply_mode": reply_mode,
        }
        changes = {key: value for key, value in changes.items() if value is not None}
        group = (
            update_group(services, owner, group_id, changes)
            if changes
            else Group.from_record(group_row(services, owner, group_id))
        )
        if section is not None:
            file_entry(section, group=group_id)
        return group.model_dump()

    def octop_bot_team_memory(text: str) -> str:
        """Replace the owner's shared team notes when explicitly requested. Preserve unrelated notes."""
        require_owner()
        if len(text) > 12000:
            raise OctopError(ErrorCode.SLASH_BAD_ARGS, "team notes too long")
        services.settings_repo.set(f"octop_bot:memory:{owner}", text)
        return text

    async def octop_bot_delete(kind: Literal["bot", "group"], resource_id: str) -> str:
        """Delete a named bot or group after owner approval. Only use for an explicit deletion request."""
        from octop.infra.bot_groups.service import group_row

        require_owner()
        if kind == "group":
            group_row(services, owner, resource_id)
            services.repos.bot_group_repo.delete(resource_id, owner)
        else:
            row = registry.get_row(resource_id)
            if row is None or row.user_id != owner or row.kind == "team" or is_private_bot(row):
                raise OctopError(ErrorCode.FORBIDDEN, "bot cannot be removed")
            await registry.delete(resource_id)
        return resource_id

    return [
        StructuredTool.from_function(func=octop_bot_roster),
        StructuredTool.from_function(func=octop_bot_sections),
        StructuredTool.from_function(coroutine=octop_bot_create),
        StructuredTool.from_function(coroutine=octop_bot_update),
        StructuredTool.from_function(func=octop_bot_list_avatar_photos),
        StructuredTool.from_function(coroutine=octop_bot_set_photo),
        StructuredTool.from_function(coroutine=octop_bot_create_group),
        StructuredTool.from_function(coroutine=octop_bot_create_team),
        StructuredTool.from_function(func=octop_bot_update_group),
        StructuredTool.from_function(func=octop_bot_team_memory),
        StructuredTool.from_function(coroutine=octop_bot_delete),
    ]
