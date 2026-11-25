"""Checks on a file before a Bot hands it to the user, without a model.

A delivered file must open, have real content (not an empty sheet, a header row alone or a
template left as is), and have a name that says what it is. ``inspect_file`` returns what is
wrong (model-facing; the file is not sent) and what was checked, as data the client words
in the user's language (``{"k": "pages", "n": 12}``).
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath

# Names that say nothing about the file.
VAGUE_STEMS = frozenset(
    {
        "output",
        "out",
        "result",
        "untitled",
        "file",
        "new",
        "document",
        "temp",
        "tmp",
        "test",
        "未命名",
        "新建",
        "文档",
        "新建文档",
        "新建文件",
    }
)
# Template text left in a document meant for the user.
PLACEHOLDERS = re.compile(
    r"lorem ipsum|\{\{\s*\w+\s*\}\}|\[(?:insert|placeholder|todo)[^\]]*\]|在此(?:输入|填写)|待填写",
    re.IGNORECASE,
)
TEXT_SUFFIXES = frozenset({".md", ".txt", ".html", ".htm", ".py", ".js", ".ts", ".sql", ".xml"})
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"})
MAX_TEXT_SCAN = 2_000_000


@dataclass
class Inspection:
    problems: list[str] = field(default_factory=list)
    facts: list[dict[str, int | str]] = field(default_factory=list)

    def add(self, kind: str, count: int, **extra: int) -> None:
        self.facts.append({"k": kind, "n": count, **extra})

    @property
    def ok(self) -> bool:
        return not self.problems


def _decode(data: bytes) -> str | None:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _placeholder(text: str, result: Inspection) -> None:
    found = PLACEHOLDERS.search(text[:MAX_TEXT_SCAN])
    if found:
        result.problems.append(f"it still contains template text ({found.group(0)!r})")


def _office(data: bytes, suffix: str, result: Inspection) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        result.problems.append("it does not open (not a valid Office file)")
        return
    with archive:
        names = archive.namelist()
        if suffix == ".docx":
            if "word/document.xml" not in names:
                result.problems.append("it does not open (no document body)")
                return
            xml = archive.read("word/document.xml").decode("utf-8", "replace")
            text = re.sub(r"<[^>]+>", "", xml)
            if not text.strip():
                result.problems.append("the document has no text")
            else:
                result.add("chars", len(text.strip()))
                _placeholder(text, result)
        elif suffix == ".xlsx":
            sheets = [n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)]
            if not sheets:
                result.problems.append("the workbook has no sheets")
                return
            cells = sum(archive.read(n).count(b"<c ") for n in sheets)
            if not cells:
                result.problems.append("the workbook is empty")
            else:
                result.add("sheets", len(sheets))
        elif suffix == ".pptx":
            slides = [n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
            if not slides:
                result.problems.append("the presentation has no slides")
                return
            result.add("slides", len(slides))
            text = " ".join(
                re.sub(r"<[^>]+>", " ", archive.read(n).decode("utf-8", "replace")) for n in slides
            )
            _placeholder(text, result)


def _csv(data: bytes, result: Inspection) -> None:
    text = _decode(data)
    if text is None:
        result.problems.append("it is not readable text")
        return
    rows = [row for row in csv.reader(io.StringIO(text)) if any(cell.strip() for cell in row)]
    if len(rows) <= 1:
        result.problems.append("it has no data rows (a header at most)")
    else:
        result.add("rows", len(rows) - 1)


def _image(data: bytes, result: Inspection) -> None:
    from PIL import Image, UnidentifiedImageError  # noqa: PLC0415

    try:
        with Image.open(io.BytesIO(data)) as picture:
            picture.verify()
            width, height = picture.size
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        result.problems.append("the image does not open")
        return
    result.add("pixels", width * height, w=width, h=height)


def inspect_file(name: str, data: bytes | None) -> Inspection:
    """Inspect available content. None requests the name-only check for large files."""
    result = Inspection()
    path = PurePosixPath(name.replace("\\", "/"))
    suffix = path.suffix.lower()
    if path.stem.strip().lower() in VAGUE_STEMS:
        result.problems.append(
            f"the name {path.name!r} does not say what it is; rename it (e.g. 竞品价格对比_2026Q3.xlsx)"
        )
    if data is None:
        return result
    if not data:
        result.problems.append("the file is empty")
        return result
    if suffix == ".pdf":
        if not data.startswith(b"%PDF"):
            result.problems.append("it does not open (not a PDF)")
        else:
            from pypdf import PdfReader  # noqa: PLC0415
            from pypdf.errors import PyPdfError  # noqa: PLC0415

            try:
                pages = len(PdfReader(io.BytesIO(data)).pages)
            except (PyPdfError, ValueError, KeyError, TypeError, OSError):
                result.problems.append("the PDF does not open")
            else:
                if pages:
                    result.add("pages", pages)
                else:
                    result.problems.append("the PDF contains no pages")
    elif suffix in {".docx", ".xlsx", ".pptx"}:
        _office(data, suffix, result)
    elif suffix == ".csv":
        _csv(data, result)
    elif suffix == ".json":
        try:
            json.loads(data)
        except ValueError:
            result.problems.append("it is not valid JSON")
    elif suffix in IMAGE_SUFFIXES:
        _image(data, result)
    elif suffix == ".zip":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if archive.testzip() is not None:
                    result.problems.append("the archive is damaged")
                else:
                    result.add("files", len(archive.namelist()))
        except zipfile.BadZipFile:
            result.problems.append("the archive does not open")
    elif suffix in TEXT_SUFFIXES:
        text = _decode(data)
        if text is None:
            result.problems.append("it is not readable text")
        elif not text.strip():
            result.problems.append("the file has no text")
        else:
            _placeholder(text, result)
            result.add("lines", len(text.splitlines()))
    return result
