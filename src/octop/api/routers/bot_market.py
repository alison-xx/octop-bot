"""Bot market: browse ready-made Bot templates and import one into my directory."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from octop.api.deps import current_user, get_server
from octop.infra.agents.bot_appearance import Character
from octop.infra.agents.bot_market.catalog import (
    Locale,
    Template,
    avatar_path,
    load_catalog,
    pick_locale,
)
from octop.infra.agents.bot_market.install import import_template, imported_slugs
from octop.infra.connectors.catalog import get_catalog_entry
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.server import OctopServer
from octop.infra.users.identity import User
from octop.infra.utils.locale import resolve_request_locale

# GET /api/octop-bot/market… is public (static catalog); importing needs a session.
router = APIRouter()
Owner = Annotated[User, Depends(current_user)]
Server = Annotated[OctopServer, Depends(get_server)]
LocaleParam = Annotated[
    str | None, Query(description="zh or en; defaults to the request's Accept-Language.")
]


class MarketCategory(BaseModel):
    id: str
    name: str
    blurb: str
    count: int


class MarketCard(BaseModel):
    slug: str
    category: str
    featured: bool
    name: str
    tagline: str
    look: Character = Field(description="SVG character shape and colour.")
    avatar: str | None = Field(description="Portrait URL, or null to draw the character.")


class MarketSkill(BaseModel):
    id: str
    name: str
    summary: str


class MarketRoutine(BaseModel):
    id: str
    name: str
    when: str = Field(description="The schedule in words, server timezone.")
    prompt: str
    suggested: bool = Field(description="On by default in the import dialog.")


class MarketIntegration(BaseModel):
    kind: str = Field(description="Connector kind; connect it under Capabilities → Connectors.")
    name: str
    color: str | None = None


class MarketDetail(MarketCard):
    version: int
    description: str
    role: str
    instructions: list[str]
    memories: list[str]
    skills: list[MarketSkill]
    routines: list[MarketRoutine]
    integrations: list[MarketIntegration]
    starters: list[str]


class Market(BaseModel):
    categories: list[MarketCategory]
    templates: list[MarketCard]


class ImportBody(BaseModel):
    slug: str
    name: str | None = Field(
        default=None, max_length=64, description="Defaults to the template name."
    )
    routines: list[str] | None = Field(
        default=None,
        description="Routine ids to schedule; null schedules the suggested ones, [] none.",
    )


class ImportResult(BaseModel):
    agent_id: str
    name: str
    routines: list[str] = Field(description="Created cron job ids.")
    integrations: list[str] = Field(description="Suggested connector kinds to connect next.")


class MyImports(BaseModel):
    imports: dict[str, list[str]] = Field(description="Template slug → my Bot ids made from it.")


def _locale(request: Request, locale: str | None) -> Locale:
    return pick_locale(locale or resolve_request_locale(request))


def _avatar(t: Template) -> str | None:
    if avatar_path(t.slug) is None:
        return None
    return f"/api/octop-bot/market/{t.slug}/avatar?v={t.version}"


def _card(t: Template, loc: Locale) -> MarketCard:
    return MarketCard(
        slug=t.slug,
        category=t.category,
        featured=t.featured,
        name=t.name.get(loc),
        tagline=t.tagline.get(loc),
        look=t.look,
        avatar=_avatar(t),
    )


def _integration(kind: str, loc: Locale) -> MarketIntegration:
    entry = get_catalog_entry(kind)
    if entry is None:
        return MarketIntegration(kind=kind, name=kind)
    return MarketIntegration(kind=kind, name=getattr(entry.name, loc), color=entry.color)


def _template(slug: str) -> Template:
    template = load_catalog().get(slug)
    if template is None:
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    return template


@router.get(
    "/market",
    summary="List Bot market categories and templates",
    response_model=Market,
    description="Public. Templates come in category order; `featured` marks the curated row.",
)
async def market(request: Request, locale: LocaleParam = None) -> Market:
    loc = _locale(request, locale)
    catalog = load_catalog()
    counts: dict[str, int] = {}
    for t in catalog.templates:
        counts[t.category] = counts.get(t.category, 0) + 1
    return Market(
        categories=[
            MarketCategory(
                id=c.id, name=c.name.get(loc), blurb=c.blurb.get(loc), count=counts.get(c.id, 0)
            )
            for c in catalog.categories
        ],
        templates=[_card(t, loc) for t in catalog.templates],
    )


@router.get(
    "/market/{slug}",
    summary="Get one Bot market template",
    response_model=MarketDetail,
    description="Public. Everything the import will set up: rules, memory, skills, routines, connectors.",
)
async def market_detail(slug: str, request: Request, locale: LocaleParam = None) -> MarketDetail:
    t = _template(slug)
    loc = _locale(request, locale)
    return MarketDetail(
        **_card(t, loc).model_dump(),
        version=t.version,
        description=t.description.get(loc),
        role=t.role.get(loc),
        instructions=t.instructions.get(loc),
        memories=t.memories.get(loc),
        skills=[
            MarketSkill(id=s.id, name=s.name.get(loc), summary=s.summary.get(loc)) for s in t.skills
        ],
        routines=[
            MarketRoutine(
                id=r.id,
                name=r.name.get(loc),
                when=r.when.get(loc),
                prompt=r.prompt.get(loc),
                suggested=r.suggested,
            )
            for r in t.routines
        ],
        integrations=[_integration(kind, loc) for kind in t.integrations],
        starters=t.starters.get(loc),
    )


@router.get(
    "/market/{slug}/avatar",
    summary="Get a Bot market template portrait",
    response_class=FileResponse,
    description="Public 512px WebP. 404 when the template draws its SVG character instead.",
)
async def market_avatar(slug: str) -> FileResponse:
    path = avatar_path(_template(slug).slug)
    if path is None:
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    return FileResponse(
        path, media_type="image/webp", headers={"Cache-Control": "public, max-age=86400"}
    )


@router.get(
    "/market-imports",
    summary="List which templates I already imported",
    response_model=MyImports,
)
async def my_imports(user: Owner, server: Server) -> MyImports:
    services = server.services
    assert services is not None
    return MyImports(imports=await asyncio.to_thread(imported_slugs, services, user.id))


@router.post(
    "/market-imports",
    status_code=201,
    summary="Import a Bot market template as my own Bot",
    response_model=ImportResult,
    description=(
        "Creates a Bot with the template's rules, MEMORY.md facts, skills, conversation starters, "
        "portrait and character, then schedules the chosen routines. Importing again makes another "
        "Bot; a taken name gets a number."
    ),
)
async def import_bot(body: ImportBody, request: Request, user: Owner, server: Server) -> Any:
    runtime, services = server.app_runtime, server.services
    assert runtime is not None and services is not None
    result = await import_template(
        services=services,
        registry=runtime.agent_registry,
        cron=runtime.cron_manager,
        user_id=user.id,
        username=user.username,
        slug=_template(body.slug).slug,
        locale=_locale(request, None),
        name=body.name,
        routine_ids=body.routines,
    )
    return ImportResult(**result.__dict__)
