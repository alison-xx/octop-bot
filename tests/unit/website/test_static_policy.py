"""The website keeps the rules its sign-in depends on (security review of #73).

Signed-in sessions live in the browser, so the site loads scripts only from itself: no third-party
scripts, no inline scripts and no inline event handlers. film-src/ is the promo film's source and is
never deployed, so it is skipped.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WEBSITE = Path(__file__).resolve().parents[3] / "website"
PAGES = sorted(p for p in WEBSITE.rglob("*.html") if "film-src" not in p.relative_to(WEBSITE).parts)

SCRIPT_TAG = re.compile(r"<script\b([^>]*)>", re.IGNORECASE)
SRC = re.compile(r"\bsrc\s*=\s*[\"']([^\"']*)[\"']", re.IGNORECASE)
EVENT_ATTR = re.compile(r"<[a-z][^>]*\son[a-z]+\s*=", re.IGNORECASE)
JS_URL = re.compile(r"\b(?:href|src)\s*=\s*[\"']\s*javascript:", re.IGNORECASE)


def test_pages_found() -> None:
    assert len(PAGES) >= 10


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.relative_to(WEBSITE).as_posix())
def test_scripts_are_local_files(page: Path) -> None:
    html = page.read_text(encoding="utf-8")
    for attrs in SCRIPT_TAG.findall(html):
        if re.search(r"type\s*=\s*[\"']application/(ld\+)?json[\"']", attrs, re.IGNORECASE):
            continue
        src = SRC.search(attrs)
        assert src, f"inline <script> in {page.name}"
        url = src.group(1)
        assert not re.match(r"^(https?:)?//", url, re.IGNORECASE), (
            f"third-party script {url} in {page.name}"
        )
        assert not url.lower().startswith(("data:", "javascript:")), f"{url} in {page.name}"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.relative_to(WEBSITE).as_posix())
def test_no_javascript_urls(page: Path) -> None:
    html = page.read_text(encoding="utf-8")
    assert not JS_URL.search(html), f"javascript: URL in {page.name}"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.relative_to(WEBSITE).as_posix())
def test_no_inline_event_handlers(page: Path) -> None:
    assert not EVENT_ATTR.search(page.read_text(encoding="utf-8")), f"on*= handler in {page.name}"
