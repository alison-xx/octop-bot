"""Agent fetches on a cloud server reach public addresses only."""

from __future__ import annotations

import pytest
from octop_harness.security import ssrf

from octop.infra.cloud.bot_cloud import fetch_guard


@pytest.fixture
def guarded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssrf, "_ip_is_blocked", ssrf._ip_is_blocked)
    fetch_guard.install()


@pytest.mark.parametrize(
    "url",
    [
        "http://100.100.100.200/",
        "http://169.254.169.254/",
        "http://172.23.0.1/",
        "http://10.1.2.3/",
        "http://127.0.0.1/",
        "http://0.0.0.0/",
        "http://[::ffff:100.100.100.200]/",
        "http://[::1]/",
    ],
)
def test_non_public_addresses_are_refused(guarded: None, url: str) -> None:
    with pytest.raises(ssrf.UnsafeAgentFetchUrlError):
        ssrf.validate_agent_fetch_url(url)


def test_public_addresses_still_work(guarded: None) -> None:
    assert ssrf.validate_agent_fetch_url("https://8.8.8.8/") == "https://8.8.8.8/"
