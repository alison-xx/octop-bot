"""Render the exact delivered Office revision on its own running cloud computer."""

from __future__ import annotations

import base64
import io
import json
import shlex
import uuid
from importlib.resources import files
from pathlib import PurePosixPath

from PIL import Image

from octop.infra.cloud.computers.driver import WORKSPACE, ComputerDriver

OFFICE = frozenset({".docx", ".xlsx", ".pptx"})
MAX_JPEG = 128 * 1024


class OfficePreviewError(Exception):
    """An actionable, model-facing reason why the document could not be delivered."""


# This program runs inside the guest's disposable, networkless mount namespace.
# Copy the bound input before hashing: the renderer reads exactly the checked bytes.
_INSPECT = """
import base64, hashlib, json, resource, runpy, sys
from pathlib import Path
resource.setrlimit(resource.RLIMIT_FSIZE, (128 << 20, 128 << 20))
resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
source = Path(sys.argv[1])
with source.open("rb") as stream:
    data = stream.read((50 << 20) + 1)
if len(data) > 50 << 20 or hashlib.sha256(data).hexdigest() != sys.argv[2]:
    raise SystemExit(72)
copy = Path("/tmp") / source.name
copy.write_bytes(data)
output = Path("/tmp/preview.jpg")
pages = runpy.run_path("/renderer.py")["thumbnail"](copy, output)
if not 0 < output.stat().st_size <= 128 << 10:
    raise SystemExit(73)
print("OCTOP_OFFICE_PREVIEW " + json.dumps([pages, base64.b64encode(output.read_bytes()).decode("ascii")]))
"""


def guest_preview(
    driver: ComputerDriver, instance: str, workspace_path: str, digest: str, stored: bytes | None
) -> tuple[int, bytes]:
    suffix = PurePosixPath(workspace_path).suffix.lower()
    if suffix not in OFFICE:
        raise OfficePreviewError("Choose a Word, Excel or PowerPoint document.")
    scratch = f"/tmp/octop-preview-{uuid.uuid4().hex}"
    if driver.run(instance, f"umask 077 && mkdir {scratch}", 15)[0]:
        raise OfficePreviewError("The computer could not prepare its private preview directory.")
    try:
        renderer = files("octop.infra.agents").joinpath(
            "builtin_skills/office-documents/scripts/render.py"
        )
        driver.write(instance, f"{scratch}/renderer.py", renderer.read_bytes())
        source = workspace_path
        if stored is not None:
            source = f"{scratch}/source{suffix}"
            driver.write(instance, source, stored)
        # Accept a virtual workspace file or our private copy. Resolve in the guest,
        # then bind just that file, the renderer and the OS libraries/fonts it needs.
        target = f"/source{suffix}"
        args = [
            "bwrap",
            "--unshare-all",
            "--new-session",
            "--die-with-parent",
            "--cap-drop",
            "ALL",
            "--clearenv",
            "--setenv",
            "PATH",
            "/usr/bin:/bin",
            "--setenv",
            "HOME",
            "/tmp",
            "--setenv",
            "LANG",
            "C.UTF-8",
            "--ro-bind",
            "/usr",
            "/usr",
        ]
        for name in ("bin", "sbin", "lib", "lib64"):
            args.extend(["--ro-bind-try", f"/{name}", f"/{name}"])
        args.extend(
            [
                "--ro-bind-try",
                "/etc/libreoffice",
                "/etc/libreoffice",
                "--ro-bind-try",
                "/var/cache/fontconfig",
                "/var/cache/fontconfig",
                "--ro-bind-try",
                "/etc/fonts",
                "/etc/fonts",
                "--ro-bind-try",
                "/etc/ld.so.cache",
                "/etc/ld.so.cache",
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--tmpfs",
                "/tmp",
                "--chdir",
                "/tmp",
                "--ro-bind",
                f"{scratch}/renderer.py",
                "/renderer.py",
            ]
        )
        allowed = scratch if stored is not None else WORKSPACE
        command = (
            f"p=$(realpath -e -- {shlex.quote(source)}) || exit 72; "
            f'case "$p" in {allowed}/*) ;; *) exit 72 ;; esac; '
            + shlex.join(args)
            + ' --ro-bind "$p" '
            + shlex.join([target, "/usr/bin/python3", "-I", "-c", _INSPECT, target, digest])
        )
        code, output = driver.run(instance, command, 240)
        if code == 72:
            raise OfficePreviewError(
                "The computer lacks this exact revision. Save the document and retry."
            )
        if code:
            raise OfficePreviewError(
                "The cloud computer could not render a private Office preview. Check its renderer and document."
            )
        try:
            (receipt,) = [
                line.removeprefix("OCTOP_OFFICE_PREVIEW ")
                for line in output.splitlines()
                if line.startswith("OCTOP_OFFICE_PREVIEW ")
            ]
            pages, encoded = json.loads(receipt)
            if (
                type(pages) is not int
                or pages < 1
                or not isinstance(encoded, str)
                or len(encoded) > (MAX_JPEG * 4 // 3 + 4)
            ):
                raise ValueError
            jpeg = base64.b64decode(encoded, validate=True)
            with Image.open(io.BytesIO(jpeg)) as image:
                if image.format != "JPEG" or max(image.size) > 384:
                    raise ValueError
                image.load()
        except (IndexError, TypeError, ValueError, OSError, Image.DecompressionBombError) as exc:
            raise OfficePreviewError("The cloud computer returned an unreadable preview.") from exc
        return pages, jpeg
    finally:
        driver.run(instance, f"rm -rf -- {scratch}", 15)
