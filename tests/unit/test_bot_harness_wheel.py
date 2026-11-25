"""Regression coverage for the desktop sidecar's offline wheel install."""

import importlib
import sys
import zipfile
from importlib.metadata import distributions
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "desktop/src/scripts"


def test_offline_install_has_no_local_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.syspath_prepend(str(SCRIPTS))
    harness = importlib.import_module("bot_harness_wheel")
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "empty cache"))
    target = tmp_path / "portable sidecar" / "packages"

    harness.install_harness("uv", Path(sys.executable), target=target)

    (installed,) = distributions(path=[str(target)])
    assert installed.metadata["Name"] == "octop-harness"
    assert installed.version == harness.VERSION
    assert installed.read_text("direct_url.json") is None
    with zipfile.ZipFile(harness.WHEEL) as archive:
        files = [
            p for p in archive.namelist() if p.startswith("octop_harness/") and not p.endswith("/")
        ]
        assert files
        for path in files:
            assert (target / path).read_bytes() == archive.read(path), path


def test_wrong_wheel_digest_stops_before_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.syspath_prepend(str(SCRIPTS))
    harness = importlib.import_module("bot_harness_wheel")
    wheel = tmp_path / harness.WHEEL.name
    wheel.write_bytes(b"not the pinned artifact")
    monkeypatch.setattr(harness, "WHEEL", wheel)
    target = tmp_path / "packages"

    with pytest.raises(ValueError, match="digest mismatch"):
        harness.install_harness("uv", Path(sys.executable), target=target)
    assert not target.exists()
