"""Integration tests for dashboard chat attachments in agent workspace."""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any
from urllib.parse import unquote

import pytest


async def test_upload_and_workspace_download(env_with_agent: Any) -> None:
    client, _srv, auth, aid = env_with_agent
    files = {"file": ("note.txt", b"hello attachment", "text/plain")}
    r = await client.post(f"/api/agents/{aid}/upload", files=files, headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["path"] == body["workspace_path"]
    assert body["access_url"].startswith(f"/api/agents/{aid}/workspace/download")
    assert body["filename"] == "note.txt"
    assert body["media_type"] == "text/plain"
    assert body["workspace_path"].endswith(".txt")
    assert body["workspace_path"].startswith("inbound/")
    assert re.search(r"inbound/\d{10,}_note\.txt$", body["workspace_path"])
    assert "file_id" not in body
    assert "legacy_url" not in body

    r2 = await client.get(body["access_url"], headers=auth)
    assert r2.status_code == 200, r2.text
    assert r2.content == b"hello attachment"


async def test_upload_pdf_workspace_path(env_with_agent: Any) -> None:
    client, _srv, auth, aid = env_with_agent
    files = {"file": ("report.pdf", b"%PDF-1.4", "application/pdf")}
    r = await client.post(f"/api/agents/{aid}/upload", files=files, headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["workspace_path"].endswith(".pdf")
    assert body["filename"] == "report.pdf"

    r2 = await client.get(body["access_url"], headers=auth)
    assert r2.status_code == 200, r2.text
    assert r2.content == b"%PDF-1.4"


async def test_upload_requires_auth(env: Any) -> None:
    client, _srv, _auth = env
    files = {"file": ("note.txt", b"x", "text/plain")}
    r = await client.post("/api/agents/NOPE/upload", files=files)
    assert r.status_code == 401, r.text


async def test_cloud_upload_and_reopen_zip_and_preview_while_bot_is_stopped(
    env_with_agent: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, srv, auth, aid = env_with_agent
    stopped = await client.post(f"/api/agents/{aid}/stop", headers=auth)
    assert stopped.status_code == 204
    monkeypatch.setenv("OCTOP_BOT_CLOUD", "1")
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("目录/原文.txt", "完整内容")
    for name, mime, data in [
        ("项目 100%.ZIP", "application/x-zip-compressed", raw.getvalue()),
        ("示意图.png", "image/png", b"\x89PNG\r\n\x1a\n"),
    ]:
        uploaded = await client.post(
            f"/api/agents/{aid}/upload", files={"file": (name, data, mime)}, headers=auth
        )
        assert uploaded.status_code == 200, uploaded.text
        file = uploaded.json()
        assert file["filename"] == name
        if name.endswith(".ZIP"):
            assert file["media_type"] == "application/zip"
        assert (await client.get(file["access_url"])).status_code == 401
        opened = await client.get(file["access_url"], headers=auth)
        assert opened.status_code == 200 and opened.content == data
        if name.endswith(".ZIP"):
            assert unquote(opened.headers["content-disposition"]).endswith(name)
            with zipfile.ZipFile(io.BytesIO(opened.content)) as saved:
                assert saved.read("目录/原文.txt").decode() == "完整内容"
