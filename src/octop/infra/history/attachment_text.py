"""Recognize model-facing attachment placeholders in projected conversation text."""

from __future__ import annotations

import json
import re
from typing import Any

# Matches the lightweight placeholder that ``MediaOffloadMiddleware`` writes
# into LangGraph state for already-offloaded inline images / audio. Format
# (see octop_harness.middleware.media_offload._placeholder_text_block):
#   [<btype> offloaded: sha=<short_sha> path=<path> size=<n>B mime=<m>;
#   use read_file to retrieve bytes]
# We strip these on history serialization because the original bytes are
# still available via ``inbound_attachments`` and the dashboard renders the
# thumbnail from there — leaving the placeholder visible made the chat show
# a "[image offloaded: sha=… path=…]" line under every user image after the
# second turn (when the middleware first re-encountered the block).
OFFLOAD_PLACEHOLDER_RE = re.compile(
    r"^\s*\[\s*(?:image|audio)\s+offloaded\s*:",
    re.IGNORECASE,
)


def is_history_noise_image_block(block: Any) -> bool:
    """True for vision blocks that must not appear as user-authored history text."""
    if not isinstance(block, dict):
        return False
    if str(block.get("type") or "").lower() != "image_url":
        return False
    if str(block.get("workspace_path") or "").strip():
        return True
    url_field = block.get("image_url")
    url = ""
    if isinstance(url_field, dict):
        url = str(url_field.get("url") or "")
    elif isinstance(url_field, str):
        url = url_field
    return url.startswith("data:") or url.startswith("workspace://")


def _parse_image_ref_json_text(text: str) -> dict[str, Any] | None:
    """Return an ``image_url`` dict when *text* is a dumped vision ref (UI noise)."""
    stripped = text.strip()
    if not stripped.startswith("{") or "image_url" not in stripped:
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict) and is_history_noise_image_block(parsed):
        return parsed
    return None


def extract_dumped_image_refs_from_text(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Pull harness JSONL-style vision dumps out of user text.

    ``MemoryMiddleware._stringify_content`` joins text blocks and
    ``json.dumps(image_url_block)`` with newlines. Session-log history
    therefore arrives as one string like::

        这图是啥
        {"type": "image_url", "workspace_path": "inbound/…", …}

    Returns ``(cleaned_caption, image_ref_dicts)``.
    """
    if not text or "image_url" not in text:
        return text, []
    refs: list[dict[str, Any]] = []
    kept: list[str] = []
    for part in text.split("\n"):
        parsed = _parse_image_ref_json_text(part)
        if parsed is not None:
            refs.append(parsed)
            continue
        kept.append(part)
    if not refs:
        return text, []
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    return cleaned, refs
