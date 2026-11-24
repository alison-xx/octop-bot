"""Chief's account-scoped team management tools."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.tools import StructuredTool
from langgraph.config import get_config
from pydantic import BaseModel, Field

from octop.infra.agents.bot_appearance import Character, bot_appearance, set_character
from octop.infra.agents.bot_sections import SectionAction, SectionName, read_layout, section_action
from octop.infra.agents.bot_workspace import chief_key, is_private_bot, list_bot_cards
from octop.infra.errors import ErrorCode, OctopError

if TYPE_CHECKING:
    from octop.infra.agents.manager import AgentManager
    from octop.infra.db.services import SharedServices

TEAM_MAX_BOTS = 6


class TeamBot(BaseModel):
    name: str = Field(description="Short display name.")
    role: str = Field(description="One line on what this bot does in the team.")
    instructions: str = Field(description="Concrete role instructions (the bot's system prompt).")
    avatar: Character | None = None


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
        bots = list_bot_cards(services, owner, chief_id, include_private=False)
        groups = list_groups(services, owner)
        return {
            "bots": [{**b, "section": memberships.get(f"bot:{b['agent_id']}")} for b in bots],
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
        bots: list[TeamBot],
        admin: str,
        first_task: str = "",
        reply_mode: Literal["admin_first", "all_members"] = "admin_first",
    ) -> dict[str, Any]:
        """Create a whole team in one call: new bots, a group chat and a sidebar section.

        team_name names both the group chat and the sidebar section. admin is the name of one
        of the new bots; it answers first in the group. first_task is one message the owner can
        post in the group to start. If a bot or the group fails, the result lists the bot_ids
        already created and the error code; reuse those IDs instead of creating them again.
        """
        from octop.infra.agents.manager import AgentCreateSpec
        from octop.infra.bot_groups.service import create_group

        require_owner()
        name = team_name.strip()
        names = [b.name.strip() for b in bots]
        if not name or not bots or len(bots) > TEAM_MAX_BOTS:
            raise OctopError(
                ErrorCode.SLASH_BAD_ARGS, f"team_name and 1-{TEAM_MAX_BOTS} bots required"
            )
        if any(not n or not b.instructions.strip() for n, b in zip(names, bots, strict=True)):
            raise OctopError(ErrorCode.SLASH_BAD_ARGS, "every bot needs a name and instructions")
        if len(set(names)) != len(names) or admin.strip() not in names:
            raise OctopError(ErrorCode.SLASH_BAD_ARGS, "admin must name one of the new bots")
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
            admin_id = created[names.index(admin.strip())]
            group = await asyncio.to_thread(
                create_group,
                services,
                owner,
                name=name,
                admin_id=admin_id,
                member_ids=[i for i in created if i != admin_id],
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
            "section": name,
        }
        try:
            await asyncio.to_thread(
                section_action, services, owner, "create", name, created, [group.group_id]
            )
        except OctopError as exc:
            # The team exists either way; only filing it in the sidebar failed.
            result.update({"requested_section": name, "section_error": exc.code.value})
        await asyncio.to_thread(note_onboarding_team, group.group_id, created, name, first_task)
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
