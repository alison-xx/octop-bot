"""Build the standalone x64 Octop Bot client from the checkout and locked dependencies.

On Windows, install the dashboard's npm lock and desktop/src's pnpm lock, then run
`pnpm run package:bot:win` in desktop/src. Use --prepare to cache only CPython and
dependencies, or --dir for the unpacked app without generating the installer and ZIP.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

from bot_harness_wheel import REQUIREMENT, install_harness

SHELL = Path(__file__).resolve().parents[1]
REPO = SHELL.parent.parent
PORTABLE = REPO / "desktop" / "portable"
PYTHON_VERSION = "3.12.13"
EXTRAS = ("browser", "computer-use", "desktop")


def binary(name: str, fallback: Path | None = None) -> str:
    value = shutil.which(name)
    if value:
        return value
    if fallback and fallback.is_file():
        return str(fallback)
    raise SystemExit(f"Install {name} to build the desktop client.")


def run(args: list[str | Path], **kwargs) -> None:
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def prepare_dependencies(stage: Path, uv: str) -> None:
    portable = stage / "portable"
    marker = stage / "dependencies.ready"
    if marker.is_file():
        return
    portable.mkdir(parents=True, exist_ok=True)
    find_python = [uv, "python", "find", "--system", "--managed-python", PYTHON_VERSION]
    try:
        source = subprocess.check_output(find_python, text=True, stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        run([uv, "python", "install", PYTHON_VERSION])
        source = subprocess.check_output(find_python, text=True).strip()
    base = Path(source).resolve().parent
    if not (base / "DLLs").is_dir() or not (base / "Lib" / "os.py").is_file():
        raise SystemExit("A complete uv-managed Windows CPython installation is required.")
    shutil.copytree(
        base,
        portable / "runtime",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "site-packages", "Scripts", "*.pyc"),
    )
    python = portable / "runtime" / "python.exe"
    run(
        [
            python,
            "-I",
            "-c",
            "import pathlib, sys; assert pathlib.Path(sys.base_prefix) == pathlib.Path(sys.executable).parent",
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
    for dll in (packages / "pywin32_system32").glob("*.dll"):
        shutil.copy2(dll, python.parent / dll.name)
    run([python, "-I", "-B", PORTABLE / "prune_packages.py", packages])
    marker.touch()


def install_wheel(stage: Path, uv: str, version: str) -> None:
    portable = stage / "portable"
    python = portable / "runtime" / "python.exe"
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
    relocate_entrypoints(portable)
    for direct in packages.glob("*.dist-info/direct_url.json"):
        provenance = json.loads(direct.read_text(encoding="utf-8"))
        if provenance.get("dir_info", {}).get("editable") or str(
            provenance.get("url", "")
        ).startswith("file:"):
            raise SystemExit(f"Local package source found in {direct}")
    if list(packages.glob("*.egg-link")) or list(packages.glob("*editable*.pth")):
        raise SystemExit("Editable Python installation found in the distribution.")
    with tempfile.TemporaryDirectory() as work:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("OCTOP_", "PYTHON"))}
        env["OCTOP_HOME"] = work
        run([python, "-I", "-B", portable / "launch.py", "--version"], cwd=work, env=env)


def relocate_entrypoints(portable: Path) -> None:
    packages = portable / "packages"
    # uv's generated Windows launcher EXEs embed the build interpreter's absolute
    # filename. Replace just those entry points with relocatable Windows commands.
    command = (
        '@echo off\n"%~dp0..\\..\\runtime\\python.exe" '
        '"%~dp0..\\..\\console-entry.py" "%~n0" %*\nexit /b %ERRORLEVEL%\n'
    )
    (portable / "console-entry.py").write_text(
        "import sys\nfrom importlib.metadata import entry_points\nfrom launch import _bootstrap\n"
        "_bootstrap()\nname = sys.argv.pop(1)\nsys.argv[0] = name\n"
        "raise SystemExit(next(ep for ep in entry_points()"
        " if ep.group in ('console_scripts','gui_scripts') and ep.name == name).load()())\n",
        encoding="utf-8",
    )
    for dist in importlib.metadata.distributions(path=[str(packages)]):
        for entry in dist.entry_points:
            if entry.group not in ("console_scripts", "gui_scripts"):
                continue
            wrapper = packages / "bin" / f"{entry.name}.exe"
            if wrapper.is_file():
                wrapper.unlink()
                wrapper.with_suffix(".cmd").write_text(command, encoding="ascii")
    # Wheels can also install plain scripts from their .data/scripts directory.
    # Installers rewrite their first line to the build interpreter's location.
    for script in (packages / "bin").iterdir():
        if not script.is_file():
            continue
        with script.open("rb") as stream:
            line = stream.readline(2048)
            if line.startswith(b"#!") and b"python" in line.lower():
                body = stream.read()
            else:
                continue
        script.write_bytes(b"#!/usr/bin/env python\n" + body)


def build_icons(stage: Path) -> None:
    python = stage / "portable" / "runtime" / "python.exe"
    script = """
import site, sys
from pathlib import Path
site.addsitedir(sys.argv[1])
from PIL import Image, ImageOps
source = Image.open(sys.argv[2]).convert("RGBA")
icon = ImageOps.pad(source, (512,512), method=Image.Resampling.LANCZOS, color=(0,0,0,0))
icon.save(Path(sys.argv[3]) / "bot-icon.png")
icon.save(Path(sys.argv[3]) / "bot-icon.ico", sizes=[(n,n) for n in (16,24,32,48,64,128,256)])
"""
    run(
        [
            python,
            "-I",
            "-B",
            "-c",
            script,
            stage / "portable" / "packages",
            REPO / "desktop/src/resources/bot-icon.png",
            stage,
        ]
    )


def verify_package(unpacked: Path, node: str) -> None:
    resources = unpacked / "resources"
    sidecar = resources / "sidecar"
    if not (unpacked / "Octop Bot.exe").is_file():
        raise SystemExit("The packaged Windows executable is missing.")
    for filename in ("bot-icon.ico", "bot-icon.png", "app.asar"):
        if not (resources / filename).is_file():
            raise SystemExit(f"Missing packaged resource: {filename}")
    if {p.name for p in sidecar.iterdir()} != {
        "packages",
        "runtime",
        "launch.py",
        "console-entry.py",
        "version.json",
    }:
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
for name in ('octop','octop_harness','octop_memory','octop_gateway','octop_browser','cua_driver','PIL','win32api'):
    origin = pathlib.Path(importlib.import_module(name).__file__).resolve()
    if not origin.is_relative_to(root): raise RuntimeError(f'{name} comes from outside the bundle: {origin}')
from importlib.metadata import version
from octop_harness.backends.workspace import BackendWorkspace
assert version('octop-harness') == '1.0.11+bounded.1'
assert callable(BackendWorkspace.adownload_bytes_capped)
assert (root/'packages/octop/dashboard/index.html').is_file()
assert pathlib.Path(sys.base_prefix).resolve() == (root/'runtime')
"""
    with tempfile.TemporaryDirectory() as work:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("OCTOP_", "PYTHON"))}
        env["OCTOP_HOME"] = work
        run(
            [sidecar / "runtime/python.exe", "-I", "-B", "-c", check_runtime, sidecar],
            cwd=work,
            env=env,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--dir", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=SHELL / "release" / "octop-bot",
        help="Build into a separate release directory, e.g. while the previous client is running.",
    )
    args = parser.parse_args()
    if sys.platform != "win32" or os.environ.get("PROCESSOR_ARCHITECTURE", "").upper() != "AMD64":
        parser.error("Build on x64 Windows.")
    uv = binary("uv", Path.home() / ".local/bin/uv.exe")
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
    stage = SHELL / ".dev-runtime" / "bot-windows" / cache_key
    prepare_dependencies(stage, uv)
    build_icons(stage)
    if args.prepare:
        print(f"Runtime and icons ready at {stage}")
        return
    node = binary("node")
    dashboard = REPO / "dashboard"
    env = {**os.environ, "NODE_ENV": "production", "NODE_OPTIONS": "--max-old-space-size=4096"}
    run([node, dashboard / "node_modules/typescript/bin/tsc", "-b"], cwd=dashboard, env=env)
    run([node, dashboard / "node_modules/vite/bin/vite.js", "build"], cwd=dashboard, env=env)
    install_wheel(stage, uv, version)
    run([node, SHELL / "node_modules/electron-vite/bin/electron-vite.js", "build"], cwd=SHELL)
    env.update(OCTOP_BOT_STAGING=str(stage), OCTOP_BOT_PACKAGE_VERSION=semver)
    # The sidecar contains tens of thousands of small Python and data files.
    # A moderate NSIS compression level keeps local release builds practical.
    env.setdefault("ELECTRON_BUILDER_COMPRESSION_LEVEL", "3")
    command = [
        node,
        SHELL / "node_modules/electron-builder/cli.js",
        "--config",
        "electron-builder.bot.cjs",
        "--win",
        "--x64",
    ]
    output = args.output.resolve()
    command.append(f"--config.directories.output={output}")
    if args.dir:
        command.append("--dir")
    run(command, cwd=SHELL, env=env)
    unpacked = output / "win-unpacked"
    verify_package(unpacked, node)
    if not args.dir:
        archive = output / f"Octop-Bot-{semver}-x64.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
            for file in sorted(unpacked.rglob("*")):
                if file.is_file():
                    zf.write(file, Path("Octop Bot") / file.relative_to(unpacked))
        print(archive)
    print(unpacked / "Octop Bot.exe")


if __name__ == "__main__":
    main()
