"""Pinned desktop dependency until the bounded workspace API ships upstream."""

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

WHEEL = (
    Path(__file__).resolve().parents[2] / "vendor/octop_harness-1.0.11+bounded.1-py3-none-any.whl"
)
SHA256 = "840786c69f9a5a0eb9e2a4399e889c6c6b404b37f68de20c9cdad49b850ecabe"


def append_requirement(requirements: Path) -> None:
    if hashlib.sha256(WHEEL.read_bytes()).hexdigest() != SHA256:
        raise ValueError("Desktop harness wheel digest mismatch")
    with requirements.open("a", encoding="utf-8") as file:
        file.write(f"\noctop-harness @ {WHEEL.as_uri()} --hash=sha256:{SHA256}\n")


if __name__ == "__main__":
    # Source-mode Electron uses this interpreter's site-packages.
    with tempfile.TemporaryDirectory() as tmp:
        requirements = Path(tmp) / "requirements.txt"
        append_requirement(requirements)
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                sys.executable,
                "--no-index",
                "--no-deps",
                "--require-hashes",
                "-r",
                str(requirements),
            ],
            check=True,
        )
