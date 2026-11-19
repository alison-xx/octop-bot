"""Octop Bot workspace. Agent and conversation identity stay with the platform."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from octop.i18n import tr
from octop.infra.agents.bot_appearance import appearance_prefix, bot_appearance
from octop.infra.agents.experts.avatar import display_agent_icon_url
from octop.infra.agents.settings.profile import parse_config_json
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.locale import resolve_user_locale
from octop.infra.utils.ulid import new_short_id

if TYPE_CHECKING:
    from octop.infra.agents.manager import AgentManager
    from octop.infra.db.repos.agents import AgentRow
    from octop.infra.db.repos.settings import SettingsRepo
    from octop.infra.db.services import RepoBundle, SharedServices


def chief_key(user_id: int) -> str:
    return f"octop_bot:chief:{user_id}"


def is_private_bot(row: AgentRow | None) -> bool:
    raw = getattr(row, "config_json", None)
    settings = parse_config_json(raw if isinstance(raw, str) else None).get("octop_bot")
    return isinstance(settings, dict) and settings.get("private") is True


def can_join_bot_group(row: AgentRow) -> bool:
    return row.kind in {"expert", "managed"} and not row.is_shared and not is_private_bot(row)


def assert_removable_bot(repos: RepoBundle, row: AgentRow) -> None:
    if row.user_id is None or row.kind == "team":
        return
    if repos.settings_repo.get(chief_key(row.user_id)) == row.agent_id:
        raise OctopError.localized(ErrorCode.FORBIDDEN)
    from octop.infra.bot_groups.service import Group

    for record in repos.bot_group_repo.list_by_owner(row.user_id):
        group = Group.from_record(record)
        if row.agent_id in group.member_ids:
            raise OctopError(
                ErrorCode.TEAM_MEMBER_INVALID,
                "remove bot from group first",
                status=409,
                details={"group_id": group.group_id},
            )


def bot_card(
    row: AgentRow, chief_id: str, settings: SettingsRepo, cached: dict[str, str] | None = None
) -> dict[str, Any]:
    avatar = bot_appearance(settings, row, chief_id, cached)
    return {
        "agent_id": row.agent_id,
        "name": row.name,
        "description": row.description,
        "avatar": avatar.model_dump(),
        "color": row.color,
        "icon_name": row.icon_name,
        "icon_url": display_agent_icon_url(
            agent_id=row.agent_id, stored=row.icon_url, updated_at=row.updated_at
        )
        if avatar.source == "photo"
        else None,
        "kind": row.kind,
        "is_main": row.agent_id == chief_id,
        "is_private": is_private_bot(row),
        "can_join_group": can_join_bot_group(row),
        "enabled": bool(row.enabled),
        "default_model": row.default_model,
    }


def list_bot_cards(
    services: SharedServices, owner: int, chief_id: str, *, include_private: bool = True
) -> list[dict[str, Any]]:
    cached = services.settings_repo.with_prefix(appearance_prefix(owner))
    return [
        bot_card(row, chief_id, services.settings_repo, cached)
        for row in services.agent_repo.list_by_user(owner)
        if row.kind != "team" and (include_private or not is_private_bot(row))
    ]


async def ensure_chief(services: SharedServices, registry: AgentManager, user_id: int) -> str:
    from octop.infra.agents.manager import AgentCreateSpec

    key = chief_key(user_id)
    chief_id = await asyncio.to_thread(services.settings_repo.get, key)
    if not chief_id:
        chief_id = await asyncio.to_thread(
            services.settings_repo.get_or_insert, key, new_short_id(16)
        )
    existing = await asyncio.to_thread(services.agent_repo.get, chief_id)
    if existing is None:
        rows = await asyncio.to_thread(services.agent_repo.list_by_user, user_id)
        names = {row.name for row in rows}
        name = "Chief"
        index = 1
        while name in names:
            index += 1
            name = f"Chief ({index})"
        locale = resolve_user_locale(user_repo=services.user_repo, user_id=user_id)
        try:
            existing = await registry.create(
                AgentCreateSpec(
                    name=name,
                    agent_id=chief_id,
                    user_id=user_id,
                    icon_name="compass",
                    description=tr("octop_bot.chief_description", locale),
                    system_prompt=tr("octop_bot.chief_prompt", locale),
                    welcome_message=tr("octop_bot.chief_welcome", locale),
                ),
                defer_bootstrap=True,
            )
        except OctopError as exc:
            if exc.code not in {ErrorCode.AGENT_ID_TAKEN, ErrorCode.AGENT_NAME_TAKEN}:
                raise
            existing = await asyncio.to_thread(services.agent_repo.get, chief_id)
            if existing is None:
                raise
    if existing.user_id != user_id or existing.kind != "expert":
        raise OctopError(ErrorCode.FORBIDDEN, "invalid chief identity")
    return chief_id
