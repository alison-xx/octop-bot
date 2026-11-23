"""Octop Bot clients read /api/octop-bot/server-info before anyone signs in."""

from pathlib import Path

import pytest

from tests.support.app import octop_client

INFO = "/api/octop-bot/server-info"


async def test_fresh_web_build_offers_lynxce_sign_in(
    tmp_octop_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOP_BOT_WEB", "1")
    async with octop_client(tmp_octop_home) as (client, _srv):
        res = await client.get(INFO)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["product"] == "octop-bot"
        assert body["edition"] == "web"
        assert body["setup_required"] is True
        assert body["sign_in"] == ["lynxce", "password"]
        assert body["capabilities"] == {
            "wallet": False,
            "cloud_computer": False,
            "file_store": "local",
        }
        assert body["version"]
        assert res.headers["cache-control"] == "no-store"


async def test_plain_server_signs_in_with_a_password(
    tmp_octop_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OCTOP_BOT_WEB", raising=False)
    async with octop_client(tmp_octop_home) as (client, _srv):
        body = (await client.get(INFO)).json()
        assert body["edition"] == "server"
        assert body["sign_in"] == ["password"]
