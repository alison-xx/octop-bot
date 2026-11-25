"""Desktop shell ownership for the Octop Python sidecar.

The Electron shell marks the Python process it owns with
``OCTOP_DESKTOP_SHELL=1``.  This flag is authoritative for "this process is the
desktop-hosted sidecar" and is intentionally distinct from ``OCTOP_DESKTOP`` /
``OCTOP_GREEN_PACKAGES``: a standalone green portable install may set those
without being shell-owned, and it must keep its self-upgrade ability.

``octop.config`` must stay free of ``infra`` imports (AGENTS.md §5), so this
module lives in ``octop.infra`` and is only imported by ``infra`` / ``cli`` /
``api`` code paths that are allowed to depend on it.
"""

from __future__ import annotations

import os
import re

from octop.infra.errors import ErrorCode, OctopError

_DESKTOP_SHELL_ENV = "OCTOP_DESKTOP_SHELL"

# Shell-owned keys that the ``~/.octop/env`` file and ``/api/envs`` must never
# override: they control process identity, bind address, and update ownership.
SHELL_OWNED_ENV_KEYS = frozenset(
    {
        "OCTOP_DESKTOP_SHELL",
        "OCTOP_DESKTOP_PRODUCT",
        "OCTOP_BOT_CLOUD_ORIGIN",
        "OCTOP_DASHBOARD_DEV",
        "OCTOP_DESKTOP",
        "OCTOP_GREEN_PACKAGES",
        "OCTOP_BIND_HOST",
        "OCTOP_PORT",
        "OCTOP_HOME",
        "PYTHONNOUSERSITE",
    }
)

# Product decisions the desktop shell makes on the user's behalf.  They stay
# ordinary user-settable variables everywhere else (``docs/configuration.md``),
# but a persisted env file must not flip them back while the shell runs: a
# settings-page write would otherwise resurrect the sign-in wall the desktop
# build deliberately removed.
SHELL_POLICY_ENV_KEYS = frozenset(
    {
        "OCTOP_REQUIRE_SETUP_PASSWORD",
    }
)


def desktop_shell_enabled() -> bool:
    """Return true when this process is the desktop-hosted sidecar."""
    raw = (os.environ.get(_DESKTOP_SHELL_ENV) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def bot_desktop_enabled() -> bool:
    """The standalone Bot client provisions Chief as its first assistant."""
    return desktop_shell_enabled() and os.environ.get("OCTOP_DESKTOP_PRODUCT") == "bot"


def bot_web_enabled() -> bool:
    """The Bot web/NAS build signs its owner in with a Lynxce account.

    Set by the Bot Docker image and the fnOS packages (``OCTOP_BOT_WEB=1``). There is no
    CLI setup password; the first Lynxce sign-in claims the instance.
    """
    raw = (os.environ.get("OCTOP_BOT_WEB") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def bot_cloud_enabled() -> bool:
    """Lynxce-operated multi-tenant Octop Bot (``OCTOP_BOT_CLOUD=1``, e.g. bot.lynxce.cn).

    Anyone with a Lynxce account signs in and gets their own non-admin account. Agents keep
    their files in the shared object store and never touch the host.
    """
    raw = (os.environ.get("OCTOP_BOT_CLOUD") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def bot_cloud_session_login_enabled() -> bool:
    """Cloud accepts a Lynxce refresh token handed over by a desktop (``OCTOP_BOT_SESSION_LOGIN=1``).

    Off by default: desktops no longer move their team to the cloud, and the account plan
    replaces handing over refresh tokens.
    """
    raw = (os.environ.get("OCTOP_BOT_SESSION_LOGIN") or "").strip().lower()
    return bot_cloud_enabled() and raw in {"1", "true", "yes", "on"}


def bot_cloud_move_in_enabled() -> bool:
    """Cloud receives a desktop's Bots, chats, groups and notes (``OCTOP_BOT_MOVE_IN=1``).

    Off by default until request size, totals and rate limits are in place.
    """
    raw = (os.environ.get("OCTOP_BOT_MOVE_IN") or "").strip().lower()
    return bot_cloud_enabled() and raw in {"1", "true", "yes", "on"}


def bot_cloud_origin() -> str:
    """Where the desktop app's Lynxce mode keeps its data (``OCTOP_BOT_CLOUD_ORIGIN`` for tests)."""
    raw = (os.environ.get("OCTOP_BOT_CLOUD_ORIGIN") or "").strip().rstrip("/")
    official = "https://bot.lynxce.cn"
    if not raw or raw == official:
        return official
    # Development Electron owns both settings. Never send credentials to a
    # custom server selected for an ordinary self-hosted workspace.
    loopback = re.fullmatch(r"https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::([0-9]{1,5}))?", raw)
    if (
        os.environ.get("OCTOP_DASHBOARD_DEV") == "1"
        and loopback
        and (loopback[1] is None or 0 < int(loopback[1]) <= 65535)
    ):
        return raw
    raise OctopError.localized(ErrorCode.FORBIDDEN)


def shell_owned_env_key(key: str) -> bool:
    """Return true when ``key`` is pinned by the desktop shell for this process."""
    if key in SHELL_OWNED_ENV_KEYS:
        return True
    return desktop_shell_enabled() and key in SHELL_POLICY_ENV_KEYS
