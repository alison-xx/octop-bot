"""Pinned desktop dependency until the bounded workspace API ships upstream."""

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

VERSION = "1.0.11+bounded.1"
WHEEL = Path(__file__).resolve().parents[2] / f"vendor/octop_harness-{VERSION}-py3-none-any.whl"
SHA256 = "840786c69f9a5a0eb9e2a4399e889c6c6b404b37f68de20c9cdad49b850ecabe"
REQUIREMENT = f"octop-harness=={VERSION} --hash=sha256:{SHA256}"


def install_harness(uv: str, python: Path, *, target: Path | None = None) -> None:
    if hashlib.sha256(WHEEL.read_bytes()).hexdigest() != SHA256:
        raise ValueError("Desktop harness wheel digest mismatch")

    # A direct wheel URL records the build machine's path in the installed metadata.
    with tempfile.TemporaryDirectory() as tmp:
        requirements = Path(tmp) / "requirements.txt"
        requirements.write_text(REQUIREMENT + "\n", encoding="utf-8")
        args = [
            uv,
            "pip",
            "install",
            "--python",
            str(python),
            "--offline",
            "--no-index",
            "--find-links",
            str(WHEEL.parent),
            "--no-deps",
            "--require-hashes",
            "--reinstall-package",
            "octop-harness",
            "--link-mode",
            "copy",
            "-r",
            str(requirements),
        ]
        if target is not None:
            args.extend(["--target", str(target)])
        subprocess.run(args, check=True)


if __name__ == "__main__":
    # Source-mode Electron uses this interpreter's site-packages.
    install_harness("uv", Path(sys.executable))
