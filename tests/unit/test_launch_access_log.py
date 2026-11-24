"""``OCTOP_ACCESS_LOG`` switches uvicorn's per-request access log."""

from __future__ import annotations

import pytest

from octop import launch


@pytest.mark.parametrize(
    ("value", "enabled"),
    [
        (None, True),
        ("", True),
        ("1", True),
        ("on", True),
        ("0", False),
        ("off", False),
        ("OFF ", False),
    ],
)
def test_access_log_switch(
    monkeypatch: pytest.MonkeyPatch, value: str | None, enabled: bool
) -> None:
    if value is None:
        monkeypatch.delenv("OCTOP_ACCESS_LOG", raising=False)
    else:
        monkeypatch.setenv("OCTOP_ACCESS_LOG", value)
    assert launch._access_log() is enabled


def test_every_listener_gets_the_switch() -> None:
    import inspect

    source = inspect.getsource(launch.run_foreground)
    assert source.count("uvicorn.Config(") == source.count("access_log=access_log")
