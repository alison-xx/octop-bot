"""New-user onboarding: pick an industry, Chief builds bots and a group, post in the group.

The state belongs to the Octop user, so every client of one server (web, desktop on the
cloud, phones) guides an owner once. Accounts that already have a bot or a group skip it.
"""

from __future__ import annotations

import json
import time
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field, ValidationError

from octop.i18n import tr
from octop.infra.agents.bot_workspace import chief_key
from octop.infra.utils.locale import resolve_user_locale

if TYPE_CHECKING:
    from octop.infra.db.repos.settings import SettingsRepo
    from octop.infra.db.services import SharedServices

Status = Literal["pending", "active", "done", "skipped"]
Step = Literal["welcome", "ask", "team_ready", "first_message"]
Action = Literal["start", "step", "skip", "complete", "restart"]
Reason = Literal["existing", "legacy"]
Kind = Literal["industry", "role"]


class OnboardingTeam(BaseModel):
    group_id: str
    bot_ids: list[str] = Field(default_factory=list)
    section: str | None = None
    first_task: str = ""


class OnboardingChoice(BaseModel):
    """What the owner picked on the first screen: a listed option or their own words."""

    kind: Kind = "industry"
    id: str | None = None
    label: str
    note: str = ""


class Option(BaseModel):
    id: str
    name: str
    hint: str = Field(default="", description="What it covers, for Chief and tooltips.")


class Options(BaseModel):
    industries: list[Option]
    roles: list[Option]


# The industries most owners pick, in display order: Bot market categories plus two the
# market does not have yet (``octop_bot.onboarding_industries.*``).
ONBOARDING_INDUSTRIES = (
    "ecommerce",
    "trade",
    "store",
    "content",
    "marketing",
    "sales",
    "education",
    "legal",
    "finance",
    "hr",
)
EXTRA_INDUSTRIES = ("trade", "store")
# Same shape as the Bot market's roles.json (onboarding = order on this screen); replaced by
# the market's own file once it ships.
ROLES_FILE = Path(__file__).with_name("onboarding_roles.json")


@lru_cache(maxsize=1)
def _roles() -> list[dict[str, Any]]:
    rows = json.loads(ROLES_FILE.read_text(encoding="utf-8"))
    return sorted((r for r in rows if r.get("onboarding")), key=lambda r: r["onboarding"])


def onboarding_options(locale: str) -> Options:
    """The first screen's two lists, in the owner's language."""
    from octop.infra.agents.bot_market.catalog import load_catalog, pick_locale

    lang = pick_locale(locale)
    catalog = load_catalog()
    categories = {c.id: c for c in catalog.categories}
    industries = []
    for key in ONBOARDING_INDUSTRIES:
        if key in EXTRA_INDUSTRIES:
            name = tr(f"octop_bot.onboarding_industries.{key}.name", lang)
            hint = tr(f"octop_bot.onboarding_industries.{key}.roles", lang).replace("|", ", ")
        elif key in categories:
            name = categories[key].name.get(lang)
            hint = ", ".join(t.name.get(lang) for t in catalog.templates if t.category == key)
        else:
            continue
        industries.append(Option(id=key, name=name, hint=hint))
    roles = [Option(id=r["id"], name=r["name"][lang], hint=r["blurb"][lang]) for r in _roles()]
    return Options(industries=industries, roles=roles)


class Onboarding(BaseModel):
    status: Status
    step: Step = "welcome"
    choice: OnboardingChoice | None = None
    team: OnboardingTeam | None = None
    reason: Reason | None = None
    updated_at: int = 0

    @property
    def show(self) -> bool:
        return self.status in ("pending", "active")


def onboarding_key(user_id: int) -> str:
    return f"octop_bot:onboarding:{user_id}"


def _load(raw: str | None) -> Onboarding | None:
    if not raw:
        return None
    try:
        return Onboarding.model_validate_json(raw)
    except ValidationError:
        return None


def _save(settings: SettingsRepo, user_id: int, state: Onboarding) -> Onboarding:
    state = state.model_copy(update={"updated_at": int(time.time())})
    settings.set(onboarding_key(user_id), state.model_dump_json())
    return state


def read_onboarding(services: SharedServices, user_id: int) -> Onboarding | None:
    return _load(services.settings_repo.get(onboarding_key(user_id)))


def open_onboarding(services: SharedServices, user_id: int, chief_id: str) -> Onboarding:
    """The owner's onboarding; the first call decides whether they are new."""
    current = read_onboarding(services, user_id)
    if current is not None:
        return current
    has_bots = any(
        row.kind != "team" and row.agent_id != chief_id
        for row in services.agent_repo.list_by_user(user_id)
    )
    has_groups = bool(services.repos.bot_group_repo.list_by_owner(user_id))
    first = (
        Onboarding(status="done", reason="existing")
        if has_bots or has_groups
        else Onboarding(status="pending")
    )
    first = first.model_copy(update={"updated_at": int(time.time())})
    # Two tabs opening at once must agree on one answer.
    claimed = services.settings_repo.get_or_insert(onboarding_key(user_id), first.model_dump_json())
    return _load(claimed) or first


def apply_action(
    services: SharedServices,
    user_id: int,
    chief_id: str,
    action: Action,
    *,
    step: Step | None = None,
    reason: Reason | None = None,
    kind: Kind = "industry",
    option: str | None = None,
    custom: str | None = None,
    note: str | None = None,
) -> Onboarding:
    """Move the owner's onboarding along. An action that does not fit returns it unchanged."""
    current = open_onboarding(services, user_id, chief_id)
    settings = services.settings_repo
    if action == "restart":
        return _save(settings, user_id, Onboarding(status="active", step="welcome"))
    if action == "skip":
        if not current.show:
            return current
        return _save(
            settings, user_id, current.model_copy(update={"status": "skipped", "reason": reason})
        )
    if action == "complete":
        if current.status != "active":
            return current
        return _save(settings, user_id, current.model_copy(update={"status": "done"}))
    if action == "start":
        if not current.show:
            return current
        choice = _choice(services, user_id, kind, option, custom, note) or current.choice
        return _save(
            settings,
            user_id,
            current.model_copy(
                update={
                    "status": "active",
                    "step": "team_ready" if current.team else "ask",
                    "choice": choice,
                }
            ),
        )
    # action == "step": the client may only go back to asking or on to the group.
    if current.status != "active" or step not in ("ask", "first_message"):
        return current
    if step == "first_message" and current.team is None:
        return current
    return _save(settings, user_id, current.model_copy(update={"step": step}))


def _choice(
    services: SharedServices,
    user_id: int,
    kind: Kind,
    option: str | None,
    custom: str | None,
    note: str | None,
) -> OnboardingChoice | None:
    """A listed option by id, else the owner's own words; anything else is no choice."""
    extra = (note or "").strip()
    if option:
        listed = _listed(services, user_id, kind)
        match = next((o for o in listed if o.id == option), None)
        if match is None:
            return None
        return OnboardingChoice(kind=kind, id=match.id, label=match.name, note=extra)
    own = (custom or "").strip()
    return OnboardingChoice(kind=kind, label=own, note=extra) if own else None


def _listed(services: SharedServices, user_id: int, kind: Kind) -> list[Option]:
    locale = resolve_user_locale(user_repo=services.user_repo, user_id=user_id)
    options = onboarding_options(locale)
    return options.industries if kind == "industry" else options.roles


def record_team(services: SharedServices, user_id: int, team: OnboardingTeam) -> None:
    """Chief built the team the onboarding asked for: point the owner at it."""
    current = read_onboarding(services, user_id)
    if current is None or current.status != "active" or current.step not in ("welcome", "ask"):
        return
    _save(
        services.settings_repo,
        user_id,
        current.model_copy(update={"step": "team_ready", "team": team}),
    )


def onboarding_briefing(services: SharedServices, user_id: int, agent_id: str) -> str | None:
    """Extra instructions for Chief while the owner is asking for their first team."""
    if services.settings_repo.get(chief_key(user_id)) != agent_id:
        return None
    current = read_onboarding(services, user_id)
    if current is None or current.status != "active" or current.step not in ("welcome", "ask"):
        return None
    locale = resolve_user_locale(user_repo=services.user_repo, user_id=user_id)
    parts = [tr("octop_bot.onboarding_briefing", locale)]
    choice = current.choice
    if choice is not None:
        parts.append(tr(f"octop_bot.onboarding_choice.{choice.kind}", locale, label=choice.label))
        if choice.note:
            parts.append(tr("octop_bot.onboarding_note", locale, note=choice.note))
        hint = next(
            (o.hint for o in _listed(services, user_id, choice.kind) if o.id == choice.id), ""
        )
        if hint:
            parts.append(tr(f"octop_bot.onboarding_hint.{choice.kind}", locale, hint=hint))
    return "\n".join(parts)
