"""Import a Bot market template into a user's own Bot directory."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from octop.infra.agents.bot_appearance import mark_bot_photo, set_character
from octop.infra.agents.bot_market.catalog import Locale, Template, avatar_path, load_catalog
from octop.infra.agents.bot_workspace import ensure_chief
from octop.infra.agents.experts.avatar import agent_avatar_api_path, write_workspace_avatar
from octop.infra.agents.experts.catalog import apply_workspace_quick_prompts
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.ulid import new_cron_id

if TYPE_CHECKING:
    from octop.infra.agents.manager import AgentManager
    from octop.infra.cron.manager import CronManager
    from octop.infra.db.repos.agents import AgentRow
    from octop.infra.db.services import SharedServices

_HEADINGS = {
    "zh": ("工作守则", "技能", "记忆", "以下内容来自 Bot 市场模板，可以随时修改。"),
    "en": (
        "Working rules",
        "Skills",
        "Memory",
        "Seeded from the Bot market template; edit freely.",
    ),
}


def import_prefix(user_id: int) -> str:
    return f"octop_bot:market:{user_id}:"


def persona(template: Template, locale: Locale) -> str:
    rules, skills, _, _ = _HEADINGS[locale]
    lines = [template.role.get(locale), "", f"## {rules}"]
    lines += [f"- {rule}" for rule in template.instructions.get(locale)]
    if template.skills:
        lines += ["", f"## {skills}"]
        lines += [
            f"- {s.name.get(locale)} (skills/{s.id}/SKILL.md): {s.summary.get(locale)}"
            for s in template.skills
        ]
    return "\n".join(lines)


def skill_file(template: Template, index: int, locale: Locale) -> tuple[str, bytes]:
    skill = template.skills[index]
    text = (
        f"---\nname: {skill.id}\ndescription: {json.dumps(skill.summary.get(locale), ensure_ascii=False)}\n---\n\n"
        f"# {skill.name.get(locale)}\n\n{skill.body.get(locale).strip()}\n"
    )
    return f"skills/{skill.id}/SKILL.md", text.encode()


def memory_file(template: Template, locale: Locale) -> bytes:
    from octop_harness.builtin.templates import iter_md_template_files

    base = dict(iter_md_template_files(locale)).get("MEMORY.md", b"").decode().rstrip()
    _, _, title, note = _HEADINGS[locale]
    facts = "\n".join(f"- {fact}" for fact in template.memories.get(locale))
    head = base or f"# {title}"
    return f"{head}\n\n<!-- {note} -->\n{facts}\n".encode()


def _portrait_bytes(slug: str) -> bytes | None:
    path = avatar_path(slug)
    return path.read_bytes() if path else None


def _available_name(rows: list[AgentRow], wanted: str) -> str:
    taken = {row.name.casefold() for row in rows}
    name, index = wanted, 1
    while name.casefold() in taken:
        index += 1
        name = f"{wanted} {index}"
    return name


@dataclass
class Imported:
    agent_id: str
    name: str
    routines: list[str]
    integrations: list[str]


async def import_template(
    *,
    services: SharedServices,
    registry: AgentManager,
    cron: CronManager | None,
    user_id: int,
    username: str | None,
    slug: str,
    locale: Locale,
    name: str | None = None,
    routine_ids: list[str] | None = None,
) -> Imported:
    """Create a Bot from *slug*: persona, memory, skills, starters, look, portrait, routines.

    ``routine_ids`` picks which of the template's routines to schedule (the suggested ones when None;
    unknown ids are ignored).
    Importing the same template twice gives two Bots; names get a number suffix.
    """
    from octop_harness.middleware.bootstrap import BOOTSTRAPPED_MARKER

    from octop.infra.agents.manager import AgentCreateSpec
    from octop.infra.cron.manager import CronCreateSpec

    template = (await asyncio.to_thread(load_catalog)).get(slug)
    if template is None:
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    chosen = [
        r
        for r in template.routines
        if (r.suggested if routine_ids is None else r.id in routine_ids)
    ]
    if chosen and cron is None:
        raise OctopError(ErrorCode.INTERNAL_ERROR, "scheduler not running")

    # Chief first: a failed Chief create must not leave a half-imported Bot holding the quota.
    chief_id = await ensure_chief(services, registry, user_id)
    rows = await asyncio.to_thread(registry.list_agents, user_id)
    final_name = _available_name(rows, (name or "").strip()[:64] or template.name.get(locale))
    portrait_bytes = await asyncio.to_thread(_portrait_bytes, slug)

    async def seed(_row: Any, workspace: Any) -> None:
        files = [skill_file(template, i, locale) for i in range(len(template.skills))]
        files.append(("MEMORY.md", memory_file(template, locale)))
        semaphore = asyncio.Semaphore(8)

        async def upload(item: tuple[str, bytes]) -> None:
            async with semaphore:
                await workspace.aupload_many([item])

        starters = template.starters
        prompts = [
            {"title": {"zh": zh, "en": en}, "prompt": {"zh": zh, "en": en}}
            for zh, en in zip(starters.zh, starters.en, strict=True)
        ]
        async with asyncio.TaskGroup() as group:
            for item in files:
                group.create_task(upload(item))
            group.create_task(apply_workspace_quick_prompts(workspace, prompts))
            if portrait_bytes:
                group.create_task(write_workspace_avatar(workspace, portrait_bytes))
        # The template is the onboarding: without the marker the harness drops the
        # system prompt and memory and runs the generic first-run interview instead.
        marker = workspace.resolve_path(None, default=BOOTSTRAPPED_MARKER)
        await asyncio.to_thread(workspace.write_text, marker, "", force=True)

    row = await registry.create(
        AgentCreateSpec(
            name=final_name,
            user_id=user_id,
            description=template.tagline.get(locale),
            system_prompt=persona(template, locale),
            welcome_message=template.description.get(locale),
            color=template.look.color,
        ),
        defer_bootstrap=True,
        workspace_initializer=seed,
    )
    await asyncio.to_thread(set_character, services.settings_repo, row, chief_id, template.look)
    if portrait_bytes:
        icon_url = f"{agent_avatar_api_path(row.agent_id)}?market={slug}-{template.version}"
        row = await asyncio.to_thread(registry.set_icon_url, row.agent_id, icon_url)
        await asyncio.to_thread(mark_bot_photo, services.settings_repo, row)

    created: list[str] = []
    for routine in chosen:
        assert cron is not None
        job = await cron.create(
            CronCreateSpec(
                cron_id=new_cron_id(),
                agent_id=row.agent_id,
                user_id=user_id,
                name=routine.name.get(locale),
                trigger=routine.schedule,
                prompt=routine.prompt.get(locale),
                username=username,
                meta={"bot_market": {"slug": slug, "routine": routine.id}},
            )
        )
        created.append(job.cron_id)

    record = {"slug": slug, "version": template.version, "imported_at": int(time.time())}
    await asyncio.to_thread(
        services.settings_repo.set, import_prefix(user_id) + row.agent_id, json.dumps(record)
    )
    return Imported(
        agent_id=row.agent_id,
        name=row.name,
        routines=created,
        integrations=list(template.integrations),
    )


def imported_slugs(services: SharedServices, user_id: int) -> dict[str, list[str]]:
    """slug → my Bot ids still alive that were imported from it."""
    prefix = import_prefix(user_id)
    alive = {row.agent_id for row in services.agent_repo.list_by_user(user_id)}
    out: dict[str, list[str]] = {}
    for key, raw in services.settings_repo.with_prefix(prefix).items():
        agent_id = key[len(prefix) :]
        if agent_id not in alive:
            continue
        try:
            slug = json.loads(raw)["slug"]
        except (ValueError, KeyError, TypeError):
            continue
        out.setdefault(slug, []).append(agent_id)
    return out
