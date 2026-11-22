"""Stable Octop Bot characters, with role presets and owner-selected appearances."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, field_validator

from octop.infra.errors import ErrorCode, OctopError

if TYPE_CHECKING:
    from octop.infra.db.repos.agents import AgentRow
    from octop.infra.db.repos.settings import SettingsRepo

Shape = Literal[
    "octop",
    "whale",
    "star",
    "moon",
    "wave",
    "squircle",
    "zed",
    "hex",
    "gumdrop",
    "peanut",
    "saucer",
    "bunny",
    "kitty",
    "beacon",
    "plus",
    "magnet",
    "acorn",
    "pebbles",
    "cushion",
    "ring",
    "gem",
]
_DEFAULT_SHAPES: tuple[Shape, ...] = (
    "star",
    "moon",
    "gumdrop",
    "peanut",
    "bunny",
    "kitty",
    "acorn",
)
_DEFAULT_COLORS = ("red", "orange", "yellow", "green", "cyan", "blue", "violet", "magenta")
_COLORS = {
    "black",
    "brown",
    "gray",
    "aurora",
    "deepseek",
    "charcoal",
    "graphite",
    "rose",
    "sky",
    "tangerine",
    "cobalt",
    *_DEFAULT_COLORS,
}


class Character(BaseModel):
    shape: Shape
    color: str

    @field_validator("color")
    @classmethod
    def valid_color(cls, value: str) -> str:
        if value not in _COLORS and not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError("Choose a palette color or a six-digit hex color.")
        return value.lower()


class Appearance(Character):
    source: Literal["character", "photo"]


class _Preference(BaseModel):
    original: Character
    selected: Character | None = None
    source: Literal["auto", "character", "photo"] = "auto"


_CHIEF_LOOK = Character(shape="octop", color="rose")
_ROLE_LOOKS = (
    (("选题", "策划", "制片", "planner", "strategist"), Character(shape="star", color="yellow")),
    (
        ("文案", "写作", "撰稿", "编辑", "writer", "editor", "copywriter"),
        Character(shape="moon", color="violet"),
    ),
    (("视觉", "美术", "设计", "design", "illustrat"), Character(shape="gem", color="magenta")),
    (("数据", "分析", "运营", "analytics", "analyst"), Character(shape="hex", color="cyan")),
    # Later roles only apply when none of the four studio roles above matched.
    (("调研", "研究", "research"), Character(shape="acorn", color="green")),
    (
        ("工程", "开发", "程序", "代码", "engineer", "developer", "coder"),
        Character(shape="beacon", color="cobalt"),
    ),
    (("客服", "支持", "support", "service"), Character(shape="bunny", color="tangerine")),
    (("翻译", "译者", "translat"), Character(shape="wave", color="sky")),
    (("测试", "质检", "tester", "qa"), Character(shape="magnet", color="red")),
    (("法务", "律师", "合规", "legal", "lawyer"), Character(shape="cushion", color="graphite")),
    (("财务", "会计", "finance", "account"), Character(shape="pebbles", color="orange")),
    (("销售", "市场", "营销", "sales", "marketing"), Character(shape="kitty", color="red")),
)


def _default_character(row: AgentRow, chief_id: str) -> Character:
    if row.agent_id == chief_id:
        return _CHIEF_LOOK
    name = row.name.casefold()
    for names, role in _ROLE_LOOKS:
        if any(term in name for term in names):
            return role
    # DS Bot characters.js (Apache-2.0). Match its unsigned 32-bit arithmetic.
    seed = 2166136261
    for char in row.agent_id:  # Octop public agent IDs are ASCII.
        seed = ((seed ^ ord(char)) * 16777619) & 0xFFFFFFFF
    value = ((seed ^ (seed >> 16)) * 73244475) & 0xFFFFFFFF
    value = ((value ^ (value >> 13)) * 3266489909) & 0xFFFFFFFF
    shape = _DEFAULT_SHAPES[(value ^ (value >> 16)) % len(_DEFAULT_SHAPES)]
    t = (seed + 1831565813) & 0xFFFFFFFF
    n = ((t ^ (t >> 15)) * (1 | t)) & 0xFFFFFFFF
    n = ((n + (n ^ (n >> 7)) * (61 | n)) ^ n) & 0xFFFFFFFF
    color = _DEFAULT_COLORS[((n ^ (n >> 14)) * len(_DEFAULT_COLORS)) >> 32]
    return Character(shape=shape, color=color)


def appearance_prefix(owner: int) -> str:
    return f"octop_bot:appearance:{owner}:"


def _preference(
    settings: SettingsRepo, row: AgentRow, chief_id: str, cached: dict[str, str] | None = None
) -> tuple[str, _Preference]:
    if row.user_id is None:
        raise OctopError.localized(ErrorCode.FORBIDDEN)
    key = appearance_prefix(row.user_id) + row.agent_id
    raw = cached.get(key) if cached is not None else settings.get(key)
    if raw is None:
        original = _default_character(row, chief_id)
        if (
            original.shape != "octop"
            and row.color
            and (row.color in _COLORS or re.fullmatch(r"#[0-9a-fA-F]{6}", row.color))
        ):
            original = Character(shape=original.shape, color=row.color)
        raw = settings.get_or_insert(key, _Preference(original=original).model_dump_json())
    pref = _Preference.model_validate_json(raw)
    # Existing workspaces stored the former Chief default. Explicit choices live in selected.
    if row.agent_id == chief_id and pref.original.shape == "whale":
        pref.original = _CHIEF_LOOK
    return key, pref


def bot_appearance(
    settings: SettingsRepo, row: AgentRow, chief_id: str, cached: dict[str, str] | None = None
) -> Appearance:
    _, pref = _preference(settings, row, chief_id, cached)
    look = pref.selected or pref.original
    photo = bool(row.icon_url and pref.source != "character")
    return Appearance(shape=look.shape, color=look.color, source="photo" if photo else "character")


def set_character(
    settings: SettingsRepo, row: AgentRow, chief_id: str, selected: Character | None
) -> Appearance:
    key, pref = _preference(settings, row, chief_id)
    pref.source = "character"
    pref.selected = selected
    settings.set(key, pref.model_dump_json())
    look = selected or pref.original
    return Appearance(shape=look.shape, color=look.color, source="character")


def mark_bot_photo(settings: SettingsRepo, row: AgentRow) -> None:
    if row.user_id is None:
        return
    key = appearance_prefix(row.user_id) + row.agent_id
    raw = settings.get(key)
    if raw:
        pref = _Preference.model_validate_json(raw)
        pref.source = "photo"
        settings.set(key, pref.model_dump_json())
