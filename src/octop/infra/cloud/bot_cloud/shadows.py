"""Octop Bot cloud: shadow Bots, so a Bot that lives on someone's desktop can use a cloud computer.

The desktop app (signed in with Lynxce) keeps its Bots, chats and workspaces on the computer it
runs on. Only the Bot's *computer* is in the cloud: for each desktop Bot that uses one, the
account's tenant here gets a shadow Bot, an ordinary ``agents`` row of kind ``shadow``:

- ``config_json.octop_bot.origin`` = ``<desktop install id>:<desktop agent_id>``, one per origin;
- ``config_json.octop_bot.hidden`` = true; the repo leaves shadows out of every list, so the web,
  the phones and group pickers never show them;
- no agent runtime is ever started for it; it only owns a cloud computer, which the usual
  ``ComputerManager`` starts on use, bills, idles and reaps.

A shadow nobody has used for ``IDLE_DAYS`` (no update from the desktop, no computer use) is
deleted; the computer reaper then stops and settles its computer. See
``docs/octop-bot-accounts.md`` §7.
"""

from __future__ import annotations

import json
import re
import threading
from typing import TYPE_CHECKING, Any

from octop.infra.db.repos.agents import SHADOW, AgentRow
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.ulid import new_short_id

if TYPE_CHECKING:
    from octop.infra.db.services import SharedServices

# ``<install id>:<agent id>``: the install id is a ULID, the agent id a desktop agent id.
ORIGIN = re.compile(r"[0-9A-Za-z]{10,40}:[A-Za-z0-9_-]{1,64}")
IDLE_DAYS = 30
# Shadows one account may have: well above any real desktop, so a client stuck in a loop (or
# abuse) cannot fill the table.
MAX_SHADOWS = 200
MAX_NAME = 64
MAX_AVATAR = 2048

# Two desktop calls for the same new origin must not make two shadows.
_lock = threading.Lock()


def valid_origin(origin: str) -> bool:
    return ORIGIN.fullmatch(origin) is not None


def _octop_bot(row: AgentRow) -> dict[str, Any]:
    try:
        data = json.loads(row.config_json or "{}")
    except ValueError:
        return {}
    section = data.get("octop_bot") if isinstance(data, dict) else None
    return section if isinstance(section, dict) else {}


def origin_of(row: AgentRow) -> str | None:
    value = _octop_bot(row).get("origin")
    return value if row.kind == SHADOW and isinstance(value, str) else None


def find_shadow(services: SharedServices, user_id: int, origin: str) -> AgentRow | None:
    for row in services.agent_repo.list_shadows(user_id):
        if origin_of(row) == origin:
            return row
    return None


def is_shadow(row: AgentRow | None) -> bool:
    return row is not None and row.kind == SHADOW


def put_shadow(
    services: SharedServices,
    user_id: int,
    origin: str,
    *,
    name: str,
    avatar: str | None,
) -> tuple[AgentRow, bool]:
    """The shadow for ``origin`` (created if new, its name and avatar updated). Also counts as a
    use, which keeps it from being reaped. Returns the row and whether it was created."""
    config = json.dumps(
        {
            "octop_bot": {
                "origin": origin,
                "hidden": True,
                "name": name[:MAX_NAME],
                "avatar": (avatar or "")[:MAX_AVATAR] or None,
            }
        },
        ensure_ascii=False,
    )
    repo = services.agent_repo
    with _lock:
        existing = find_shadow(services, user_id, origin)
        if existing is not None:
            repo.update_config(existing.agent_id, config_json=config)
            repo.touch(existing.agent_id)
            row = repo.get(existing.agent_id)
            assert row is not None
            return row, False
        if len(repo.list_shadows(user_id)) >= MAX_SHADOWS:
            raise OctopError.localized(ErrorCode.BOT_REMOTE_BOT_LIMIT, limit=MAX_SHADOWS)
        agent_id = new_short_id(16)
        while repo.get(agent_id) is not None:
            agent_id = new_short_id(16)
        # The row name only has to be unique for the user; the shown name is in the config.
        repo.create(
            agent_id=agent_id,
            user_id=user_id,
            name=f"shadow:{origin}",
            config_json=config,
            kind=SHADOW,
        )
        repo.set_enabled(agent_id, False)
        row = repo.get(agent_id)
        assert row is not None
        return row, True


def delete_shadow(services: SharedServices, user_id: int, origin: str) -> bool:
    """Delete the shadow for ``origin``; its computer is stopped and settled by the reaper."""
    with _lock:
        row = find_shadow(services, user_id, origin)
        if row is None:
            return False
        services.agent_repo.delete(row.agent_id)
        return True


def idle_shadows(services: SharedServices, last_computer_use: Any, now: float) -> list[AgentRow]:
    """Shadows unused for ``IDLE_DAYS``: no update from the desktop and no computer use.

    ``last_computer_use(row)`` is the last time its computer was used or watched (0 if never).
    """
    cutoff = now - IDLE_DAYS * 86400
    return [
        row
        for row in services.agent_repo.list_shadows()
        if max(float(row.updated_at or 0), float(last_computer_use(row) or 0)) < cutoff
    ]
