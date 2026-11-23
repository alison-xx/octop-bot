"""A Bot's cloud computer: started on first use, paused when idle, billed by the minute."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any

import pytest

from octop.infra.cloud.computers import driver as ags
from octop.infra.cloud.computers import manager as computers
from octop.infra.cloud.computers.backend import CloudComputer
from octop.infra.cloud.computers.driver import WORKSPACE, AgsConfig, State, state_of
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

    def delete(self, key: str) -> None:
        self.data.pop(key, None)


class Agents:
    def __init__(self) -> None:
        self.deleted: set[str] = set()

    def get(self, agent_id: str) -> object | None:
        return None if agent_id in self.deleted else object()


class Services:
    def __init__(self) -> None:
        self.settings_repo = Settings()
        self.agent_repo = Agents()


class Driver:
    def __init__(self) -> None:
        self.states: dict[str, State] = {}
        self.calls: list[tuple[str, str]] = []
        self.files: dict[str, bytes] = {}
        self.fail_start = False
        self.broken: set[str] = set()
        self.readied: list[str] = []
        self.clipboard = ""

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
        self.calls.append(("stop", instance_id))

    def wait_ready(self, instance_id: str, timeout: float = 90.0) -> None:
        self.readied.append(instance_id)

    def state(self, instance_id: str) -> State:
        if instance_id in self.broken:
            raise RuntimeError("provider error")
        return self.states.get(instance_id, "gone")

    def run(self, instance_id: str, command: str, timeout: int) -> tuple[int, str]:
        assert self.states[instance_id] == "running"
        return 0, f"ran {command}"

    def write(self, instance_id: str, path: str, data: bytes) -> None:
        self.files[path] = data

    def read(self, instance_id: str, path: str) -> bytes | None:
        return self.files.get(path)

    def screen(self, instance_id: str) -> tuple[str, dict[str, str]]:
        return f"wss://6080-{instance_id}.test/websockify", {"X-Access-Token": "t"}

    def paste_text(self, instance_id: str, text: str) -> None:
        self.clipboard = text

    def read_clipboard(self, instance_id: str) -> str:
        return self.clipboard


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
    # Both the start and the resume waited for the desktop to come up.
    assert driver.readied == ["ins-1", "ins-1"]
    assert computer.download_files(["/missing"])[0].error == "file_not_found"
    assert driver.files == {f"{WORKSPACE}/root/notes.md": b"hi"}


def test_the_agents_root_is_the_workspace_folder(setup: Any) -> None:
    manager, driver, billing, clock = setup
    computer = CloudComputer(manager, user_id=7, agent_id="bot1")
    assert computer._map_path("/") == WORKSPACE
    assert computer._map_path("SOUL.md") == f"{WORKSPACE}/SOUL.md"
    assert computer._map_path(f"{WORKSPACE}/a/b") == f"{WORKSPACE}/a/b"
    assert computer._map_path("/../../etc/passwd") == WORKSPACE
    assert computer._to_virtual_path(f"{WORKSPACE}/a/b.md") == "/a/b.md"
    assert computer._to_virtual_path(WORKSPACE) == "/"
    with pytest.raises(OSError):
        computer.delete_path("/")


def test_commands_outlive_the_desktop_servers_request_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AgsConfig.from_env(
        {"OCTOP_AGS_SECRET_ID": "id", "OCTOP_AGS_SECRET_KEY": "key", "OCTOP_AGS_TOOL": "t"}
    )
    assert config is not None
    scripts: list[str] = []
    replies = [ags._PENDING + "\n", "3\nout\nerr\n"]

    def execute(instance_id: str, script: str) -> str:
        scripts.append(script)
        return replies.pop(0)

    driver = ags.AgsDriver(config)
    monkeypatch.setattr(driver, "_execute", execute)
    assert driver.run("ins", "make build", 600) == (3, "out\nerr\n")
    # The first request launches it detached in the workspace; the second only waits.
    assert "setsid bash -c" in scripts[0] and f"cd {WORKSPACE}" in scripts[0]
    assert "make build" in scripts[0] and "setsid" not in scripts[1]

    replies[:] = [ags._PENDING, "partial"]
    clock = iter([0.0, 0.0, 10.0])
    monkeypatch.setattr(ags.time, "monotonic", lambda: next(clock))
    code, output = driver.run("ins", "sleep 999", 5)
    assert code == 124 and output.startswith("partial") and "timed out" in output
    assert "kill -KILL" in scripts[-1]


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
            "OCTOP_AGS_TOOL": "octop-bot-desktop",
        }
    )
    assert config is not None
    assert config.domain == "ap-guangzhou.tencentags.com"
    assert config.tools == {"standard": "octop-bot-desktop", "pro": "octop-bot-desktop"}
    assert config.timeout is None  # persistent tools take none
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


def test_a_deleted_bots_computer_is_stopped_settled_and_forgotten(setup: Any) -> None:
    manager, driver, billing, clock = setup
    CloudComputer(manager, user_id=7, agent_id="bot1").execute("ls")
    manager._services.agent_repo.deleted.add("bot1")
    clock.now += 60
    manager.tick()
    assert driver.calls[-1] == ("stop", "ins-1")
    assert billing.settled == [("r1", 60)]
    assert manager._services.settings_repo.with_prefix("octop_bot:computer:") == {}


def test_a_vanished_instance_closes_billing_and_starts_fresh(setup: Any) -> None:
    manager, driver, billing, clock = setup
    computer = CloudComputer(manager, user_id=7, agent_id="bot1")
    computer.execute("ls")
    driver.states["ins-1"] = "gone"  # stopped by its own timeout
    clock.now += 120
    manager.tick()
    assert billing.settled == [("r1", 120)]
    computer.execute("ls")
    assert driver.calls[-1] == ("start", "bot1")


def test_a_long_command_is_not_idle(setup: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    manager, driver, billing, clock = setup

    def slow(instance_id: str, command: str, timeout: int) -> tuple[int, str]:
        clock.now += computers.IDLE_PAUSE_SECONDS + 60
        manager.tick()  # the reaper runs while the command is still going
        return 0, "built"

    monkeypatch.setattr(driver, "run", slow)
    assert CloudComputer(manager, user_id=7, agent_id="bot1").execute("make").output == "built"
    assert ("pause", "ins-1") not in driver.calls


def test_a_stale_snapshot_never_renews_a_paused_computer(setup: Any) -> None:
    manager, driver, billing, clock = setup
    CloudComputer(manager, user_id=7, agent_id="bot1").execute("ls")
    stale = manager.record("bot1", 7)
    manager.pause("bot1", 7)
    clock.now += 5 * 60
    manager._tick_one(stale, clock.now)
    assert billing.reserved == [5]


def test_one_broken_computer_does_not_hold_up_the_others(setup: Any) -> None:
    manager, driver, billing, clock = setup
    CloudComputer(manager, user_id=7, agent_id="bot1").execute("ls")
    CloudComputer(manager, user_id=8, agent_id="bot2").execute("ls")
    driver.broken.add("ins-1")
    clock.now += 4 * 60 + 30
    manager.touch("bot2", 8)
    manager.tick()
    assert billing.reserved == [5, 5, 5]  # bot2 still bought its next chunk


def test_a_taken_over_computer_turns_the_bot_away_and_stays_awake(setup: Any) -> None:
    manager, driver, billing, clock = setup
    computer = CloudComputer(manager, user_id=7, agent_id="bot1")
    computer.execute("ls")
    manager.set_takeover("bot1", 7, True)
    blocked = computer.execute("rm -rf /tmp/x")
    assert blocked.exit_code == 1 and "taken over" in blocked.output
    clock.now += computers.IDLE_PAUSE_SECONDS * 2
    manager.touch("bot1", 7)  # keeps paying in the meantime
    manager.tick()
    assert ("pause", "ins-1") not in driver.calls
    manager.set_takeover("bot1", 7, False)
    assert computer.execute("ls").exit_code == 0


def test_a_watched_screen_keeps_the_computer_running(setup: Any) -> None:
    manager, driver, billing, clock = setup
    url, headers = manager.screen("bot1", 7)
    assert url == "wss://6080-ins-1.test/websockify" and headers == {"X-Access-Token": "t"}
    clock.now += computers.IDLE_PAUSE_SECONDS + 10
    manager.viewing("bot1", 7)
    manager.tick()
    assert ("pause", "ins-1") not in driver.calls
    clock.now += computers.VIEWER_GRACE_SECONDS + computers.IDLE_PAUSE_SECONDS
    manager.tick()
    assert driver.calls[-1] == ("pause", "ins-1")


def test_the_screen_starts_the_vnc_bridge_once(monkeypatch: pytest.MonkeyPatch) -> None:
    config = AgsConfig.from_env(
        {"OCTOP_AGS_SECRET_ID": "id", "OCTOP_AGS_SECRET_KEY": "key", "OCTOP_AGS_TOOL": "t"}
    )
    assert config is not None
    driver = ags.AgsDriver(config)
    scripts: list[str] = []
    uploads: list[str] = []
    listening = ["down"]
    monkeypatch.setattr(driver, "_execute", lambda i, s: scripts.append(s) or listening[0])
    monkeypatch.setattr(driver, "write", lambda i, path, data: uploads.append(path))
    monkeypatch.setattr(driver, "token", lambda i, fresh=False: "tok")
    url, headers = driver.screen("ins")
    assert url == "wss://8080-ins.ap-guangzhou.tencentags.com/websockify"
    assert headers == {"X-Access-Token": "tok"}
    assert uploads == [ags._BRIDGE] and "nohup python3" in scripts[-1]
    listening[0] = "up"
    driver.screen("ins")
    assert uploads == [ags._BRIDGE]  # already running: nothing uploaded or started


def test_typing_and_the_clipboard_need_takeover(setup: Any) -> None:
    manager, driver, billing, clock = setup
    CloudComputer(manager, user_id=7, agent_id="bot1").execute("ls")
    with pytest.raises(OctopError) as refused:
        manager.paste_text("bot1", 7, "你好")
    assert refused.value.code == ErrorCode.BOT_COMPUTER_NOT_TAKEN_OVER
    manager.set_takeover("bot1", 7, True)
    manager.paste_text("bot1", 7, "你好，云电脑")
    assert manager.read_clipboard("bot1", 7) == "你好，云电脑"


def test_pasting_sends_text_as_base64_and_presses_the_paste_shortcut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AgsConfig.from_env(
        {"OCTOP_AGS_SECRET_ID": "id", "OCTOP_AGS_SECRET_KEY": "key", "OCTOP_AGS_TOOL": "t"}
    )
    assert config is not None
    driver = ags.AgsDriver(config)
    scripts: list[str] = []
    monkeypatch.setattr(driver, "_execute", lambda i, s: scripts.append(s) or "pasted\n")
    driver.paste_text("ins", "你好'; rm -rf ~")
    encoded = base64.b64encode("你好'; rm -rf ~".encode()).decode()
    assert f"printf %s {encoded} | base64 -d | xclip -selection clipboard -i" in scripts[0]
    assert "rm -rf" not in scripts[0] and "xtest.fake_input" in scripts[0]
    # The clipboard is read back before the paste key is pressed; a miss is an error.
    monkeypatch.setattr(driver, "_execute", lambda i, s: "")
    with pytest.raises(RuntimeError):
        driver.paste_text("ins", "你好")


def test_billing_is_lynxce_credits_in_the_cloud_unless_turned_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOP_BOT_CLOUD", "1")
    monkeypatch.delenv("OCTOP_BOT_COMPUTE_BILLING", raising=False)
    assert isinstance(computers.billing_for(Services()), computers.Billing)  # type: ignore[arg-type]
    monkeypatch.setenv("OCTOP_BOT_COMPUTE_BILLING", "off")
    free = computers.billing_for(Services())  # type: ignore[arg-type]
    assert isinstance(free, computers.FreeBilling)
    record = computers.ComputerRecord(agent_id="bot1", user_id=7)
    free.settle(record, free.reserve(record, 5), 300)
    # A self-hosted server (not the cloud) never bills Lynxce for its own AGS account.
    monkeypatch.delenv("OCTOP_BOT_CLOUD")
    monkeypatch.delenv("OCTOP_BOT_COMPUTE_BILLING")
    assert isinstance(computers.billing_for(Services()), computers.FreeBilling)  # type: ignore[arg-type]
