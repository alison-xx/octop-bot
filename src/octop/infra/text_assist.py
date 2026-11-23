"""One-shot LLM text assist (polish / generate) for dashboard forms and chat."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal, get_args

from octop.i18n import tr
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.llm_text import strip_thinking
from octop.infra.utils.locale import Locale, normalize_locale

logger = logging.getLogger(__name__)

AssistKind = Literal[
    "chat.prompt",
    "chat.thread_title",
    "expert.description",
    "expert.welcome_message",
    "team.description",
    "team.welcome_message",
    "skill_package.description",
    "skill.description",
    "skill.label_zh",
    "skill.label_en",
    "skill.summary_zh",
    "skill.summary_en",
    "skill.body",
    "knowledge_base.description",
    "connector.description",
    "bridge.notes",
    "user_group.description",
    "user_role.description",
]

ASSIST_KINDS: frozenset[str] = frozenset(get_args(AssistKind))
_TEXT_KINDS: frozenset[str] = frozenset({"chat.prompt", "chat.thread_title"})
_FORM_KINDS: frozenset[str] = ASSIST_KINDS - _TEXT_KINDS
_TIMEOUT_SECONDS = 30.0


def server_agent_registry(server: Any) -> Any:
    """The server's agent registry, or ``None`` while the runtime is down."""
    return getattr(getattr(server, "app_runtime", None), "agent_registry", None)


@asynccontextmanager
async def assist_models(
    registry: Any, user_id: int, default_model: str | None = None
) -> AsyncIterator[tuple[Any, str | None]]:
    """The models and model ref a one-shot assist call for ``user_id`` runs on.

    A cloud tenant (``OCTOP_BOT_CLOUD``, non-admin) never reaches the operator's shared
    providers: the call uses the tenant's own Lynxce key and chat model, billed to their
    wallet, whatever ``default_model`` asks for. Everyone else gets the host models.
    Raises when the runtime (``registry``) is down.
    """
    from octop.infra.desktop import bot_cloud_enabled  # noqa: PLC0415

    tenant = (
        await asyncio.to_thread(registry.cloud_tenant_model, user_id)
        if registry is not None and bot_cloud_enabled()
        else None
    )
    if tenant is None:
        models = getattr(registry, "host_models", None)
        if models is None:
            raise OctopError(ErrorCode.INTERNAL_ERROR, "runtime unavailable")
        yield models, default_model
        return
    from octop.infra.agents.providers import HostModelFactory  # noqa: PLC0415

    provider, model_ref = tenant
    factory = HostModelFactory()
    factory.sync([provider])
    try:
        yield factory, model_ref
    finally:
        factory.close()


def _context_name(context: dict[str, Any] | None) -> str:
    if not context:
        return ""
    raw = context.get("name")
    if raw is None:
        return ""
    return str(raw).strip()


def _prompt_pair(
    *,
    kind: str,
    text: str,
    name: str,
    locale: Locale,
) -> tuple[str, str]:
    system = tr(f"text_assist.kinds.{kind}.system", locale)
    if kind in _TEXT_KINDS:
        user = tr(f"text_assist.kinds.{kind}.user", locale, text=text)
    elif text:
        user = tr(
            f"text_assist.kinds.{kind}.user_polish",
            locale,
            name=name,
            text=text,
        )
    else:
        user = tr(f"text_assist.kinds.{kind}.user_generate", locale, name=name)
    return system, user


async def run_text_assist(
    *,
    models: Any,
    kind: str,
    text: str = "",
    context: dict[str, Any] | None = None,
    locale: str | Locale = "en",
    default_model: str | None = None,
) -> str:
    """Polish or generate short copy for a known assist kind.

    ``chat.prompt`` and ``chat.thread_title`` require non-empty ``text``.
    Form kinds require ``context.name``; ``text`` may be empty to generate
    from the name.
    ``default_model`` is forwarded to harness: omit it or pass ``auto`` and
    ``ChatModelFactory.get_for`` selects the model.
    """
    if kind not in ASSIST_KINDS:
        raise OctopError(ErrorCode.SLASH_BAD_ARGS, f"unknown assist kind: {kind}")

    draft = (text or "").strip()
    name = _context_name(context)
    loc = normalize_locale(str(locale))

    if kind in _TEXT_KINDS:
        if not draft:
            raise OctopError(ErrorCode.SLASH_BAD_ARGS, "text is required")
    elif kind in _FORM_KINDS:
        if not name:
            raise OctopError(ErrorCode.SLASH_BAD_ARGS, "context.name is required")
    else:
        raise OctopError(ErrorCode.SLASH_BAD_ARGS, f"unknown assist kind: {kind}")

    access = models.get(default_model)
    system, user = _prompt_pair(kind=kind, text=draft, name=name, locale=loc)
    model_ref = getattr(access, "model_ref", "")
    try:
        result = await asyncio.wait_for(
            access.ainvoke_text(user, system=system, timeout_s=_TIMEOUT_SECONDS),
            timeout=_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        raise OctopError(ErrorCode.INTERNAL_ERROR, "text assist timed out") from None
    except Exception:
        logger.exception("text assist failed kind=%s model=%s", kind, model_ref)
        raise OctopError(ErrorCode.INTERNAL_ERROR, "text assist failed") from None

    polished = strip_thinking(result or "").strip()
    if not polished:
        raise OctopError(ErrorCode.INTERNAL_ERROR, "model returned empty text assist result")
    return polished


__all__ = [
    "ASSIST_KINDS",
    "AssistKind",
    "assist_models",
    "run_text_assist",
    "server_agent_registry",
]
