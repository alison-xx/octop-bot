"""Release checks for the Octop Bot web/NAS build.

The Bot web build ships as a container image (``ghcr.io/alison-xx/octop-bot:nas-<version>``)
and as fnOS packages. It must never self-upgrade from PyPI: the ``octop`` package
there is the upstream product. Instead it reads the same signed manifest every
Octop Bot client reads (``docs/octop-bot-updates.md``) and tells the owner which
version is out and how to move to it.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
import urllib.request
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from octop.i18n import tr
from octop.infra.setup.self_update import get_local_version, is_newer, is_prerelease

logger = logging.getLogger(__name__)

MANIFEST_URL = "https://dl.lynxce.cn/releases/octop-bot/manifest.json"
# Public half of the release signing key (scripts/octop_bot_manifest.py).
PUBLIC_KEY = b"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAjfzS5kpiVxqx/79rU5tYno7Js31ezDt05RmrmXnRTa0=
-----END PUBLIC KEY-----
"""
NAS_IMAGE = "ghcr.io/alison-xx/octop-bot"
CACHE_SECONDS = 6 * 60 * 60
_USER_AGENT = {"User-Agent": "octop-bot-web-update-check/1"}

_cache: tuple[float, BotRelease | None, str | None] | None = None


@dataclass(frozen=True)
class BotRelease:
    """The newest Bot web release on the channel this server follows."""

    version: str
    image: str
    notes_zh: str
    notes_en: str
    notes_url: str | None


def verify_manifest(data: bytes, signature: str, public_pem: bytes | None = None) -> dict[str, Any]:
    """Return the manifest when the detached Ed25519 signature matches, else raise ``ValueError``."""
    key = load_pem_public_key(public_pem or PUBLIC_KEY)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("release key is not Ed25519")
    try:
        key.verify(base64.b64decode(signature.strip()), data)
    except Exception as exc:  # noqa: BLE001 - any failure means the manifest is not ours
        raise ValueError("update manifest signature is invalid") from exc
    manifest: Any = json.loads(data)
    if not isinstance(manifest, dict) or manifest.get("product") != "octop-bot":
        raise ValueError("update manifest has an unexpected shape")
    return manifest


def latest_release(manifest: dict[str, Any], *, stable_only: bool) -> BotRelease | None:
    """The highest release with a NAS image on the followed channels."""
    channels = manifest.get("channels") or {}
    names = ["stable"] if stable_only else ["stable", "beta"]
    best: BotRelease | None = None
    for name in names:
        entry = channels.get(name)
        if not isinstance(entry, dict) or not isinstance(entry.get("version"), str):
            continue
        version = entry["version"]
        nas_raw, notes_raw = entry.get("nas"), entry.get("notes")
        nas: dict[str, Any] = nas_raw if isinstance(nas_raw, dict) else {}
        notes: dict[str, Any] = notes_raw if isinstance(notes_raw, dict) else {}
        candidate = BotRelease(
            version=version,
            image=str(nas.get("image") or f"{NAS_IMAGE}:nas-{version}"),
            notes_zh=str(notes.get("zh") or ""),
            notes_en=str(notes.get("en") or ""),
            notes_url=entry.get("notes_url") if isinstance(entry.get("notes_url"), str) else None,
        )
        if best is None or is_newer(candidate.version, best.version):
            best = candidate
    return best


def _fetch(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(url, headers=_USER_AGENT)
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https URL
        data: bytes = response.read()
        return data


def fetch_latest(
    *, stable_only: bool, refresh: bool = False, timeout: int = 10
) -> tuple[BotRelease | None, str | None]:
    """Latest release and an error message, cached for a few hours."""
    global _cache
    now = time.monotonic()
    if not refresh and _cache is not None and now - _cache[0] < CACHE_SECONDS:
        return _cache[1], _cache[2]
    try:
        manifest = verify_manifest(
            _fetch(MANIFEST_URL, timeout), _fetch(MANIFEST_URL + ".sig", timeout).decode()
        )
        result: tuple[BotRelease | None, str | None] = (
            latest_release(manifest, stable_only=stable_only),
            None,
        )
    except Exception as exc:  # noqa: BLE001 - offline or bad manifest: report, never raise
        logger.info("Octop Bot update check failed: %s", exc)
        result = (None, str(exc) or type(exc).__name__)
    _cache = (now, *result)
    return result


def upgrade_steps(release: BotRelease, locale: str) -> list[str]:
    """How the owner moves to ``release``: fnOS app center, or pulling the new image."""
    steps = [tr("update.bot_web.step_fnos", locale)]
    steps.append(tr("update.bot_web.step_docker", locale, image=release.image))
    return steps


def bot_web_status(*, stable_only: bool, locale: str, refresh: bool = False) -> dict[str, Any]:
    """Update status for the Bot web build, in the same shape as the PyPI status payload."""
    current = get_local_version()
    release, error = fetch_latest(stable_only=stable_only, refresh=refresh)
    has_update = bool(release and is_newer(release.version, current))
    zh = locale.startswith("zh")
    notes = None
    if release and has_update:
        notes = (
            (release.notes_zh if zh else release.notes_en)
            or release.notes_zh
            or release.notes_en
            or None
        )
    return {
        "current_version": current,
        "latest_version": release.version if release else None,
        "latest_any": release.version if release else None,
        "latest_stable": release.version
        if release and not is_prerelease(release.version)
        else None,
        "description": None,
        "has_update": has_update,
        "is_editable": False,
        "service_mode": os.environ.get("OCTOP_SERVICE_MODE") or None,
        "desktop": False,
        "updates_managed_by_image": True,
        "upgrade_image": release.image if release else None,
        "upgrade_steps": upgrade_steps(release, locale) if release and has_update else [],
        "error": tr("update.bot_web.check_failed", locale) if error else None,
        "error_code": "bot_manifest_unreachable" if error else None,
        "source": "dl.lynxce.cn" if release else None,
        "last_check_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "release_notes": notes,
        "stable_only": stable_only,
        "latest_is_prerelease": bool(release and is_prerelease(release.version)),
    }
