"""Render an Office document in its execution environment, without modifying the source."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def libreoffice_command() -> str:
    for command in ("soffice", "libreoffice"):
        if found := shutil.which(command):
            return found
    candidates: list[Path] = []
    if sys.platform == "darwin":
        candidates.append(Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"))
    elif os.name == "nt":
        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
            if base := os.environ.get(variable):
                candidates.append(Path(base) / "LibreOffice" / "program" / "soffice.com")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise OSError("LibreOffice is required to render Office documents.")


def convert_pdf(source: Path, work: Path, office: str) -> Path:
    subprocess.run(
        [
            office,
            f"-env:UserInstallation={(work / 'profile').as_uri()}",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(work),
            str(source),
        ],
        check=True,
        timeout=180,
    )
    converted = work / source.with_suffix(".pdf").name
    if not converted.is_file():
        raise OSError("LibreOffice did not produce a PDF.")
    return converted


def render(source: Path, destination: Path) -> None:
    source = source.resolve(strict=True)
    destination = destination.absolute()
    if not source.is_file() or source.suffix.lower() not in {".docx", ".xlsx", ".pptx"}:
        raise ValueError("Expected a .docx, .xlsx or .pptx file.")
    if destination.exists():
        raise FileExistsError(f"Choose a new preview directory: {destination}")
    office = libreoffice_command()
    poppler = shutil.which("pdftoppm")
    if poppler is None:
        raise OSError("Poppler pdftoppm is required to render page images.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        work = Path(temporary)
        pages = work / "pages"
        pages.mkdir()
        converted = convert_pdf(source, work, office)
        pdf = pages / "document.pdf"
        converted.rename(pdf)
        subprocess.run(
            [poppler, "-png", "-r", "120", str(pdf), str(pages / "page")], check=True, timeout=180
        )
        if not any(pages.glob("page-*.png")):
            raise OSError("Poppler did not produce any page images.")
        pages.rename(destination)


def thumbnail(source: Path, destination: Path) -> int:
    """Render one bounded first-page JPEG and return the PDF's actual page count."""
    source = source.resolve(strict=True)
    if source.suffix.lower() not in {".docx", ".xlsx", ".pptx"}:
        raise ValueError("Expected an Office document.")
    if destination.exists():
        raise FileExistsError("Choose a new preview file.")
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        work = Path(temporary)
        pdf = convert_pdf(source, work, libreoffice_command())
        info = subprocess.run(
            ["pdfinfo", str(pdf)],
            check=True,
            capture_output=True,
            timeout=30,
            env={**os.environ, "LC_ALL": "C"},
        )
        pages = re.search(rb"^Pages:\s*([1-9]\d*)\s*$", info.stdout, re.MULTILINE)
        if not pages:
            raise ValueError("The rendered PDF has no pages.")
        prefix = work / "thumbnail"
        subprocess.run(
            [
                "pdftoppm",
                "-singlefile",
                "-f",
                "1",
                "-l",
                "1",
                "-scale-to",
                "384",
                "-jpeg",
                "-jpegopt",
                "quality=78",
                str(pdf),
                str(prefix),
            ],
            check=True,
            timeout=45,
        )
        prefix.with_suffix(".jpg").rename(destination)
        return int(pages[1])


def check() -> int:
    """Report whether page previews can be rendered here; exit 1 when they cannot."""
    missing: list[str] = []
    try:
        print(f"libreoffice: {libreoffice_command()}")
    except OSError:
        missing.append("LibreOffice (soffice)")
    if poppler := shutil.which("pdftoppm"):
        print(f"pdftoppm: {poppler}")
    else:
        missing.append("Poppler (pdftoppm)")
    if missing:
        print("preview unavailable, missing: " + ", ".join(missing))
        return 1
    print("preview available")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="only report renderer availability")
    parser.add_argument("source", type=Path, nargs="?")
    parser.add_argument("destination", type=Path, nargs="?")
    args = parser.parse_args()
    if args.check:
        return check()
    if args.source is None or args.destination is None:
        parser.error("source and destination are required")
    try:
        render(args.source, args.destination)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"{exc}\n")
    print(args.destination.absolute())
    return 0


if __name__ == "__main__":
    sys.exit(main())
