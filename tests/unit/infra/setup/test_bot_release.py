"""tests/unit/infra/setup/test_bot_release.py"""

from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from octop.infra.setup import bot_release, self_update

MANIFEST = {
    "schema": 1,
    "product": "octop-bot",
    "channels": {
        "stable": {
            "version": "1.0.3",
            "notes": {"zh": "稳定版", "en": "Stable"},
            "nas": {"image": "ghcr.io/alison-xx/octop-bot:nas-1.0.3"},
            "assets": {},
        },
        "beta": {"version": "1.0.4b1", "notes": {"zh": "测试版"}, "assets": {}},
    },
}


@pytest.fixture
def signer() -> tuple[Ed25519PrivateKey, bytes]:
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return key, public


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bot_release, "_cache", None)


def _signed(key: Ed25519PrivateKey, manifest: dict[str, object]) -> tuple[bytes, str]:
    data = json.dumps(manifest).encode()
    return data, base64.b64encode(key.sign(data)).decode()


def test_verify_manifest_rejects_other_keys_and_edits(
    signer: tuple[Ed25519PrivateKey, bytes],
) -> None:
    key, public = signer
    data, signature = _signed(key, MANIFEST)
    assert bot_release.verify_manifest(data, signature, public)["product"] == "octop-bot"
    with pytest.raises(ValueError):
        bot_release.verify_manifest(data + b" ", signature, public)
    with pytest.raises(ValueError):
        bot_release.verify_manifest(data, signature)  # the real key did not sign this
    other, other_sig = _signed(key, {**MANIFEST, "product": "octop"})
    with pytest.raises(ValueError):
        bot_release.verify_manifest(other, other_sig, public)


def test_latest_release_follows_the_channel() -> None:
    stable = bot_release.latest_release(MANIFEST, stable_only=True)
    assert stable is not None and stable.version == "1.0.3"
    assert stable.image == "ghcr.io/alison-xx/octop-bot:nas-1.0.3"
    beta = bot_release.latest_release(MANIFEST, stable_only=False)
    assert beta is not None and beta.version == "1.0.4b1"
    assert beta.image == "ghcr.io/alison-xx/octop-bot:nas-1.0.4b1"


def test_status_reports_image_and_steps(
    monkeypatch: pytest.MonkeyPatch, signer: tuple[Ed25519PrivateKey, bytes]
) -> None:
    key, public = signer
    data, signature = _signed(key, MANIFEST)
    monkeypatch.setattr(bot_release, "PUBLIC_KEY", public)
    fetched: list[str] = []

    def fake_fetch(url: str, timeout: int) -> bytes:
        fetched.append(url)
        return signature.encode() if url.endswith(".sig") else data

    monkeypatch.setattr(bot_release, "_fetch", fake_fetch)
    monkeypatch.setattr(bot_release, "get_local_version", lambda: "1.0.3b8")
    status = bot_release.bot_web_status(stable_only=True, locale="zh")
    assert status["has_update"] is True
    assert status["latest_version"] == "1.0.3"
    assert status["updates_managed_by_image"] is True
    assert status["upgrade_image"] == "ghcr.io/alison-xx/octop-bot:nas-1.0.3"
    assert status["release_notes"] == "稳定版"
    assert any(
        "docker pull ghcr.io/alison-xx/octop-bot:nas-1.0.3" in step
        for step in status["upgrade_steps"]
    )
    assert status["error"] is None
    # Cached: a second status does not hit the network; refresh does.
    bot_release.bot_web_status(stable_only=True, locale="en")
    assert len(fetched) == 2
    bot_release.bot_web_status(stable_only=True, locale="en", refresh=True)
    assert len(fetched) == 4


def test_status_survives_an_unreachable_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    def offline(url: str, timeout: int) -> bytes:
        raise OSError("offline")

    monkeypatch.setattr(bot_release, "_fetch", offline)
    monkeypatch.setattr(bot_release, "get_local_version", lambda: "1.0.3b8")
    status = bot_release.bot_web_status(stable_only=True, locale="en")
    assert status["has_update"] is False
    assert status["error_code"] == "bot_manifest_unreachable"
    assert status["upgrade_steps"] == []


def test_bot_web_never_self_upgrades_from_pypi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OCTOP_DESKTOP_SHELL", raising=False)
    monkeypatch.setenv("OCTOP_BOT_WEB", "1")

    def must_not_run(*_: object, **__: object) -> None:
        raise AssertionError("PyPI must not be touched")

    monkeypatch.setattr(self_update, "validate_upgrade_target", must_not_run)
    result = self_update.run_upgrade(locale="zh")
    assert result.success is False
    assert result.error and "PyPI" in result.error
