"""tests/unit/test_octop_bot_manifest.py"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "octop_bot_manifest.py"


def _load():
    spec = importlib.util.spec_from_file_location("octop_bot_manifest", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _key(tmp_path: Path) -> tuple[Path, str]:
    key = Ed25519PrivateKey.generate()
    path = tmp_path / "key.pem"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return path, public.decode()


def test_asset_keys_follow_package_names() -> None:
    mod = _load()
    assert mod.asset_key("Octop-Bot-Setup-1.0.4b1-x64.exe") == "win_x64"
    assert mod.asset_key("Octop-Bot-Setup-1.0.4b1-arm64.exe") == "win_arm"
    assert mod.asset_key("Octop-Bot-1.0.4b1-mac-arm64.dmg") == "mac_arm"
    assert mod.asset_key("Octop-Bot-1.0.4b1-mac-x64.dmg") == "mac_intel"
    assert mod.asset_key("octop-bot-1.0.4b1.apk") == "android"
    assert mod.asset_key("Octop-Bot-1.0.4b1-x64.zip") is None


def test_changelog_notes_take_one_section() -> None:
    mod = _load()
    text = "## [Unreleased]\n\n- soon\n\n## [1.0.4b1] - 2026-11-24\n\n### 新增\n\n- 自动更新\n\n## [1.0.3b8] - 2026-11-21\n\n- old\n"
    assert mod.changelog_notes(text, "1.0.4b1") == "### 新增\n\n- 自动更新"
    assert mod.changelog_notes(text, "9.9.9") == ""


def test_build_signs_and_keeps_the_other_channel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _load()
    key_path, public = _key(tmp_path)
    monkeypatch.setattr(mod, "PUBLIC_KEY", public)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "Octop-Bot-Setup-1.0.4b1-x64.exe").write_bytes(b"win")
    (dist / "Octop-Bot-1.0.4b1-mac-arm64.dmg").write_bytes(b"mac")
    (dist / "notes.txt").write_text("ignored")
    out = tmp_path / "out"
    common = [
        "--key",
        str(key_path),
        "--out",
        str(out),
        "--changelog",
        str(tmp_path / "missing.md"),
    ]

    mod.main(["build", "--version", "1.0.3", "--channel", "stable", "--dist", str(dist), *common])
    mod.main(
        [
            "build",
            "--version",
            "1.0.4b1",
            "--channel",
            "beta",
            "--dist",
            str(dist),
            "--rollout",
            "30",
            "--previous",
            str(out / "manifest.json"),
            "--min-supported",
            "1.0.3b1",
            *common,
        ]
    )

    data = (out / "manifest.json").read_bytes()
    assert mod.verify(data, (out / "manifest.json.sig").read_text(), public)
    assert not mod.verify(data + b" ", (out / "manifest.json.sig").read_text(), public)
    manifest = json.loads(data)
    assert manifest["channels"]["stable"]["version"] == "1.0.3"
    beta = manifest["channels"]["beta"]
    assert beta["version"] == "1.0.4b1"
    assert beta["rollout"] == 30
    assert beta["min_supported"] == "1.0.3b1"
    assert beta["nas"]["image"] == "ghcr.io/alison-xx/octop-bot:nas-1.0.4b1"
    win = beta["assets"]["win_x64"]
    assert (
        win["url"]
        == "https://dl.lynxce.cn/releases/octop-bot/1.0.4b1/Octop-Bot-Setup-1.0.4b1-x64.exe"
    )
    assert win["size"] == 3
    assert len(win["sha256"]) == 64
    assert set(beta["assets"]) == {"win_x64", "mac_arm"}

    mod.main(
        [
            "promote",
            "--manifest",
            str(out / "manifest.json"),
            "--rollout",
            "20",
            "--key",
            str(key_path),
            "--out",
            str(out),
        ]
    )
    promoted = json.loads((out / "manifest.json").read_bytes())
    assert promoted["channels"]["stable"]["version"] == "1.0.4b1"
    assert promoted["channels"]["stable"]["rollout"] == 20


def test_previous_manifest_must_be_ours(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    key_path, public = _key(tmp_path)
    monkeypatch.setattr(mod, "PUBLIC_KEY", public)
    forged = tmp_path / "manifest.json"
    forged.write_text('{"schema": 1, "channels": {}}')
    (tmp_path / "manifest.json.sig").write_text("AAAA")
    with pytest.raises(SystemExit):
        mod.load_previous(str(forged))


def test_mobile_assets_carry_their_own_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _load()
    key_path, public = _key(tmp_path)
    monkeypatch.setattr(mod, "PUBLIC_KEY", public)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "octop-bot-0.2.0.apk").write_bytes(b"apk")
    out = tmp_path / "out"
    base = [
        "build",
        "--version",
        "1.0.4",
        "--dist",
        str(dist),
        "--key",
        str(key_path),
        "--out",
        str(out),
    ]
    base += ["--changelog", str(tmp_path / "missing.md")]
    with pytest.raises(SystemExit):
        mod.main(base)  # an APK without its versionCode is refused
    mod.main(
        [
            *base,
            "--android-version",
            "0.2.0",
            "--android-version-code",
            "2",
            "--android-min-version-code",
            "1",
            "--ios-url",
            "https://apps.apple.com/app/id1",
            "--ios-version",
            "0.2.0",
            "--ios-min-version",
            "0.1.0",
        ]
    )
    assets = json.loads((out / "manifest.json").read_bytes())["channels"]["beta"]["assets"]
    assert assets["android"]["version_code"] == 2
    assert assets["android"]["version"] == "0.2.0"
    assert assets["android"]["min_version_code"] == 1
    assert assets["ios"] == {
        "url": "https://apps.apple.com/app/id1",
        "version": "0.2.0",
        "min_version": "0.1.0",
    }
