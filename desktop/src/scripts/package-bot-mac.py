"""Build the signed and notarized arm64 Octop Bot DMG from the checkout and locked dependencies.

On an Apple silicon Mac, install the dashboard's npm lock and desktop/src's pnpm lock, then run
`pnpm run package:bot:mac` in desktop/src. Signing uses the "Developer ID Application" identity
in the keychain (or CSC_LINK / CSC_KEY_PASSWORD). Notarization uses the notarytool keychain
profile from --notary-profile, or APPLE_API_KEY / APPLE_API_KEY_ID / APPLE_API_ISSUER when set.
Use --prepare to cache only CPython and dependencies, --dir for the app without a DMG, and
--unsigned for a local trial build that Gatekeeper will not open.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

from bot_harness_wheel import REQUIREMENT, install_harness

SHELL = Path(__file__).resolve().parents[1]
REPO = SHELL.parent.parent
PORTABLE = REPO / "desktop" / "portable"
PYTHON_VERSION = "3.12.13"
EXTRAS = ("browser", "computer-use", "desktop")
APP_NAME = "Octop Bot.app"


def binary(name: str) -> str:
    value = shutil.which(name)
    if not value:
        raise SystemExit(f"Install {name} to build the desktop client.")
    return value


def run(args: list[str | Path], **kwargs) -> None:
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def prepare_dependencies(stage: Path, uv: str) -> None:
    portable = stage / "portable"
    marker = stage / "dependencies.ready"
    if marker.is_file():
        return
    shutil.rmtree(portable, ignore_errors=True)
    portable.mkdir(parents=True)
    find_python = [uv, "python", "find", "--managed-python", PYTHON_VERSION]
    try:
        source = subprocess.check_output(find_python, text=True, stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        run([uv, "python", "install", PYTHON_VERSION])
        source = subprocess.check_output(find_python, text=True).strip()
    base = Path(source).resolve().parent.parent
    if not (base / "lib" / "python3.12" / "os.py").is_file():
        raise SystemExit(f"A complete uv-managed CPython installation is required: {base}")
    shutil.copytree(
        base,
        portable / "runtime",
        symlinks=True,
        ignore=shutil.ignore_patterns(
            "__pycache__", "site-packages", "*.pyc", "EXTERNALLY-MANAGED"
        ),
    )
    python = portable / "runtime" / "bin" / "python3"
    run(
        [
            python,
            "-I",
            "-c",
            "import pathlib, sys; assert pathlib.Path(sys.base_prefix).resolve() == "
            "pathlib.Path(sys.executable).resolve().parent.parent",
        ]
    )
    reqs = stage / "requirements.txt"
    args = [uv, "export", "--project", REPO, "--frozen", "--no-dev", "--no-emit-project"]
    args.extend(["--no-emit-package", "octop-harness"])
    for extra in EXTRAS:
        args.extend(["--extra", extra])
    run([*args, "-o", reqs], stdout=subprocess.DEVNULL)
    packages = portable / "packages"
    install = [
        uv,
        "pip",
        "install",
        "--no-deps",
        "--require-hashes",
        "--python",
        python,
        "--target",
        packages,
        "--link-mode",
        "copy",
        "-r",
        reqs,
    ]
    offline = subprocess.run([*install, "--offline"], check=False)
    if offline.returncode:
        run([*install, "--default-index", "https://pypi.org/simple"])
    install_harness(uv, python, target=packages)
    run([python, "-I", "-B", PORTABLE / "prune_packages.py", packages])
    reject_homebrew_links(portable)
    marker.touch()


def reject_homebrew_links(portable: Path) -> None:
    bad = []
    for path in portable.rglob("*"):
        if path.suffix not in (".so", ".dylib") or path.is_symlink():
            continue
        links = subprocess.run(["otool", "-L", path], capture_output=True, text=True).stdout
        if re.search(r"/opt/homebrew/|/usr/local/opt/|/opt/local/", links):
            bad.append(str(path))
    if bad:
        raise SystemExit("Native modules link Homebrew or MacPorts libraries:\n" + "\n".join(bad))


def install_wheel(stage: Path, uv: str, version: str) -> None:
    portable = stage / "portable"
    python = portable / "runtime" / "bin" / "python3"
    with tempfile.TemporaryDirectory(dir=stage) as tmp:
        run([uv, "build", "--wheel", "--out-dir", tmp, REPO], cwd=REPO)
        run(
            [
                uv,
                "pip",
                "install",
                "--target",
                portable / "packages",
                "--python",
                python,
                "--reinstall-package",
                "octop",
                "--no-index",
                "--find-links",
                tmp,
                "--no-deps",
                "--link-mode",
                "copy",
                f"octop=={version}",
            ]
        )
    shutil.copy2(PORTABLE / "templates" / "launch.py", portable / "launch.py")
    (portable / "version.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    packages = portable / "packages"
    if not (packages / "octop" / "dashboard" / "index.html").is_file():
        raise SystemExit("The wheel must contain the built dashboard.")
    # Installers write the build interpreter's absolute path into script shebangs.
    # launch.py puts the bundled interpreter first on PATH.
    for script in (packages / "bin").iterdir():
        if not script.is_file() or script.is_symlink():
            continue
        with script.open("rb") as stream:
            line = stream.readline(2048)
            if not (line.startswith(b"#!") and b"python" in line.lower()):
                continue
            body = stream.read()
        script.write_bytes(b"#!/usr/bin/env python3\n" + body)
    for direct in packages.glob("*.dist-info/direct_url.json"):
        provenance = json.loads(direct.read_text(encoding="utf-8"))
        if provenance.get("dir_info", {}).get("editable") or str(
            provenance.get("url", "")
        ).startswith("file:"):
            raise SystemExit(f"Local package source found in {direct}")
    with tempfile.TemporaryDirectory() as work:
        run(
            [python, "-I", "-B", portable / "launch.py", "--version"], cwd=work, env=clean_env(work)
        )


def clean_env(home: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OCTOP_", "PYTHON"))}
    env["OCTOP_HOME"] = home
    return env


def verify_runtime(app: Path, node: str) -> None:
    resources = app / "Contents" / "Resources"
    sidecar = resources / "sidecar"
    if {p.name for p in sidecar.iterdir()} != {"packages", "runtime", "launch.py", "version.json"}:
        raise SystemExit("Unexpected files at the packaged sidecar root.")
    check_metadata = """
import {extractFile} from '@electron/asar';
const metadata = JSON.parse(extractFile(process.argv[1], 'package.json'));
if (metadata.octopBotClient !== true || metadata.productName !== 'Octop Bot' ||
    metadata.name !== 'octop-bot') throw new Error('Incorrect standalone client metadata');
"""
    run([node, "--input-type=module", "-e", check_metadata, resources / "app.asar"], cwd=SHELL)
    check_runtime = """
import importlib, pathlib, runpy, sys
root = pathlib.Path(sys.argv[1]).resolve()
runpy.run_path(str(root/'launch.py'))['_bootstrap']()
for name in ('octop','octop_harness','octop_memory','octop_gateway','octop_browser','cua_driver','PIL','cryptography.hazmat.bindings._rust'):
    origin = pathlib.Path(importlib.import_module(name).__file__).resolve()
    if not origin.is_relative_to(root): raise RuntimeError(f'{name} comes from outside the bundle: {origin}')
from importlib.metadata import version
from octop_harness.backends.workspace import BackendWorkspace
assert version('octop-harness') == '1.0.11+bounded.1'
assert callable(BackendWorkspace.adownload_bytes_capped)
assert (root/'packages/octop/dashboard/index.html').is_file()
assert pathlib.Path(sys.base_prefix).resolve() == (root/'runtime').resolve()
"""
    with tempfile.TemporaryDirectory() as work:
        run(
            [sidecar / "runtime/bin/python3", "-I", "-B", "-c", check_runtime, sidecar],
            cwd=work,
            env=clean_env(work),
        )


def notary_auth(profile: str) -> list[str]:
    key, key_id, issuer = (
        os.environ.get(n, "").strip()
        for n in ("APPLE_API_KEY", "APPLE_API_KEY_ID", "APPLE_API_ISSUER")
    )
    if key and key_id and issuer:
        return ["--key", key, "--key-id", key_id, "--issuer", issuer]
    return ["--keychain-profile", profile]


def check_notary(profile: str) -> None:
    auth = notary_auth(profile)
    if auth[0] == "--key":
        return
    probe = subprocess.run(
        ["xcrun", "notarytool", "history", *auth], capture_output=True, text=True
    )
    if probe.returncode:
        raise SystemExit(
            f'No usable notarytool keychain profile "{profile}". Store one once on this Mac:\n'
            f"  xcrun notarytool store-credentials {profile} --key <AuthKey_XXXX.p8> "
            "--key-id <Key ID> --issuer <Issuer ID>\n"
            "or pass --notary-profile with an existing profile."
        )


def notarize_dmg(dmg: Path, profile: str) -> None:
    result = subprocess.run(
        [
            "xcrun",
            "notarytool",
            "submit",
            dmg,
            *notary_auth(profile),
            "--wait",
            "--output-format",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    try:
        submission = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise SystemExit(f"notarytool failed:\n{result.stdout}\n{result.stderr}") from None
    print(f"Notarization {submission.get('id')}: {submission.get('status')}")
    if submission.get("status") != "Accepted":
        raise SystemExit(
            f"Notarization was not accepted. Inspect it with:\n"
            f"  xcrun notarytool log {submission.get('id')} {' '.join(notary_auth(profile))}"
        )
    run(["xcrun", "stapler", "staple", dmg])


def verify_signed(app: Path, dmg: Path | None) -> None:
    checks: list[list[str | Path]] = [
        ["codesign", "--verify", "--deep", "--strict", "--verbose=2", app],
        ["spctl", "-a", "-vvv", app],
        ["xcrun", "stapler", "validate", app],
    ]
    if dmg:
        checks += [
            ["codesign", "--verify", "--strict", "--verbose=2", dmg],
            ["spctl", "-a", "-vvv", "-t", "install", dmg],
            ["xcrun", "stapler", "validate", dmg],
        ]
    for check in checks:
        result = subprocess.run([str(a) for a in check], capture_output=True, text=True)
        output = (result.stdout + result.stderr).strip()
        print(f"$ {' '.join(str(a) for a in check)}\n{output}")
        if result.returncode or (
            check[0] == "spctl" and "source=Notarized Developer ID" not in output
        ):
            raise SystemExit(f"Verification failed: {check[0]} {check[-1]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--dir", action="store_true")
    parser.add_argument("--unsigned", action="store_true", help="Skip signing and notarization.")
    parser.add_argument(
        "--notary-profile",
        default=os.environ.get("OCTOP_BOT_NOTARY_PROFILE", "lynxce-notary"),
        help="notarytool keychain profile (ignored when APPLE_API_KEY* are set).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=SHELL / "release" / "octop-bot",
        help="Build into a separate release directory, e.g. while the previous client is running.",
    )
    args = parser.parse_args()
    if sys.platform != "darwin" or platform.machine() != "arm64":
        parser.error("Build on an Apple silicon Mac.")
    uv = binary("uv")
    version = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    semver = re.sub(
        r"(a|b|rc)(\d+)$",
        lambda m: "-" + {"a": "alpha", "b": "beta", "rc": "rc"}[m[1]] + "." + m[2],
        version,
    )
    cache_key = hashlib.sha256(
        (REPO / "uv.lock").read_bytes() + (PYTHON_VERSION + str(EXTRAS) + REQUIREMENT).encode()
    ).hexdigest()[:12]
    stage = SHELL / ".dev-runtime" / "bot-mac" / cache_key
    prepare_dependencies(stage, uv)
    shutil.copy2(REPO / "desktop/src/resources/bot-icon.png", stage / "bot-icon.png")
    if args.prepare:
        print(f"Runtime ready at {stage}")
        return
    sign = not args.unsigned
    if sign:
        check_notary(args.notary_profile)
    node = binary("node")
    dashboard = REPO / "dashboard"
    env = {**os.environ, "NODE_ENV": "production", "NODE_OPTIONS": "--max-old-space-size=4096"}
    run([node, dashboard / "node_modules/typescript/bin/tsc", "-b"], cwd=dashboard, env=env)
    run([node, dashboard / "node_modules/vite/bin/vite.js", "build"], cwd=dashboard, env=env)
    install_wheel(stage, uv, version)
    run([node, SHELL / "node_modules/electron-vite/bin/electron-vite.js", "build"], cwd=SHELL)
    env.update(OCTOP_BOT_STAGING=str(stage), OCTOP_BOT_PACKAGE_VERSION=semver)
    # Notarization only through the keychain profile or an API key. APPLE_TEAM_ID
    # and Apple ID variables would switch electron-builder to another login path.
    for name in (
        "APPLE_ID",
        "APPLE_APP_SPECIFIC_PASSWORD",
        "APPLE_TEAM_ID",
        "APPLE_KEYCHAIN_PROFILE",
    ):
        env.pop(name, None)
    if sign:
        env["OCTOP_BOT_MAC_SIGN"] = "1"
        if notary_auth(args.notary_profile)[0] == "--keychain-profile":
            env["APPLE_KEYCHAIN_PROFILE"] = args.notary_profile
    else:
        env["CSC_IDENTITY_AUTO_DISCOVERY"] = "false"
    output = args.output.resolve()
    command = [
        node,
        SHELL / "node_modules/electron-builder/cli.js",
        "--config",
        "electron-builder.bot.cjs",
        "--mac",
        "--arm64",
        f"--config.directories.output={output}",
    ]
    if args.dir:
        command.append("--dir")
    run(command, cwd=SHELL, env=env)
    app = output / "mac-arm64" / APP_NAME
    verify_runtime(app, node)
    dmg = None if args.dir else output / f"Octop-Bot-{semver}-mac-arm64.dmg"
    if dmg and not dmg.is_file():
        raise SystemExit(f"Missing {dmg}")
    if sign:
        if dmg:
            notarize_dmg(dmg, args.notary_profile)
        verify_signed(app, dmg)
        if dmg:
            # The release folder that octop_bot_manifest.py build --dist reads.
            dist = REPO / "dist" / version
            dist.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dmg, dist / dmg.name)
            digest = hashlib.sha256(dmg.read_bytes()).hexdigest()
            (dist / f"{dmg.name}.sha256").write_text(f"{digest}  {dmg.name}\n", encoding="utf-8")
            dmg = dist / dmg.name
    print(dmg or app)


if __name__ == "__main__":
    main()
