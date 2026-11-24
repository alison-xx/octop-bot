"""Octop Bot cloud: agent web fetches reach public addresses only.

octop-harness decides which addresses an agent fetch (``web_fetch``) may reach with
``octop_harness.security.ssrf._ip_is_blocked``, which looks at private, loopback, link-local
and reserved ranges. On a cloud server every address that is not globally routable is
refused (shared address space too); an IPv4-mapped IPv6 address counts as its IPv4 address.
``tests/unit/cloud/test_fetch_guard.py`` fails if a harness upgrade renames the hook.
"""

from __future__ import annotations

from octop.infra.utils.ssrf_guard import is_public_ip


def _blocked(ip_str: str) -> bool:
    return not is_public_ip(ip_str)


def install() -> None:
    """Make agent fetches public-only (cloud mode; idempotent)."""
    from octop_harness.security import ssrf  # noqa: PLC0415

    ssrf._ip_is_blocked = _blocked
