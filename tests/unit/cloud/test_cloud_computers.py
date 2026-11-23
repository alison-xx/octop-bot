"""A Bot's cloud computer: started on first use, paused when idle, billed by the minute."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from octop.infra.cloud.computers import manager as computers
from octop.infra.cloud.computers.backend import CloudComputer
from octop.infra.cloud.computers.driver import AgsConfig, State, state_of
from octop.infra.errors import ErrorCode, OctopError


class Settings:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str) -> None:
        self.data[key] = value

    def with_prefix(self, prefix: str) -> dict[str, str]:
        return {k: v for k, v in self.data.items() if k.startswith(prefix)}


class Services:
    def __init__(self) -> None:
        self.settings_repo = Settings()


class Driver:
    def __init__(self) -> None:
        self.states: dict[str, State] = {}
        self.calls: list[tuple[str, str]] = []
        self.files: dict[str, bytes] = {}
        self.fail_start = False

    def start(self, *, spec: str, labels: Mapping[str, str]) -> str:
        if self.fail_start:
            raise RuntimeError("no capacity")
        instance = f"ins-{len(self.states) + 1}"
        self.states[instance] = "running"
        self.calls.append(("start", labels["octop-bot"]))
        return instance

    def resume(self, instance_id: str) -> None:
        self.states[instance_id] = "running"
        self.calls.append(("resume", instance_id))

    def pause(self, instance_id: str) -> None:
        self.states[instance_id] = "paused"
        self.calls.append(("pause", instance_id))

    def stop(self, instance_id: str) -> None:
        self.states[instance_id] = "gone"

    def state(self, instance_id: str) -> State:
        return self.states.get(instance_id, "gone")

    def run(self, instance_id: str, command: str, timeout: int) -> tuple[int, str]:
        assert self.states[instance_id] == "running"
        return 0, f"ran {command}"

    def write(self, instance_id: str, path: str, data: bytes) -> None:
        self.files[path] = data

    def read(self, instance_id: str, path: str) -> bytes | None:
        return self.files.get(path)


class Billing:
    def __init__(self) -> None:
        self.reserved: list[int] = []
        self.settled: list[tuple[str, int]] = []
        self.broke = False

    def reserve(self, record: Any, minutes: int) -> computers.Reservation:
        if self.broke:
            raise OctopError.localized(ErrorCode.BOT_CLOUD_CREDITS_REQUIRED)
        self.reserved.append(minutes)
        return computers.Reservation(f"r{len(self.reserved)}", minutes)

    def settle(self, record: Any, reservation: computers.Reservation, used: int) -> None:
        self.settled.append((reservation.id, used))


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def setup(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[computers.ComputerManager, Driver, Billing, Clock]:
    monkeypatch.setattr(computers.ComputerManager, "_start_reaper", lambda self: None)
    driver, billing, clock = Driver(), Billing(), Clock()
    manager = computers.ComputerManager(Services(), driver, billing=billing, clock=clock)  # type: ignore[arg-type]
    return manager, driver, billing, clock


def test_first_use_starts_and_pays_for_a_chunk(setup: Any) -> None:
    manager, driver, billing, clock = setup
    computer = CloudComputer(manager, user_id=7, agent_id="bot1")
    assert computer.execute("ls").output == "ran ls"
    assert driver.calls == [("start", "bot1")]
    assert billing.reserved == [computers.CHUNK_MINUTES]
    # Still running: no second start, no second charge.
    computer.execute("pwd")
    assert driver.calls == [("start", "bot1")] and billing.reserved == [5]


def test_idle_computers_pause_and_settle_by_the_second(setup: Any) -> None:
    manager, driver, billing, clock = setup
    CloudComputer(manager, user_id=7, agent_id="bot1").execute("ls")
    clock.now += 3 * 60
    manager.tick()  # the first chunk still covers it
    assert driver.calls == [("start", "bot1")] and billing.reserved == [5]
    clock.now += 60
    manager.tick()  # a minute before it runs out, the next chunk is bought
    assert billing.reserved == [5, 5]
    clock.now += computers.IDLE_PAUSE_SECONDS - 4 * 60
    manager.tick()
    assert driver.calls[-1] == ("pause", "ins-1")
    # Ten minutes of running, settled chunk by chunk.
    assert billing.settled == [("r1", 300), ("r2", 300)]


def test_a_paused_computer_resumes_with_its_files(setup: Any) -> None:
    manager, driver, billing, clock = setup
    computer = CloudComputer(manager, user_id=7, agent_id="bot1")
    computer.upload_files([("/root/notes.md", b"hi")])
    manager.pause("bot1", 7)
    clock.now += 60
    assert computer.download_files(["/root/notes.md"])[0].content == b"hi"
    assert driver.calls == [("start", "bot1"), ("pause", "ins-1"), ("resume", "ins-1")]
    assert computer.download_files(["/missing"])[0].error == "file_not_found"


def test_busy_computers_buy_the_next_chunk_or_pause_without_credits(setup: Any) -> None:
    manager, driver, billing, clock = setup
    computer = CloudComputer(manager, user_id=7, agent_id="bot1")
    computer.execute("ls")
    clock.now += 4 * 60 + 30
    manager.touch("bot1", 7)
    manager.tick()
    assert billing.reserved == [5, 5]
    clock.now += 5 * 60
    manager.touch("bot1", 7)
    billing.broke = True
    manager.tick()
    assert driver.calls[-1] == ("pause", "ins-1")
    assert [used for _, used in billing.settled] == [300, 270]
    with pytest.raises(OctopError):
        computer.execute("ls")


def test_a_failed_start_refunds_the_chunk(setup: Any) -> None:
    manager, driver, billing, clock = setup
    driver.fail_start = True
    with pytest.raises(RuntimeError):
        CloudComputer(manager, user_id=7, agent_id="bot1").execute("ls")
    assert billing.settled == [("r1", 0)]


def test_ags_config_and_states() -> None:
    assert AgsConfig.from_env({}) is None
    config = AgsConfig.from_env(
        {
            "OCTOP_AGS_SECRET_ID": "id",
            "OCTOP_AGS_SECRET_KEY": "key",
            "OCTOP_AGS_API_KEY": "e2b_x",
            "OCTOP_AGS_TOOL": "octop-bot-desktop",
        }
    )
    assert config is not None
    assert config.domain == "ap-guangzhou.tencentags.com"
    assert config.tools == {"standard": "octop-bot-desktop", "pro": "octop-bot-desktop"}
    assert state_of("RUNNING") == "running" and state_of("PAUSED") == "paused"
    assert state_of("STOPPED") == "gone" and state_of(None) == "gone"


def test_finished_chunks_are_settled_while_the_computer_keeps_running(setup: Any) -> None:
    manager, driver, billing, clock = setup
    computer = CloudComputer(manager, user_id=7, agent_id="bot1")
    computer.execute("ls")
    for _ in range(3):  # three busy minutes at a time
        clock.now += 3 * 60
        manager.touch("bot1", 7)
        manager.tick()
    # Nine minutes in: chunk one is used up and settled, chunk two is still running.
    assert billing.reserved == [5, 5, 5]
    assert billing.settled == [("r1", 300)]
    manager.pause("bot1", 7)
    assert billing.settled == [("r1", 300), ("r2", 240), ("r3", 0)]
