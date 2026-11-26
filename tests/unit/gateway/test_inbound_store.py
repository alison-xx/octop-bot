"""Unit tests for inbound attachment storage."""

from __future__ import annotations

import asyncio
import re
import tempfile

import pytest
from deepagents.backends.local_shell import LocalShellBackend
from octop_harness.backends.workspace import BackendWorkspace

from octop.infra.gateway.media.inbound_store import (
    build_timestamped_inbound_name,
    display_name_from_stored,
    inbound_extension,
    read_inbound_bytes,
    sanitize_inbound_filename,
    write_inbound,
)


def _workspace(root: str) -> BackendWorkspace:
    backend = LocalShellBackend(root_dir=root, virtual_mode=False)
    return BackendWorkspace(backend, root)


def test_inbound_extension_from_filename() -> None:
    assert inbound_extension("report.pdf", "application/pdf") == ".pdf"


def test_sanitize_inbound_filename_keeps_cjk() -> None:
    assert sanitize_inbound_filename("我的报告.pdf") == "我的报告.pdf"
    assert sanitize_inbound_filename(r"C:\Users\me\地球介绍.pptx") == "地球介绍.pptx"
    assert sanitize_inbound_filename('say "hi".txt') == "say _hi_.txt"
    assert sanitize_inbound_filename("../evil.pdf") == "evil.pdf"


def test_timestamped_name_and_display_roundtrip() -> None:
    stored = build_timestamped_inbound_name("地球介绍.pptx", now=1783510288)
    assert re.fullmatch(r"1783510288\d{25}_地球介绍\.pptx", stored)
    assert display_name_from_stored("1783510288_地球介绍.pptx") == "地球介绍.pptx"
    assert display_name_from_stored(stored) == "地球介绍.pptx"


@pytest.mark.asyncio
async def test_write_inbound_uses_timestamp_prefix_keeps_chinese() -> None:
    with tempfile.TemporaryDirectory() as ws_dir:
        workspace = _workspace(ws_dir)
        stored = await write_inbound(
            workspace,
            b"%PDF-1.4",
            filename="地球介绍.pdf",
            media_type="application/pdf",
        )
        assert stored.filename == "地球介绍.pdf"
        assert re.fullmatch(r"inbound/\d{10,}_地球介绍\.pdf", stored.path)
        on_disk = await read_inbound_bytes(workspace, stored.path)
        assert on_disk == b"%PDF-1.4"


@pytest.mark.asyncio
async def test_concurrent_archives_keep_names_and_separate_bytes(tmp_path, monkeypatch) -> None:
    workspace = _workspace(str(tmp_path))

    async def unexpected_probe(path):
        pytest.fail(f"upload probed {path} before writing")

    monkeypatch.setattr(workspace, "aexists", unexpected_probe)
    name = "压缩包" * 29 + ".ZIP"
    files = await asyncio.gather(
        *(
            write_inbound(
                workspace, payload, filename=name, media_type="application/x-zip-compressed"
            )
            for payload in (b"first", b"second")
        )
    )
    assert files[0].path != files[1].path
    assert files[0].filename.endswith(".ZIP")
    assert await asyncio.gather(*(read_inbound_bytes(workspace, f.path) for f in files)) == [
        b"first",
        b"second",
    ]


@pytest.mark.asyncio
async def test_write_inbound_no_meta_sidecar() -> None:
    with tempfile.TemporaryDirectory() as ws_dir:
        workspace = _workspace(ws_dir)
        stored = await write_inbound(
            workspace,
            b"%PDF-1.4",
            filename="report.pdf",
            media_type="application/pdf",
        )
        assert stored.path.endswith(".pdf")
        assert stored.path.startswith("inbound/")
        on_disk = await read_inbound_bytes(workspace, stored.path)
        assert on_disk == b"%PDF-1.4"


@pytest.mark.asyncio
async def test_write_inbound_flat_docx_path() -> None:
    with tempfile.TemporaryDirectory() as ws_dir:
        workspace = _workspace(ws_dir)
        stored = await write_inbound(
            workspace,
            b"PK-docx",
            filename="report.docx",
            media_type=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        )
        assert stored.path.endswith(".docx")
        assert stored.filename == "report.docx"
