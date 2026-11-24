"""A Bot's cloud computer: started on first use, paused when idle, billed by the minute."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any

import pytest

from octop.infra.cloud.computers import driver as ags
from octop.infra.cloud.computers import driver as driver_module
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
        self.shadows: list[Any] = []

    def get(self, agent_id: str) -> object | None:
        return None if agent_id in self.deleted else object()

    def list_shadows(self, user_id: int | None = None) -> list[Any]:
        return [s for s in self.shadows if s.agent_id not in self.deleted]

    def delete(self, agent_id: str) -> None:
        self.deleted.add(agent_id)


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
        # AGS account quota: at most this many running at once (None: unlimited).
        self.capacity: int | None = None
        self.broken: set[str] = set()
        self.readied: list[str] = []
        self.clipboard = ""
        self.stopped: dict[str, float] = {}

        self.listed: list[driver_module.Instance] = []
        self.commands: list[str] = []
        self.mtimes: dict[str, float] = {}
        self.clock = 0.0

    def start(self, *, spec: str, labels: Mapping[str, str]) -> str:
        if self.fail_start:
            raise RuntimeError("no capacity")
        self._check_capacity()
        instance = f"ins-{len(self.states) + 1}"
        self.states[instance] = "running"
        self.calls.append(("start", labels["octop-bot"]))
        return instance

    def _check_capacity(self) -> None:
        from tencentcloud.common.exception.tencent_cloud_sdk_exception import (
            TencentCloudSDKException,
        )

        running = sum(1 for state in self.states.values() if state == "running")
        if self.capacity is not None and running >= self.capacity:
            raise TencentCloudSDKException("LimitExceeded.SandboxInstance", "quota", "req")

    def resume(self, instance_id: str) -> None:
        self._check_capacity()
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

    def stopped_at(self, instance_id: str) -> float | None:
        return self.stopped.get(instance_id)

    def instances(self) -> list[driver_module.Instance]:
        return self.listed

    def run(self, instance_id: str, command: str, timeout: int) -> tuple[int, str]:
        assert self.states[instance_id] == "running"
        self.commands.append(command)
        if "find generated outbound" in command:  # the deliverables listing
            lines = [
                f"{len(data)} {self.mtimes.get(path, 1.0)} {path[len(WORKSPACE) + 1 :]}"
                for path, data in self.files.items()
                if path.startswith((f"{WORKSPACE}/generated/", f"{WORKSPACE}/outbound/"))
            ]
            return 0, "\n".join(lines)
        if command.startswith("make "):  # a command that leaves a deliverable behind
            target = f"{WORKSPACE}/generated/{command.split()[1]}"
            self.write(instance_id, target, b"made on the computer")
        return 0, f"ran {command}"

    def write(self, instance_id: str, path: str, data: bytes) -> None:
        self.files[path] = data
        self.clock += 1
        self.mtimes[path] = self.clock

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
        self.settle_down = False
        self.settle_refused = False

    def reserve(self, record: Any, minutes: int) -> computers.Reservation:
        if self.broke:
            raise OctopError.localized(ErrorCode.BOT_CLOUD_CREDITS_REQUIRED)
        self.reserved.append(minutes)
        return computers.Reservation(f"r{len(self.reserved)}", minutes)

    def settle(self, record: Any, reservation: computers.Reservation, used: int) -> None:
        if self.settle_down:
            raise RuntimeError("Lynxce unavailable")
        if self.settle_refused:
            raise OctopError.localized(ErrorCode.NOT_FOUND)
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


def test_a_cloud_bot_is_rooted_at_its_workspace_so_the_model_never_sees_host_paths(
    setup: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from octop.infra.backend.resolver import resolve_agent_backend_spec

    manager, *_ = setup
    monkeypatch.setattr(computers, "_manager", manager)
    monkeypatch.delenv("OCTOP_FILE_STORE_BUCKET", raising=False)
    spec = {"type": "bot_cloud", "user_id": 7, "agent_id": "bot1"}
    computer = resolve_agent_backend_spec(spec, repo=None, workspace_dir=tmp_path)
    assert isinstance(computer, CloudComputer)
    # The harness shows a virtual backend's workspace relative to root_dir: "/" here.
    assert computer.virtual_mode and computer.root_dir == tmp_path


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


def test_out_of_capacity_pauses_the_longest_idle_computer_and_retries(setup: Any) -> None:
    manager, driver, billing, clock = setup
    driver.capacity = 2
    CloudComputer(manager, user_id=7, agent_id="old").execute("ls")
    clock.now += 60
    CloudComputer(manager, user_id=8, agent_id="recent").execute("ls")
    clock.now += computers.MAKE_ROOM_IDLE_SECONDS
    assert CloudComputer(manager, user_id=9, agent_id="new").execute("ls").output == "ran ls"
    # The longest-idle computer made room; the other keeps running.
    assert ("pause", "ins-1") in driver.calls
    assert manager.is_running("recent", 8) and manager.is_running("new", 9)
    assert not manager.is_running("old", 7)


def test_out_of_capacity_never_pauses_a_computer_in_use(setup: Any) -> None:
    manager, driver, billing, clock = setup
    driver.capacity = 1
    CloudComputer(manager, user_id=7, agent_id="busy").execute("ls")
    clock.now += 30  # acted on just now
    computer = CloudComputer(manager, user_id=9, agent_id="new")
    reply = computer.execute("ls")
    # The Bot is told plainly, and the reserved chunk is refunded.
    assert reply.exit_code == 1 and "no cloud computer is free" in reply.output
    assert billing.settled == [("r2", 0)]
    assert manager.is_running("busy", 7)
    with pytest.raises(OctopError) as refused:
        manager.ensure_running("new", 9)
    assert refused.value.code == ErrorCode.BOT_COMPUTER_BUSY


def test_capacity_errors_are_told_apart() -> None:
    from tencentcloud.common.exception.tencent_cloud_sdk_exception import (
        TencentCloudSDKException,
    )

    assert computers.capacity_full(TencentCloudSDKException("LimitExceeded.SandboxInstance"))
    assert computers.capacity_full(TencentCloudSDKException("LimitExceeded"))
    assert not computers.capacity_full(TencentCloudSDKException("RequestLimitExceeded"))
    assert not computers.capacity_full(TencentCloudSDKException("LimitExceeded.APIKeyQuota"))
    assert not computers.capacity_full(RuntimeError("no capacity"))
    # CVM: a type sold out in every zone, wrapped by the driver after the last zone.
    sold_out = TencentCloudSDKException("ResourcesSoldOut.SpecifiedInstanceType")
    try:
        raise RuntimeError("no zone has a SA9.LARGE8 available") from sold_out
    except RuntimeError as wrapped:
        assert computers.capacity_full(wrapped)
    assert computers.capacity_full(TencentCloudSDKException("LimitExceeded.InstanceQuota"))


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
    # Files the Bot writes onto the computer wait too.
    assert computer.upload_files([("/notes.md", b"x")])[0].error == blocked.output
    for _ in range(int(computers.IDLE_PAUSE_SECONDS * 2 / 30)):
        clock.now += 30
        manager.viewing("bot1", 7)  # the open screen's heartbeat
        manager.tick()
    assert ("pause", "ins-1") not in driver.calls
    manager.set_takeover("bot1", 7, False)
    assert computer.execute("ls").exit_code == 0


def test_a_takeover_no_one_watches_goes_back_to_the_bot(setup: Any) -> None:
    manager, driver, billing, clock = setup
    computer = CloudComputer(manager, user_id=7, agent_id="bot1")
    computer.execute("ls")
    manager.set_takeover("bot1", 7, True)  # e.g. a phone took over, then left the page
    clock.now += computers.VIEWER_GRACE_SECONDS + 1
    assert not manager.taken_over("bot1", 7)
    assert computer.execute("ls").exit_code == 0
    manager.tick()
    assert manager.record("bot1", 7).takeover is False


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


# -- review fixes (PR #22) -------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Any) -> Any:
    from deepagents.backends.filesystem import FilesystemBackend

    backend = FilesystemBackend(root_dir=str(tmp_path), virtual_mode=True)
    backend.upload_files(
        [
            ("/SOUL.md", b"# Soul"),
            ("/.octop/.bootstrapped", b"1"),
            ("/notes/plan.md", b"old plan"),
            ("/inbound/photo.png", b"png"),
        ]
    )
    return backend


def test_reading_the_bots_context_never_starts_its_computer(setup: Any, store: Any) -> None:
    manager, driver, billing, clock = setup
    computer = CloudComputer(manager, user_id=7, agent_id="bot1", store=store)
    assert "Soul" in str(computer.read("/SOUL.md").file_data)
    assert computer.download_files(["/.octop/.bootstrapped"])[0].content == b"1"
    assert {e["path"] for e in computer.ls("/").entries} >= {"/SOUL.md", "/notes/"}
    computer.write("/MEMORY.md", "remember this")
    computer.upload_files([("/inbound/doc.pdf", b"pdf")])
    assert driver.calls == [] and billing.reserved == []
    assert store.download_files(["/MEMORY.md"])[0].content == b"remember this"


def test_a_bots_first_computer_gets_its_existing_files_once(setup: Any, store: Any) -> None:
    manager, driver, billing, clock = setup
    computer = CloudComputer(manager, user_id=7, agent_id="bot1", store=store)
    computer.execute("ls")
    assert driver.files == {f"{WORKSPACE}/notes/plan.md": b"old plan"}
    assert manager.record("bot1", 7).seeded
    # A later fresh computer (the old one was reclaimed) is not filled with stale copies.
    driver.states["ins-1"] = "gone"
    driver.files.clear()
    manager.tick()
    computer.execute("ls")
    assert driver.calls[-1] == ("start", "bot1") and driver.files == {}


def test_deleting_follows_the_path_mapping(setup: Any, store: Any) -> None:
    manager, driver, billing, clock = setup
    computer = CloudComputer(manager, user_id=7, agent_id="bot1", store=store)
    computer.delete("/SOUL.md")
    assert store.download_files(["/SOUL.md"])[0].content is None
    assert driver.calls == []
    ran: list[str] = []
    driver.run = lambda instance, command, timeout: ran.append(command) or (0, "")  # type: ignore[method-assign]
    computer.delete("/notes/plan.md")
    assert any(f"{WORKSPACE}/notes/plan.md" in c for c in ran)
    assert not any("rm -rf /notes" in c or "'/notes/plan.md'" in c for c in ran)
    assert computer.delete("/").error


def test_a_start_that_fails_is_refunded_and_orphans_are_stopped(setup: Any) -> None:
    manager, driver, billing, clock = setup
    driver.fail_start = True
    with pytest.raises(RuntimeError):
        CloudComputer(manager, user_id=7, agent_id="bot1").execute("ls")
    mine = manager.server_id()
    old = clock.now - computers.ORPHAN_AGE_SECONDS - 1
    driver.listed = [
        driver_module.Instance("lost", "running", {"octop-server": mine}, old),
        driver_module.Instance("young", "running", {"octop-server": mine}, clock.now),
        driver_module.Instance("other-server", "running", {"octop-server": "x"}, old),
    ]
    clock.now += computers.ORPHAN_SCAN_SECONDS
    manager.tick()
    assert ("stop", "lost") in driver.calls
    assert ("stop", "young") not in driver.calls
    assert ("stop", "other-server") not in driver.calls


def test_failed_settles_are_kept_and_retried(setup: Any) -> None:
    manager, driver, billing, clock = setup
    CloudComputer(manager, user_id=7, agent_id="bot1").execute("ls")
    clock.now += 120
    billing.settle_down = True
    manager.pause("bot1", 7)
    assert billing.settled == []
    assert [u.used_seconds for u in manager.record("bot1", 7).unsettled] == [120]
    billing.settle_down = False
    manager.tick()
    assert billing.settled == [("r1", 120)]
    assert manager.record("bot1", 7).unsettled == []


def test_running_past_the_reservations_is_billed(setup: Any) -> None:
    manager, driver, billing, clock = setup
    CloudComputer(manager, user_id=7, agent_id="bot1").execute("ls")
    clock.now += 8 * 60  # the reaper never ran: 3 minutes past the paid chunk
    manager.pause("bot1", 7)
    assert billing.reserved == [5, 3]
    assert billing.settled == [("r1", 300), ("r2", 180)]


def test_releasing_an_instance_aws_already_reclaimed_does_not_retry_forever(setup: Any) -> None:
    manager, driver, billing, clock = setup
    CloudComputer(manager, user_id=7, agent_id="bot1").execute("ls")
    driver.states["ins-1"] = "gone"
    manager._services.agent_repo.deleted.add("bot1")
    manager.tick()
    assert ("stop", "ins-1") not in driver.calls
    assert manager._services.settings_repo.with_prefix("octop_bot:computer:") == {}


def test_the_shown_start_time_survives_settling_chunks(setup: Any) -> None:
    manager, driver, billing, clock = setup
    CloudComputer(manager, user_id=7, agent_id="bot1").execute("ls")
    started = manager.record("bot1", 7).started_at
    for _ in range(3):
        clock.now += 4 * 60 + 30
        manager.touch("bot1", 7)
        manager.tick()
    record = manager.record("bot1", 7)
    assert record.started_at == started and record.running_since != started


def test_close_stops_the_reaper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(computers, "REAP_INTERVAL_SECONDS", 0.01)
    manager = computers.ComputerManager(Services(), Driver(), billing=Billing())  # type: ignore[arg-type]
    manager._start_reaper()
    assert manager._reaper is not None and manager._reaper.is_alive()
    manager.close()
    assert not manager._reaper.is_alive()


def test_compute_billing_carries_the_cloud_server_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from octop.infra.auth import lynxce_cloud

    settle = "/api/billing/octop-bot/compute/settle"
    monkeypatch.delenv("OCTOP_BOT_COMPUTE_SERVICE_KEY", raising=False)
    assert lynxce_cloud._service_headers(settle) == {}
    monkeypatch.setenv("OCTOP_BOT_COMPUTE_SERVICE_KEY", "k" * 32)
    assert lynxce_cloud._service_headers(settle) == {"X-Octop-Service-Key": "k" * 32}
    # Only compute billing: other tenant calls never carry the server's key.
    assert lynxce_cloud._service_headers("/api/user/personal-api-keys") == {}


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


def test_the_floating_screen_knows_what_the_bot_is_doing(setup: Any) -> None:
    manager, driver, billing, clock = setup
    assert manager.glance("bot1", 7) is None  # off: a glance never starts the computer
    assert driver.calls == []
    CloudComputer(manager, user_id=7, agent_id="bot1").execute("ls")
    assert manager.activity("bot1") == ("command", clock.now)
    assert manager.busy("bot1")
    clock.now += computers.BUSY_AFTER_ACTION_SECONDS + 1
    assert not manager.busy("bot1")
    scripts: list[str] = []

    def glance_script(instance: str, code: str) -> str:
        scripts.append(code)
        return "WINDOW:Sign in to GitHub - Google Chrome\nTHUMB:abc"

    driver.run_python = glance_script  # type: ignore[attr-defined]
    glance = manager.glance("bot1", 7)
    assert glance == computers.Glance(window="Sign in to GitHub - Google Chrome", thumbnail="abc")
    manager.glance("bot1", 7)
    assert len(scripts) == 1  # cached for a few seconds, shared by every viewer


def test_legacy_root_system_files_stay_in_the_store() -> None:
    from octop.infra.cloud.computers.backend import on_store

    for path in ("/.bootstrapped", "/manifest.json", "/.octop-auth/token", "/.octop/x"):
        assert on_store(path), path
    assert not on_store("/notes/manifest.json")


def test_creating_a_bot_does_not_start_its_computer() -> None:
    from octop.infra.cloud.computers.backend import on_store

    # The harness checks the built-in sub-agents here whenever a Bot is created.
    assert on_store("/agents/general-purpose.md")
    assert not on_store("/agents-notes.md")


def test_a_computer_stopped_while_the_server_was_down_is_billed_until_it_stopped(
    setup: Any,
) -> None:
    manager, driver, billing, clock = setup
    CloudComputer(manager, user_id=7, agent_id="bot1").execute("ls")
    started = clock.now
    driver.states["ins-1"] = "gone"
    driver.stopped["ins-1"] = started + 90  # AGS stopped it 90 s in
    clock.now += 3 * 3600  # and this server was down for hours
    manager.tick()
    assert billing.settled == [("r1", 90)]
    assert billing.reserved == [5]  # nothing billed past the stop


def test_without_a_stop_time_only_paid_time_is_billed(setup: Any) -> None:
    manager, driver, billing, clock = setup
    CloudComputer(manager, user_id=7, agent_id="bot1").execute("ls")
    driver.states["ins-1"] = "gone"
    clock.now += 3 * 3600
    manager.tick()
    assert billing.settled == [("r1", 300)] and billing.reserved == [5]


def test_settles_lynxce_refuses_or_that_keep_failing_are_dropped(setup: Any) -> None:
    manager, driver, billing, clock = setup
    CloudComputer(manager, user_id=7, agent_id="bot1").execute("ls")
    billing.settle_refused = True  # e.g. Lynxce no longer knows the reservation
    manager.pause("bot1", 7)
    assert manager.record("bot1", 7).unsettled == []
    billing.settle_refused = False

    CloudComputer(manager, user_id=7, agent_id="bot1").execute("ls")
    billing.settle_down = True
    manager.pause("bot1", 7)
    for _ in range(computers.MAX_SETTLE_ATTEMPTS):
        manager.tick()
    assert manager.record("bot1", 7).unsettled == []
    # A deleted Bot's record is not held forever by a settle that never lands.
    manager._services.agent_repo.deleted.add("bot1")
    manager.tick()
    assert manager._services.settings_repo.with_prefix("octop_bot:computer:") == {}


def test_a_failed_start_keeps_a_failed_refund(setup: Any) -> None:
    manager, driver, billing, clock = setup
    driver.fail_start = True
    billing.settle_down = True
    with pytest.raises(RuntimeError):
        CloudComputer(manager, user_id=7, agent_id="bot1").execute("ls")
    # The refund did not land; it is saved for the reaper rather than lost.
    assert [u.used_seconds for u in manager.record("bot1", 7).unsettled] == [0]


def test_ags_times_without_a_zone_are_utc() -> None:
    assert driver_module._timestamp("2026-11-24T01:44:02") == driver_module._timestamp(
        "2026-11-24T01:44:02+00:00"
    )
    assert driver_module._timestamp("2026-11-24T09:44:02+08:00") == driver_module._timestamp(
        "2026-11-24T01:44:02Z"
    )


def test_one_conversation_at_a_time_drives_the_screen(setup: Any) -> None:
    manager, driver, billing, clock = setup
    assert manager.claim_screen("bot1", "private")
    # A group turn of the same Bot waits while the private chat is still using the screen.
    assert not manager.claim_screen("bot1", "room~bot1")
    assert manager.claim_screen("bot2", "room~bot2")
    clock.now += computers.SCREEN_HOLD_SECONDS - 1
    assert manager.claim_screen("bot1", "private")  # still the holder; its clock restarts
    clock.now += computers.SCREEN_HOLD_SECONDS
    assert manager.claim_screen("bot1", "room~bot1")


def test_deliverables_are_written_and_read_without_the_computer(setup: Any, store: Any) -> None:
    """A document the Bot writes in a chat, an image it generates, a file it sends."""
    manager, driver, billing, clock = setup
    computer = CloudComputer(manager, user_id=7, agent_id="bot1", store=store)
    computer.write("/generated/report.md", "# Report")
    computer.upload_files([("/generated/cat.png", b"png"), ("/outbound/send.pdf", b"pdf")])
    assert computer.download_files(["/generated/cat.png"])[0].content == b"png"
    assert "Report" in str(computer.read("/generated/report.md").file_data)
    assert driver.calls == [] and billing.reserved == []
    assert store.download_files(["/outbound/send.pdf"])[0].content == b"pdf"


def test_deliverables_follow_the_computer_both_ways(setup: Any, store: Any) -> None:
    manager, driver, billing, clock = setup
    computer = CloudComputer(manager, user_id=7, agent_id="bot1", store=store)
    computer.write("/generated/report.md", "# Report")
    # Waking it (any way) copies the store's deliverables onto it.
    computer.execute("ls")
    assert driver.files[f"{WORKSPACE}/generated/report.md"] == b"# Report"
    # A deliverable written while it runs reaches it before the next command ...
    computer.upload_files([("/generated/chart.png", b"chart")])
    computer.execute("python plot.py")
    assert driver.files[f"{WORKSPACE}/generated/chart.png"] == b"chart"
    # ... and what a command leaves on the computer comes back to the store.
    computer.execute("make table.csv")
    got = store.download_files(["/generated/table.csv"])[0]
    assert got.content == b"made on the computer"


def test_a_computer_from_before_mirroring_hands_its_deliverables_to_the_store(
    setup: Any, store: Any
) -> None:
    manager, driver, billing, clock = setup
    computer = CloudComputer(manager, user_id=7, agent_id="bot1", store=store)
    computer.execute("ls")
    manager.pause("bot1", 7)
    driver.files[f"{WORKSPACE}/generated/old.md"] = b"written before"
    # Opening its screen resumes it: its deliverables become readable without it.
    manager.screen("bot1", 7)
    assert store.download_files(["/generated/old.md"])[0].content == b"written before"


def test_reads_that_would_wake_a_paused_computer_are_refused(setup: Any, store: Any) -> None:
    from types import SimpleNamespace

    from octop.infra.cloud.computers.backend import computer_off

    manager, driver, billing, clock = setup
    computer = CloudComputer(manager, user_id=7, agent_id="bot1", store=store)
    workspace = SimpleNamespace(backend=computer)
    assert computer_off(workspace, "notes/plan.md")
    assert not computer_off(workspace, "generated/report.md")
    assert not computer_off(workspace, ".")  # the store's listing
    assert computer_off(workspace, ".", search=True)
    assert not computer_off(SimpleNamespace(backend=store), "notes/plan.md")
    computer.execute("ls")
    assert not computer_off(workspace, "notes/plan.md")


def test_on_cvm_beside_old_ags_computers_nothing_but_work_starts_one(
    monkeypatch: pytest.MonkeyPatch, store: Any
) -> None:
    """Production runs new computers on CVM and keeps older ones on AGS (MixedDriver)."""
    from types import SimpleNamespace

    from octop.infra.cloud.computers.backend import computer_off
    from octop.infra.cloud.computers.mixed import MixedDriver

    monkeypatch.setattr(computers.ComputerManager, "_start_reaper", lambda self: None)
    cvm, ags = Driver(), Driver()
    billing, clock = Billing(), Clock()
    manager = computers.ComputerManager(
        Services(),  # type: ignore[arg-type]
        MixedDriver(cvm, ags),  # type: ignore[arg-type]
        billing=billing,  # type: ignore[arg-type]
        clock=clock,
    )
    computer = CloudComputer(manager, user_id=7, agent_id="new", store=store)
    computer.write("/generated/report.md", "# Report")
    computer.upload_files([("/generated/cat.png", b"png")])
    assert computer_off(SimpleNamespace(backend=computer), "notes/plan.md")
    assert cvm.calls == [] and ags.calls == [] and billing.reserved == []
    # Work starts a CVM, with the deliverables on it.
    computer.execute("ls")
    assert cvm.calls == [("start", "new")] and ags.calls == []
    assert cvm.files[f"{WORKSPACE}/generated/report.md"] == b"# Report"
    # A Bot whose computer was made on AGS before the switch resumes there, files and all.
    ags.states["ags-old"] = "paused"
    ags.files[f"{WORKSPACE}/generated/old.md"] = b"from AGS"
    manager._save(computers.ComputerRecord(agent_id="old", user_id=8, instance_id="ags-old"))
    older = CloudComputer(manager, user_id=8, agent_id="old", store=store)
    older.execute("ls")
    assert ("resume", "ags-old") in ags.calls and len(cvm.calls) == 1
    assert store.download_files(["/generated/old.md"])[0].content == b"from AGS"
def test_shadow_bots_nobody_used_for_30_days_are_deleted_with_their_computers(setup: Any) -> None:
    from types import SimpleNamespace

    manager, driver, billing, clock = setup
    agents = manager._services.agent_repo
    day = 86400.0
    clock.now = 100 * day
    agents.shadows = [
        # Updated by its desktop long ago, and its computer not used since.
        SimpleNamespace(agent_id="gone", user_id=7, updated_at=60 * day, kind="shadow"),
        # Its desktop still updates it.
        SimpleNamespace(agent_id="synced", user_id=7, updated_at=95 * day, kind="shadow"),
        # Old, but its computer was used last week.
        SimpleNamespace(agent_id="used", user_id=7, updated_at=10 * day, kind="shadow"),
    ]
    clock.now = 93 * day
    CloudComputer(manager, user_id=7, agent_id="used").execute("ls")
    manager.pause("used", 7)
    CloudComputer(manager, user_id=7, agent_id="gone")  # no computer yet
    clock.now = 100 * day
    manager.tick()
    assert agents.deleted == {"gone"}
    # Not again within the hour.
    agents.shadows.append(
        SimpleNamespace(agent_id="later", user_id=7, updated_at=1 * day, kind="shadow")
    )
    clock.now += 60
    manager.tick()
    assert "later" not in agents.deleted
    clock.now += computers.SHADOW_SCAN_SECONDS
    manager.tick()
    assert "later" in agents.deleted
