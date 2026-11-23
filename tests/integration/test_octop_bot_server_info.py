"""Octop Bot clients read /api/octop-bot/server-info before anyone signs in."""

import asyncio
import threading
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
            "media_generation": True,
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


async def test_version_is_read_once_and_off_the_event_loop(
    tmp_octop_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from octop.api.routers import bot_server

    calls: list[int] = []

    def slow_version() -> str:
        # A green / fpk install runs a subprocess here; it must not hold the loop.
        calls.append(threading.get_ident())
        return "9.9.9"

    monkeypatch.setattr(bot_server, "_local_version", None)
    monkeypatch.setattr(bot_server, "get_local_version", slow_version)
    async with octop_client(tmp_octop_home) as (client, _srv):
        loop_thread = threading.get_ident()
        bodies = await asyncio.gather(*(client.get(INFO) for _ in range(5)))
        assert {res.json()["version"] for res in bodies} == {"9.9.9"}
        assert (await client.get(INFO)).json()["version"] == "9.9.9"
    assert len(calls) == 1
    assert calls[0] != loop_thread


def test_a_failed_version_read_is_not_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    from octop.api.routers import bot_server

    reads = iter(["0.0.0", "1.0.4"])
    monkeypatch.setattr(bot_server, "_local_version", None)
    monkeypatch.setattr(bot_server, "get_local_version", lambda: next(reads))
    assert bot_server._read_local_version_once() == "0.0.0"
    assert bot_server._read_local_version_once() == "1.0.4"  # tried again, then kept
    assert bot_server._read_local_version_once() == "1.0.4"
