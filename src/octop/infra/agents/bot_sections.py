"""The owner's sidebar layout, shared by the dashboard and Chief's organization tools."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from octop.infra.agents.bot_workspace import chief_key, is_private_bot
from octop.infra.db.services import SharedServices
from octop.infra.errors import ErrorCode, OctopError

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
SectionName = Annotated[str, StringConstraints(strip_whitespace=True, max_length=160)]
SectionAction = Literal["list", "create", "move", "dissolve"]


class Section(BaseModel):
    name: ShortText
    items: list[ShortText] = Field(default_factory=list, max_length=1000)
    collapsed: bool = False
    color: Literal["blue", "orange", "green", "purple", "pink"] | None = None


class Layout(BaseModel):
    sections: list[Section] = Field(default_factory=list, max_length=100)
    pinned: list[ShortText] = Field(default_factory=list, max_length=1000)
    revision: int = Field(default=0, ge=0, description="Version of this owner's sidebar layout.")


def _key(owner: int) -> str:
    return f"octop_bot:layout:{owner}"


def read_layout(services: SharedServices, owner: int) -> Layout:
    raw = services.settings_repo.get(_key(owner))
    return Layout.model_validate_json(raw) if raw else Layout()


def visible_layout(layout: Layout, keys: set[str]) -> Layout:
    """Ignore legacy dangling entries and keep the Chief fixed above all sections."""
    seen: set[str] = set()
    sections = []
    for section in layout.sections:
        items = [item for item in dict.fromkeys(section.items) if item in keys and item not in seen]
        seen.update(items)
        sections.append(section.model_copy(update={"items": items}))
    return Layout(
        sections=sections,
        pinned=[item for item in dict.fromkeys(layout.pinned) if item in keys],
        revision=layout.revision,
    )


def _available_keys(services: SharedServices, owner: int, *, include_private: bool) -> set[str]:
    chief = services.settings_repo.get(chief_key(owner))
    return {
        f"bot:{row.agent_id}"
        for row in services.agent_repo.list_by_user(owner)
        if row.agent_id != chief
        and row.kind != "team"
        and (include_private or not is_private_bot(row))
    } | {f"group:{row['group_id']}" for row in services.repos.bot_group_repo.list_by_owner(owner)}


def _change(
    services: SharedServices,
    owner: int,
    edit: Callable[[Layout], Layout],
    expected: int | None = None,
) -> tuple[Layout, bool]:
    settings = services.settings_repo
    key = _key(owner)
    raw = settings.get(key)
    if raw is None:
        raw = settings.get_or_insert(key, Layout().model_dump_json())
    while True:
        current = Layout.model_validate_json(raw)
        if expected is not None and current.revision != expected:
            raise OctopError.localized(ErrorCode.BOT_LAYOUT_CHANGED)
        updated = edit(current)
        if updated == current:
            return current, False
        updated.revision = current.revision + 1
        if settings.replace_if_current(key, raw, updated.model_dump_json()):
            return updated, True
        raw = settings.get(key)
        if raw is None:
            raise OctopError.localized(ErrorCode.BOT_LAYOUT_CHANGED)


def save_layout(services: SharedServices, owner: int, layout: Layout) -> Layout:
    def replace(current: Layout) -> Layout:
        keys = _available_keys(services, owner, include_private=True)
        proposed = layout.model_copy(update={"revision": current.revision})
        entries = [key for section in proposed.sections for key in section.items]
        if not keys.issuperset([*proposed.pinned, *entries]):
            raise OctopError.localized(ErrorCode.NOT_FOUND)
        if len({s.name for s in proposed.sections}) != len(proposed.sections):
            raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS)
        if len(set(entries)) != len(entries) or len(set(proposed.pinned)) != len(proposed.pinned):
            raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS)
        return proposed

    # A legacy client has no read version. Still reject an edit racing its PUT rather than
    # replaying a whole, stale snapshot after a failed compare-and-swap.
    expected = (
        layout.revision
        if "revision" in layout.model_fields_set
        else read_layout(services, owner).revision
    )
    return _change(services, owner, replace, expected)[0]


def section_action(
    services: SharedServices,
    owner: int,
    action: SectionAction,
    section: str = "",
    bot_ids: Iterable[str] = (),
    group_ids: Iterable[str] = (),
) -> tuple[Layout, bool]:
    name = section.strip()
    targets = list(
        dict.fromkeys([*(f"bot:{i}" for i in bot_ids), *(f"group:{i}" for i in group_ids)])
    )
    if (
        len(name) > 160
        or (not name and action in {"create", "dissolve"})
        or (action == "move" and not targets)
        or (action in {"list", "dissolve"} and targets)
        or (action == "list" and name)
    ):
        raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS)
    if action == "list":
        return visible_layout(
            read_layout(services, owner), _available_keys(services, owner, include_private=False)
        ), False

    def edit(current: Layout) -> Layout:
        if targets and not _available_keys(services, owner, include_private=False).issuperset(
            targets
        ):
            raise OctopError.localized(ErrorCode.NOT_FOUND)
        sections = [s.model_copy(deep=True) for s in current.sections]
        target = next((s for s in sections if s.name == name), None)
        if action == "dissolve":
            sections = [s for s in sections if s.name != name]
        else:
            if name and target is None:
                if action == "move":
                    raise OctopError.localized(ErrorCode.NOT_FOUND)
                if len(sections) >= 100:
                    raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS)
                target = Section(name=name)
                sections.append(target)
            keys = set(targets)
            for s in sections:
                if s is not target:
                    s.items = [item for item in s.items if item not in keys]
            if target is not None:
                existing = set(target.items)
                target.items.extend(item for item in targets if item not in existing)
                if len(target.items) > 1000:
                    raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS)
        return current.model_copy(update={"sections": sections})

    result, changed = _change(services, owner, edit)
    return visible_layout(result, _available_keys(services, owner, include_private=False)), changed
