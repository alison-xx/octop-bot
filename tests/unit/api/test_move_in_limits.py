"""Moving a desktop into the cloud: bounded bodies and a per-account allowance."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from pydantic import ValidationError

from octop.api.middleware.body_limit import MB, BodyLimit
from octop.infra.cloud import move_in
from octop.infra.cloud.move_in import MovedThread
from octop.infra.errors import ErrorCode, OctopError


def _app() -> FastAPI:
    app = FastAPI()

    @app.post("/api/octop-bot/move-in/threads")
    async def moved(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    @app.post("/api/elsewhere")
    async def elsewhere(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    app.add_middleware(BodyLimit)
    return app


async def _post(path: str, content: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        return await client.post(path, content=content)


def test_move_in_bounds_each_chat_message() -> None:
    message = {"type": "human", "data": {"content": "hello"}}
    assert MovedThread(source="source", bot_id="bot", messages=[message]).messages == [message]
    with pytest.raises(ValidationError) as too_long:
        MovedThread(source="source", bot_id="bot", messages=[{"data": {"content": "字" * 200_001}}])
    assert too_long.value.errors()[0]["type"] == "string_too_long"


async def test_small_bodies_pass_through_whole() -> None:
    ok = await _post("/api/octop-bot/move-in/threads", b"x" * 1000)
    assert ok.json() == {"size": 1000}


async def test_a_body_over_10_mb_is_refused() -> None:
    big = await _post("/api/octop-bot/move-in/threads", b"x" * (10 * MB + 1))
    assert big.status_code == 413
    assert big.json()["error"]["code"] == ErrorCode.REQUEST_TOO_LARGE.value


async def test_a_streamed_body_without_a_length_is_cut_off_too() -> None:
    async def chunks():
        for _ in range(11):
            yield b"x" * MB

    big = await _post("/api/octop-bot/move-in/threads", chunks())
    assert big.status_code == 413


async def test_other_paths_are_not_limited() -> None:
    ok = await _post("/api/elsewhere", b"x" * (10 * MB + 1))
    assert ok.json() == {"size": 10 * MB + 1}


def test_each_account_has_an_hourly_and_daily_allowance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(move_in, "_move_usage", {})
    monkeypatch.setattr(move_in, "_next_usage_cleanup", 0.0)
    monkeypatch.setattr(move_in, "_MOVE_WINDOWS", ((3600, 3, 1000), (86400, 5, 10_000)))
    now = 100_000.0
    monkeypatch.setattr(move_in.time, "monotonic", lambda: now)
    for _ in range(3):
        move_in.charge_move_request(1, 10)
    with pytest.raises(OctopError) as limited:
        move_in.charge_move_request(1, 10)
    assert limited.value.code == ErrorCode.BOT_MOVE_IN_LIMITED
    move_in.charge_move_request(2, 900)
    with pytest.raises(OctopError):
        move_in.charge_move_request(2, 200)

    now += 3600
    move_in.charge_move_request(1, 10)
    move_in.charge_move_request(1, 10)
    with pytest.raises(OctopError):
        move_in.charge_move_request(1, 10)
    now += 86400
    move_in.charge_move_request(1, 10)
    assert 2 not in move_in._move_usage
