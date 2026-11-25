"""The service credential and operational computer lifecycle."""

import asyncio
import hashlib
import time
from pathlib import Path
from typing import Any

import pytest

from octop.infra.cloud import ops
from octop.infra.cloud.computers import manager as computers
from octop.infra.cloud.computers.manager import ComputerManager, ComputerRecord, Reservation
from tests.integration.test_octop_bot_cloud import (
    Upstream,
    _sign_in,
    upstream,  # noqa: F401
)
from tests.support.app import octop_client

KEY = "test-secret"
HEADERS = {"X-Octop-Ops-Key": KEY}
BASE = "/api/ops"
OPERATOR = {"operatorId": "test-operator", "operatorName": "Test", "reason": "test"}


class Driver:
    def __init__(self) -> None:
        self.stops = 0
        self.pauses = 0

    def disk_gb(self, instance: str) -> int:
        return 50

    def state(self, instance: str) -> str:
        return "running"

    def pause(self, instance: str) -> None:
        self.pauses += 1

    def stop(self, instance: str) -> None:
        self.stops += 1


class Billing:
    def __init__(self) -> None:
        self.settled: list[str] = []

    def settle(self, record: Any, reservation: Reservation, used: int) -> None:
        self.settled.append(reservation.id)


async def test_ops_auth(
    tmp_octop_home: Path,
    upstream: Upstream,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OCTOP_OPS_KEY_SHA256", raising=False)
    monkeypatch.delenv("OCTOP_OPS_ALLOWED_IPS", raising=False)
    async with octop_client(tmp_octop_home) as (client, _):
        assert (await client.get(BASE + "/summary")).json()["error"]["code"] == "ops_unconfigured"
        monkeypatch.setenv("OCTOP_OPS_KEY_SHA256", hashlib.sha256(KEY.encode()).hexdigest())
        assert (await client.get(BASE + "/summary")).status_code == 401
        assert (
            await client.get(BASE + "/summary", headers={"X-Octop-Ops-Key": "wrong"})
        ).status_code == 401
        assert (await client.get(BASE + "/summary", headers=HEADERS)).status_code == 200
        monkeypatch.setenv("OCTOP_OPS_ALLOWED_IPS", "192.0.2.0/24")
        assert (await client.get(BASE + "/summary", headers=HEADERS)).status_code == 403
        # Outside the allowlist, a wrong or missing key gets the same answer.
        assert (
            await client.get(BASE + "/summary", headers={"X-Octop-Ops-Key": "wrong"})
        ).status_code == 403
        assert (await client.get(BASE + "/summary")).status_code == 403
        monkeypatch.setenv("OCTOP_OPS_ALLOWED_IPS", "127.0.0.0/8")
        assert (await client.get(BASE + "/summary", headers=HEADERS)).status_code == 200
        monkeypatch.setenv("OCTOP_BOT_CLOUD", "0")
        assert (await client.get(BASE + "/summary", headers=HEADERS)).status_code == 404


async def test_daily_quota_reserves_each_slot_once(
    tmp_octop_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ops, "DELETE_DISK_DAILY_LIMIT", 2)
    async with octop_client(tmp_octop_home) as (_, server):
        service = ops.OpsService(server.services)
        results = await asyncio.gather(
            *(asyncio.to_thread(service._reserve_delete, "test:daily-quota") for _ in range(5))
        )
        assert results.count(True) == 2
        assert server.services.settings_repo.get("test:daily-quota") == "2"


async def test_ops_computers(
    tmp_octop_home: Path,
    upstream: Upstream,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOP_OPS_KEY_SHA256", hashlib.sha256(KEY.encode()).hexdigest())
    monkeypatch.delenv("OCTOP_OPS_ALLOWED_IPS", raising=False)
    async with octop_client(tmp_octop_home) as (client, server):
        login = await _sign_in(client, "13800000001")
        uid = login["user"]["id"]
        driver, billing = Driver(), Billing()
        manager = ComputerManager(server.services, driver, billing=billing)  # type: ignore[arg-type]
        monkeypatch.setattr(ops, "computer_manager", lambda services: manager)
        now = time.time()
        for index in range(3):
            agent = f"bot-{index}"
            server.services.agent_repo.create(agent_id=agent, user_id=uid, name=agent)
            record = ComputerRecord(
                agent_id=agent,
                user_id=uid,
                instance_id=f"ins-test-{index}",
                running=True,
                running_since=now - 30,
                started_at=now - 30,
                active_at=now - index,
                reservations=[Reservation(agent, 5)],
            )
            if index == 2:
                record.reminded_at, record.reclaim_at = now - 100, now - 10
            manager._save(record)
        assert (await client.get(BASE + "/users/missing", headers=HEADERS)).status_code == 404
        listing = await client.get(BASE + "/computers", params={"limit": 2}, headers=HEADERS)
        assert len(listing.json()["items"]) == 2
        page = await client.get(
            BASE + "/computers",
            params={"limit": 2, "cursor": listing.json()["nextCursor"]},
            headers=HEADERS,
        )
        assert len(page.json()["items"]) == 1
        pending = await client.get(
            BASE + "/computers", params={"reclaimState": "pending_reclaim"}, headers=HEADERS
        )
        assert [item["computerId"] for item in pending.json()["items"]] == ["bot-2"]
        stop = BASE + "/computers/bot-0/stop"
        assert (await client.post(stop, headers=HEADERS, json=OPERATOR)).json()[
            "status"
        ] == "stopped"
        assert (await client.post(stop, headers=HEADERS, json=OPERATOR)).status_code == 200
        delete = BASE + "/computers/bot-1/delete-disk"
        assert (
            await client.post(delete, headers=HEADERS, json={**OPERATOR, "confirm": "wrong"})
        ).status_code == 400
        for _ in range(2):
            response = await client.post(
                delete, headers=HEADERS, json={**OPERATOR, "confirm": "bot-1"}
            )
            assert response.json()["reclaimState"] == "reclaimed"
        assert driver.pauses == 1 and driver.stops == 1
        assert billing.settled == ["bot-0", "bot-1"]
        assert len(server.services.audit_repo.query(action="ops.delete_disk")) == 2
        # Disk deletions are capped per Beijing day; replays above did not count twice.
        counter = "octop_bot:ops:deletes:" + computers.beijing_day(time.time())
        assert server.services.settings_repo.get(counter) == "1"
        server.services.settings_repo.set(counter, str(ops.DELETE_DISK_DAILY_LIMIT))
        limited = await client.post(
            BASE + "/computers/bot-2/delete-disk",
            headers=HEADERS,
            json={**OPERATOR, "confirm": "bot-2"},
        )
        assert limited.status_code == 429
        assert limited.json()["error"]["code"] == "ops_delete_limit"
        assert driver.stops == 1


async def test_every_ops_route_requires_the_ops_key(
    tmp_octop_home: Path,
    upstream: Upstream,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """/api/ops/ skips user sessions, so every route there must refuse callers without the key."""
    monkeypatch.setenv("OCTOP_OPS_KEY_SHA256", hashlib.sha256(KEY.encode()).hexdigest())
    monkeypatch.delenv("OCTOP_OPS_ALLOWED_IPS", raising=False)
    async with octop_client(tmp_octop_home) as (client, _):
        from fastapi.routing import APIRoute

        from octop.api.routers import ops as ops_router

        routes = [
            (method, ("/api/ops" + route.path).replace("{", "").replace("}", ""))
            for route in ops_router.router.routes
            if isinstance(route, APIRoute)
            for method in route.methods
        ]
        assert len(routes) >= 6
        for method, path in routes:
            response = await client.request(method, path, json={})
            assert response.status_code == 401, (method, path, response.status_code)
