"""What a Bot may hand to the user: files that open, with content and a real name."""

from __future__ import annotations

import io
import zipfile

from octop.infra.bot_tasks.deliverables import inspect_file


def _zip(files: dict[str, str]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, body in files.items():
            archive.writestr(name, body)
    return out.getvalue()


def test_names_that_say_nothing_are_refused() -> None:
    assert not inspect_file("output.csv", b"a,b\n1,2\n").ok
    assert not inspect_file("未命名.md", "# 报告".encode()).ok
    assert inspect_file("竞品价格_2026Q3.csv", b"a,b\n1,2\n").ok


def test_empty_and_broken_files_are_refused() -> None:
    assert inspect_file("报告.pdf", b"").problems == ["the file is empty"]
    assert "not a PDF" in inspect_file("报告.pdf", b"<html>").problems[0]
    assert "not a valid Office file" in inspect_file("报告.docx", b"PK broken").problems[0]
    assert "does not open" in inspect_file("图.png", b"\x89PNG broken").problems[0]
    assert "not valid JSON" in inspect_file("数据.json", b"{oops").problems[0]


def test_a_header_row_alone_or_an_empty_sheet_is_no_deliverable() -> None:
    assert "no data rows" in inspect_file("价格.csv", "公司,价格\n".encode()).problems[0]
    sheet = _zip({"xl/workbook.xml": "<w/>", "xl/worksheets/sheet1.xml": "<sheetData/>"})
    assert inspect_file("价格.xlsx", sheet).problems == ["the workbook is empty"]


def test_template_text_left_in_place_is_caught() -> None:
    doc = _zip({"word/document.xml": "<w:t>公司简介：{{ company }}，在此输入</w:t>"})
    problems = inspect_file("方案.docx", doc).problems
    assert problems and "template text" in problems[0]
    assert "template text" in inspect_file("说明.md", b"Lorem ipsum dolor").problems[0]


def test_what_was_checked_is_returned_as_data_for_the_client() -> None:
    assert inspect_file("价格.csv", "公司,价格\nA,1\nB,2\n".encode()).facts == [
        {"k": "rows", "n": 2}
    ]
    deck = _zip(
        {"ppt/slides/slide1.xml": "<a:t>封面</a:t>", "ppt/slides/slide2.xml": "<a:t>结论</a:t>"}
    )
    assert inspect_file("汇报.pptx", deck).facts == [{"k": "slides", "n": 2}]
    from pypdf import PdfWriter

    pdf = io.BytesIO()
    writer = PdfWriter()
    for _ in range(2):
        writer.add_blank_page(width=100, height=100)
    writer.write(pdf)
    assert inspect_file("报告.pdf", pdf.getvalue()).facts == [{"k": "pages", "n": 2}]
    assert not inspect_file("报告.pdf", pdf.getvalue()[:50]).ok


def test_real_images_report_their_size() -> None:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (40, 30)).save(out, "PNG")
    assert inspect_file("截图.png", out.getvalue()).facts == [
        {"k": "pixels", "n": 1200, "w": 40, "h": 30}
    ]


def test_checks_distinguish_name_bytes_and_parsed_content() -> None:
    assert inspect_file("report.json", None).facts == [{"k": "filenameOnly", "n": 1}]
    assert inspect_file("report.bin", b"example").facts == [{"k": "nonempty", "n": 1}]
    assert inspect_file("report.json", b'{"count": 4}').facts == [{"k": "validJson", "n": 1}]
