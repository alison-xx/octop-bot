"""Bot market: ready-made Bot templates by industry, bundled with the server.

Each template is one ``templates/<slug>.json`` file holding every zh/en string, plus an
optional ``avatars/<slug>.webp`` portrait. ``categories.json`` lists the industries in
display order. The website exports the same files (``scripts/export_bot_market.py``), so
the market on octop-bot.lynxce.cn and the one inside the app never drift apart.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from octop.infra.agents.bot_appearance import Character
from octop.infra.cron.task_type import CRON_NAME_MAX_LEN, CRON_PROMPT_MAX_LEN
from octop.infra.cron.trigger import build_trigger

ROOT = Path(__file__).resolve().parent
TEMPLATES_DIR = ROOT / "templates"
AVATARS_DIR = ROOT / "avatars"

Locale = Literal["zh", "en"]
SLUG = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


def pick_locale(locale: str | None) -> Locale:
    return "zh" if (locale or "").lower().startswith("zh") else "en"


class Text(BaseModel):
    zh: str = Field(min_length=1)
    en: str = Field(min_length=1)

    def get(self, locale: Locale) -> str:
        return self.zh if locale == "zh" else self.en


class TextList(BaseModel):
    zh: list[str]
    en: list[str]

    @model_validator(mode="after")
    def same_length(self) -> TextList:
        if len(self.zh) != len(self.en) or any(not s.strip() for s in self.zh + self.en):
            raise ValueError("zh and en lists must have the same length and no blank items")
        return self

    def get(self, locale: Locale) -> list[str]:
        return list(self.zh if locale == "zh" else self.en)


class Skill(BaseModel):
    id: str = Field(pattern=SLUG, max_length=48)
    name: Text
    summary: Text = Field(description="When to use it; becomes the SKILL.md description.")
    body: Text = Field(description="Markdown playbook: steps, output format, checks.")


class Routine(BaseModel):
    id: str = Field(pattern=SLUG, max_length=48)
    name: Text
    schedule: str = Field(description="Cron trigger spec, e.g. 'cron:0 9 * * 1-5'.")
    when: Text = Field(description="The schedule in words, e.g. '工作日 9:00'.")
    prompt: Text
    suggested: bool = Field(
        default=True, description="Switched on in the import dialog unless the user turns it off."
    )

    @field_validator("schedule")
    @classmethod
    def valid_schedule(cls, value: str) -> str:
        if not value.startswith(("cron:", "interval:")):
            raise ValueError("routines repeat: use cron: or interval:")
        build_trigger(value)
        return value

    @model_validator(mode="after")
    def fits_cron_limits(self) -> Routine:
        if (
            max(len(self.prompt.zh), len(self.prompt.en)) > CRON_PROMPT_MAX_LEN
            or max(len(self.name.zh), len(self.name.en)) > CRON_NAME_MAX_LEN
        ):
            raise ValueError("routine name or prompt is longer than a cron job allows")
        return self


class Template(BaseModel):
    slug: str = Field(pattern=SLUG, max_length=48)
    version: int = Field(default=1, ge=1)
    category: str = Field(pattern=SLUG)
    featured: bool = False
    name: Text
    tagline: Text = Field(description="One line for cards.")
    description: Text = Field(description="Two or three sentences for the detail page.")
    look: Character = Field(description="SVG character used when the photo is switched off.")
    avatar_subject: str = Field(
        min_length=1, description="English subject for the generated portrait."
    )
    role: Text = Field(description="Who the Bot is, opening its instructions.")
    instructions: TextList = Field(description="Working rules, shown on the detail page.")
    memories: TextList = Field(description="Facts it already knows; seeded into MEMORY.md.")
    skills: list[Skill] = Field(default_factory=list, max_length=4)
    routines: list[Routine] = Field(default_factory=list, max_length=3)
    integrations: list[str] = Field(
        default_factory=list, description="Connector kinds from infra/connectors/catalog.json."
    )
    starters: TextList = Field(description="Conversation starters for the first chat.")

    @model_validator(mode="after")
    def unique_ids(self) -> Template:
        for items in (self.skills, self.routines):
            ids = [item.id for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError("skill and routine ids must be unique")
        return self


class Category(BaseModel):
    id: str = Field(pattern=SLUG)
    name: Text
    blurb: Text


class Catalog(BaseModel):
    categories: list[Category]
    templates: list[Template]
    portraits: frozenset[str] = Field(
        default=frozenset(), description="Slugs that ship a portrait, read once at load."
    )

    def get(self, slug: str) -> Template | None:
        return next((t for t in self.templates if t.slug == slug), None)

    def portrait(self, slug: str) -> Path | None:
        """The portrait file, without touching the disk (see ``portraits``)."""
        return AVATARS_DIR / f"{slug}.webp" if slug in self.portraits else None


def avatar_path(slug: str) -> Path | None:
    path = AVATARS_DIR / f"{slug}.webp"
    return path if path.is_file() else None


@lru_cache(maxsize=1)
def load_catalog() -> Catalog:
    """Read and validate every bundled template once per process.

    Blocking file I/O on the first call: async callers use ``asyncio.to_thread``.
    """
    raw = json.loads((ROOT / "categories.json").read_text(encoding="utf-8"))
    categories = [Category.model_validate(item) for item in raw]
    order = {c.id: i for i, c in enumerate(categories)}
    templates = []
    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        template = Template.model_validate_json(path.read_text(encoding="utf-8"))
        if template.slug != path.stem:
            raise ValueError(f"{path.name}: slug {template.slug!r} must match the file name")
        if template.category not in order:
            raise ValueError(f"{path.name}: unknown category {template.category!r}")
        templates.append(template)
    templates.sort(key=lambda t: (order[t.category], t.slug))
    portraits = frozenset(t.slug for t in templates if avatar_path(t.slug) is not None)
    return Catalog(categories=categories, templates=templates, portraits=portraits)
