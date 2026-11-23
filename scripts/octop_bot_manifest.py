"""Build, sign and promote the Octop Bot update manifest.

Every Octop Bot client reads one signed file to learn about new versions:
``https://dl.lynxce.cn/releases/octop-bot/manifest.json`` and its detached
Ed25519 signature ``manifest.json.sig``. See ``docs/octop-bot-updates.md``.

    # After uploading the packages of 1.0.4b1 to .../octop-bot/1.0.4b1/
    uv run python scripts/octop_bot_manifest.py build \\
        --version 1.0.4b1 --channel beta --dist dist/1.0.4b1 \\
        --previous https://dl.lynxce.cn/releases/octop-bot/manifest.json --out out/

    # Later, move that beta to stable for 20 % of installs, then everyone
    uv run python scripts/octop_bot_manifest.py promote --manifest out/manifest.json --rollout 20 --out out/

    uv run python scripts/octop_bot_manifest.py verify out/manifest.json

The signing key never lives in the repository. By default it is read from
``~/.octop-bot-release/manifest-ed25519.pem``; the matching public key is
built into the clients (``desktop/src/main/update/bot-feed.ts``).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key

DOWNLOAD_ROOT = "https://dl.lynxce.cn/releases/octop-bot"
NOTES_URL = "https://octop-bot.lynxce.cn/download.html"
NAS_IMAGE = "ghcr.io/alison-xx/octop-bot:nas-{version}"
DEFAULT_KEY = Path.home() / ".octop-bot-release" / "manifest-ed25519.pem"
PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAjfzS5kpiVxqx/79rU5tYno7Js31ezDt05RmrmXnRTa0=
-----END PUBLIC KEY-----
"""
CHANNELS = ("stable", "beta")

# Package file name → manifest asset key. First match wins.
ASSET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("win_arm", re.compile(r"(?i)setup.*arm64\.exe$")),
    ("win_x64", re.compile(r"(?i)setup.*(x64|win).*\.exe$")),
    ("mac_arm", re.compile(r"(?i)mac.*arm64\.dmg$")),
    ("mac_intel", re.compile(r"(?i)mac.*(x64|intel)\.dmg$")),
    ("android", re.compile(r"(?i)\.apk$")),
    ("fnos", re.compile(r"(?i)\.fpk$")),
]


def asset_key(name: str) -> str | None:
    """The manifest key for a package file, or ``None`` when it is not a client package."""
    for key, pattern in ASSET_PATTERNS:
        if pattern.search(name):
            return key
    return None


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_assets(dist: Path, base_url: str) -> dict[str, dict[str, Any]]:
    """Describe every client package in ``dist`` (url, sha256, size)."""
    assets: dict[str, dict[str, Any]] = {}
    for path in sorted(p for p in dist.iterdir() if p.is_file()):
        key = asset_key(path.name)
        if key is None:
            continue
        if key in assets:
            raise SystemExit(f"two packages map to {key}: {assets[key]['name']} and {path.name}")
        assets[key] = {
            "name": path.name,
            "url": f"{base_url.rstrip('/')}/{path.name}",
            "sha256": sha256_of(path),
            "size": path.stat().st_size,
        }
    return assets


def changelog_notes(changelog: str, version: str) -> str:
    """The body of ``## [version]`` in CHANGELOG.md, without the heading."""
    pattern = re.compile(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", re.S | re.M)
    match = pattern.search(changelog)
    return match.group(1).strip() if match else ""


def release_entry(
    *,
    version: str,
    assets: dict[str, dict[str, Any]],
    notes_zh: str,
    notes_en: str,
    min_supported: str | None,
    rollout: int,
    ios_url: str | None,
    released: str,
    mobile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "version": version,
        "tag": f"octop-bot-v{version}",
        "date": released,
        "notes": {"zh": notes_zh, "en": notes_en},
        "notes_url": NOTES_URL,
        "rollout": rollout,
        "assets": dict(assets),
        "nas": {"image": NAS_IMAGE.format(version=version)},
    }
    if min_supported:
        entry["min_supported"] = min_supported
    mobile = mobile or {}
    android = entry["assets"].get("android")
    if android is not None:
        # The phone apps have their own version numbers; Android compares version_code.
        if mobile.get("android_version_code") is None:
            raise SystemExit("an APK needs --android-version-code (and --android-version)")
        android["version_code"] = mobile["android_version_code"]
        if mobile.get("android_version"):
            android["version"] = mobile["android_version"]
        if mobile.get("android_min_version_code") is not None:
            android["min_version_code"] = mobile["android_min_version_code"]
    if ios_url:
        ios: dict[str, Any] = {"url": ios_url}
        if not mobile.get("ios_version"):
            raise SystemExit("--ios-url needs --ios-version")
        ios["version"] = mobile["ios_version"]
        if mobile.get("ios_min_version"):
            ios["min_version"] = mobile["ios_min_version"]
        entry["assets"]["ios"] = ios
    return entry


def encode(manifest: dict[str, Any]) -> bytes:
    """Stable bytes: the signature covers exactly what is uploaded."""
    return (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def sign(data: bytes, key: Ed25519PrivateKey) -> str:
    return base64.b64encode(key.sign(data)).decode() + "\n"


def verify(data: bytes, signature: str, public_pem: str | None = None) -> bool:
    key = load_pem_public_key((public_pem or PUBLIC_KEY).encode())
    if not isinstance(key, Ed25519PublicKey):
        raise SystemExit("public key is not Ed25519")
    try:
        key.verify(base64.b64decode(signature.strip()), data)
    except Exception:  # noqa: BLE001 - any failure means "not signed by us"
        return False
    return True


def load_key(path: Path) -> Ed25519PrivateKey:
    key = load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit(f"{path} is not an Ed25519 private key")
    return key


def read_source(source: str) -> bytes:
    if source.startswith("https://"):
        with urllib.request.urlopen(source, timeout=30) as response:  # noqa: S310 - fixed https source
            data: bytes = response.read()
            return data
    return Path(source).read_bytes()


def load_previous(source: str | None) -> dict[str, Any]:
    """The live manifest, checked against our key, so the other channel is kept as it is."""
    empty: dict[str, Any] = {"schema": 1, "product": "octop-bot", "channels": {}}
    if not source:
        return empty
    data = read_source(source)
    signature = read_source(source + ".sig").decode()
    if not verify(data, signature):
        raise SystemExit(f"{source} is not signed by the Octop Bot release key")
    previous: dict[str, Any] = json.loads(data)
    return previous


def write(manifest: dict[str, Any], out: Path, key: Ed25519PrivateKey) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    data = encode(manifest)
    target = out / "manifest.json"
    target.write_bytes(data)
    (out / "manifest.json.sig").write_text(sign(data, key))
    return target


def cmd_build(args: argparse.Namespace) -> None:
    dist = Path(args.dist)
    assets = collect_assets(dist, args.base_url or f"{DOWNLOAD_ROOT}/{args.version}")
    if not assets and not args.ios_url:
        raise SystemExit(f"no client packages found in {dist}")
    changelog = (
        Path(args.changelog).read_text(encoding="utf-8") if Path(args.changelog).exists() else ""
    )
    notes_zh = args.notes_zh or changelog_notes(changelog, args.version)
    manifest = load_previous(args.previous)
    manifest.setdefault("channels", {})[args.channel] = release_entry(
        version=args.version,
        assets=assets,
        notes_zh=notes_zh,
        notes_en=args.notes_en or "",
        min_supported=args.min_supported,
        rollout=args.rollout,
        ios_url=args.ios_url,
        mobile={
            "android_version": args.android_version,
            "android_version_code": args.android_version_code,
            "android_min_version_code": args.android_min_version_code,
            "ios_version": args.ios_version,
            "ios_min_version": args.ios_min_version,
        },
        released=args.date or date.today().isoformat(),
    )
    target = write(manifest, Path(args.out), load_key(Path(args.key)))
    print(
        f"wrote {target} ({args.channel} {args.version}; {', '.join(sorted(assets)) or 'no packages'})"
    )


def cmd_promote(args: argparse.Namespace) -> None:
    data = read_source(args.manifest)
    if not verify(data, read_source(args.manifest + ".sig").decode()):
        raise SystemExit(f"{args.manifest} is not signed by the Octop Bot release key")
    manifest = json.loads(data)
    beta = manifest.get("channels", {}).get("beta")
    if not beta:
        raise SystemExit("the manifest has no beta release to promote")
    manifest["channels"]["stable"] = {**beta, "rollout": args.rollout}
    target = write(manifest, Path(args.out), load_key(Path(args.key)))
    print(f"wrote {target} (stable {beta['version']} at {args.rollout}%)")


def cmd_verify(args: argparse.Namespace) -> None:
    data = read_source(args.manifest)
    ok = verify(data, read_source(args.manifest + ".sig").decode())
    print("signature ok" if ok else "signature INVALID")
    if not ok:
        raise SystemExit(1)
    manifest = json.loads(data)
    for channel in CHANNELS:
        entry = manifest.get("channels", {}).get(channel)
        if entry:
            print(
                f"{channel}: {entry['version']} rollout {entry.get('rollout', 100)}% assets {', '.join(sorted(entry['assets']))}"
            )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="put a release on a channel")
    build.add_argument("--version", required=True, help="product version, e.g. 1.0.4b1")
    build.add_argument("--channel", choices=CHANNELS, default="beta")
    build.add_argument("--dist", required=True, help="folder with the uploaded packages")
    build.add_argument(
        "--base-url", help=f"where the packages live (default {DOWNLOAD_ROOT}/<version>)"
    )
    build.add_argument(
        "--previous", help="current manifest (path or https URL) to keep the other channel"
    )
    build.add_argument("--changelog", default="CHANGELOG.md")
    build.add_argument("--notes-zh")
    build.add_argument("--notes-en")
    build.add_argument("--min-supported", help="clients older than this are told they must update")
    build.add_argument("--rollout", type=int, default=100, choices=range(0, 101), metavar="0-100")
    build.add_argument("--ios-url", help="App Store or TestFlight link")
    build.add_argument("--ios-version", help="iOS app version (MARKETING_VERSION), e.g. 0.2.0")
    build.add_argument(
        "--ios-min-version", help="iOS versions below this are told they must update"
    )
    build.add_argument("--android-version", help="Android versionName, e.g. 0.2.0")
    build.add_argument("--android-version-code", type=int, help="Android versionCode of the APK")
    build.add_argument(
        "--android-min-version-code", type=int, help="Android versionCodes below this must update"
    )
    build.add_argument("--date")
    build.add_argument("--key", default=str(DEFAULT_KEY))
    build.add_argument("--out", required=True)
    build.set_defaults(run=cmd_build)

    promote = sub.add_parser("promote", help="copy the beta release to stable")
    promote.add_argument("--manifest", required=True)
    promote.add_argument("--rollout", type=int, default=100, choices=range(0, 101), metavar="0-100")
    promote.add_argument("--key", default=str(DEFAULT_KEY))
    promote.add_argument("--out", required=True)
    promote.set_defaults(run=cmd_promote)

    check = sub.add_parser("verify", help="check a manifest's signature")
    check.add_argument("manifest")
    check.set_defaults(run=cmd_verify)

    args = parser.parse_args(argv)
    args.run(args)


if __name__ == "__main__":
    main(sys.argv[1:])
