"""Agent startup errors visible to cloud tenants."""

import logging
from functools import lru_cache

from octop.i18n import tr
from octop.i18n.domains.agents import agent_error_message, is_classified_agent_error
from octop.infra.desktop import bot_cloud_enabled

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1024)
def _log_unclassified(agent_id: str, error: str) -> None:
    logger.warning("Unclassified agent startup error for %s: %s", agent_id, error)


def visible_agent_error(
    agent_id: str, error: str | None, *, is_admin: bool, locale: str
) -> str | None:
    """Preserve raw errors except when displaying them to a cloud tenant."""
    if not error or is_admin or not bot_cloud_enabled():
        return error
    if is_classified_agent_error(error, locale):
        return agent_error_message(error, locale)
    _log_unclassified(agent_id, error)
    return tr("agent_errors.generic_start_failure", locale)
