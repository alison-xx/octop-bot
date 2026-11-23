"""Each cloud Bot's computer: start on first use, pause when idle, bill the running minutes.

State per agent lives in the settings table (``octop_bot:computer:<agent_id>``). Running time is
paid for up front in chunks reserved from the tenant's Lynxce wallet and settled by the second
when the computer pauses; a computer whose next chunk cannot be paid for is paused.

The harness calls backends from worker threads, so this module is synchronous; Lynxce billing
(async) runs on a private event loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from octop.infra.cloud.computers.driver import AgsConfig, AgsDriver, ComputerDriver, Spec
from octop.infra.errors import ErrorCode, OctopError

if TYPE_CHECKING:
    from octop.infra.db.services import SharedServices

logger = logging.getLogger(__name__)

IDLE_PAUSE_SECONDS = 10 * 60
# A screen viewer reports in every 30 s; miss a few and the computer can idle again.
VIEWER_GRACE_SECONDS = 90
CHUNK_MINUTES = 5
REAP_INTERVAL_SECONDS = 30


@dataclass
class Reservation:
    id: str
    minutes: int


@dataclass
class ComputerRecord:
    agent_id: str
    user_id: int
    spec: Spec = "standard"
    instance_id: str | None = None
    running: bool = False
    running_since: float | None = None
    active_at: float = 0.0
    paid_until: float = 0.0
    reservations: list[Reservation] = field(default_factory=list)
    # The user has the mouse and keyboard; the Bot waits until it is handed back.
    takeover: bool = False
    # Last time someone was watching the screen; a watched computer is not idle.
    viewed_at: float = 0.0

    @classmethod
    def load(cls, raw: str) -> ComputerRecord:
        data = json.loads(raw)
        data["reservations"] = [Reservation(**r) for r in data.get("reservations", [])]
        return cls(**data)

    def dump(self) -> str:
        return json.dumps(asdict(self))


class Billing:
    """Lynxce compute billing for one tenant, through their stored Lynxce session."""

    def __init__(self, services: SharedServices) -> None:
        self._services = services

    def reserve(self, record: ComputerRecord, minutes: int) -> Reservation:
        from octop.infra.auth import lynxce_cloud  # noqa: PLC0415

        data = _run(
            lynxce_cloud.tenant_call(
                self._services,
                record.user_id,
                "POST",
                "/api/billing/octop-bot/compute/reserve",
                {
                    "computerId": record.agent_id,
                    "spec": record.spec,
                    "minutes": minutes,
                    "idempotencyKey": uuid.uuid4().hex,
                },
            )
        )
        reservation_id = data.get("reservationId") if isinstance(data, dict) else None
        if not isinstance(reservation_id, str):
            raise OctopError.localized(ErrorCode.NETWORK_ERROR)
        return Reservation(reservation_id, minutes)

    def settle(self, record: ComputerRecord, reservation: Reservation, used_seconds: int) -> None:
        from octop.infra.auth import lynxce_cloud  # noqa: PLC0415

        _run(
            lynxce_cloud.tenant_call(
                self._services,
                record.user_id,
                "POST",
                "/api/billing/octop-bot/compute/settle",
                {"reservationId": reservation.id, "usedSeconds": max(0, used_seconds)},
            )
        )


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine to completion from sync code, even on a thread that has a loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread
            box["error"] = exc

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join()
    if "error" in box:
        raise box["error"]
    return box["value"]  # type: ignore[no-any-return]


class ComputerManager:
    def __init__(
        self,
        services: SharedServices,
        driver: ComputerDriver,
        *,
        billing: Billing | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._services = services
        self._driver = driver
        self._billing = billing or Billing(services)
        self._clock = clock
        self._locks: dict[str, threading.Lock] = {}
        # Commands running right now, per agent: a computer mid-command is never idle.
        self._busy: dict[str, int] = {}
        self._guard = threading.Lock()
        self._reaper: threading.Thread | None = None

    # Records

    @staticmethod
    def _key(agent_id: str) -> str:
        return f"octop_bot:computer:{agent_id}"

    def _lock(self, agent_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(agent_id, threading.Lock())

    def record(self, agent_id: str, user_id: int) -> ComputerRecord:
        raw = self._services.settings_repo.get(self._key(agent_id))
        if isinstance(raw, str) and raw:
            record = ComputerRecord.load(raw)
            if record.user_id == user_id:
                return record
        return ComputerRecord(agent_id=agent_id, user_id=user_id)

    def _save(self, record: ComputerRecord) -> None:
        self._services.settings_repo.set(self._key(record.agent_id), record.dump())

    # Running

    def ensure_running(self, agent_id: str, user_id: int) -> str:
        """The computer's instance id, started or resumed (and paid for) if needed."""
        self._start_reaper()
        with self._lock(agent_id):
            record = self.record(agent_id, user_id)
            now = self._clock()
            record.active_at = now
            if record.running and record.instance_id:
                self._save(record)
                return record.instance_id
            reservation = self._billing.reserve(record, CHUNK_MINUTES)
            try:
                state = self._driver.state(record.instance_id) if record.instance_id else "gone"
                if state == "paused":
                    self._driver.resume(record.instance_id or "")
                elif state == "gone":
                    record.instance_id = self._driver.start(
                        spec=record.spec,
                        labels={"octop-user": str(user_id), "octop-bot": agent_id},
                    )
            except Exception:
                self._billing.settle(record, reservation, 0)
                raise
            record.running = True
            record.running_since = now
            record.paid_until = now + CHUNK_MINUTES * 60
            record.reservations = [reservation]
            self._save(record)
            assert record.instance_id is not None
            return record.instance_id

    def touch(self, agent_id: str, user_id: int) -> None:
        with self._lock(agent_id):
            record = self.record(agent_id, user_id)
            record.active_at = self._clock()
            self._save(record)

    def pause(self, agent_id: str, user_id: int) -> None:
        with self._lock(agent_id):
            record = self.record(agent_id, user_id)
            if not record.running:
                return
            if record.instance_id:
                try:
                    self._driver.pause(record.instance_id)
                except Exception:  # noqa: BLE001 - a computer that cannot pause is stopped instead
                    logger.warning("computer %s did not pause; stopping it", agent_id)
                    self._driver.stop(record.instance_id)
                    record.instance_id = None
            self._settle(record)
            record.running = False
            record.running_since = None
            self._save(record)

    def _settle(self, record: ComputerRecord) -> None:
        used = int(self._clock() - (record.running_since or self._clock()))
        for reservation in record.reservations:
            share = min(used, reservation.minutes * 60)
            used -= share
            try:
                self._billing.settle(record, reservation, share)
            except Exception:  # noqa: BLE001 - Lynxce settles stale reservations itself
                logger.warning("settling %s failed", reservation.id)
        record.reservations = []

    def tick(self) -> None:
        """One pass over every computer; a failure on one never holds up the others."""
        now = self._clock()
        for key, raw in self._services.settings_repo.with_prefix("octop_bot:computer:").items():
            if not isinstance(raw, str):
                continue
            try:
                self._tick_one(ComputerRecord.load(raw), now)
            except Exception:  # noqa: BLE001 - isolated per computer
                logger.exception("computer %s tick failed", key)

    def _tick_one(self, record: ComputerRecord, now: float) -> None:
        if self._services.agent_repo.get(record.agent_id) is None:
            self._release(record.agent_id, record.user_id)
            return
        if not record.running:
            return
        if record.instance_id and self._driver.state(record.instance_id) == "gone":
            self._lost(record.agent_id, record.user_id)
            return
        busy = self._busy.get(record.agent_id, 0) > 0
        watched = record.takeover or now - record.viewed_at < VIEWER_GRACE_SECONDS
        if not (busy or watched) and now - record.active_at >= IDLE_PAUSE_SECONDS:
            self.pause(record.agent_id, record.user_id)
            return
        self._settle_elapsed(record.agent_id, record.user_id, now)
        with self._lock(record.agent_id):
            current = self.record(record.agent_id, record.user_id)
            # Re-read under the lock: a pause may have landed since the snapshot above.
            if not current.running or now < current.paid_until - 60:
                return
            try:
                current.reservations.append(self._billing.reserve(current, CHUNK_MINUTES))
                current.paid_until += CHUNK_MINUTES * 60
                self._save(current)
                return
            except Exception:  # noqa: BLE001 - out of credits (402) or Lynxce down
                logger.info("computer %s could not be paid for; pausing", record.agent_id)
        self.pause(record.agent_id, record.user_id)

    def _lost(self, agent_id: str, user_id: int) -> None:
        """The provider no longer has the instance (stopped, expired): close its billing."""
        with self._lock(agent_id):
            record = self.record(agent_id, user_id)
            if record.running:
                self._settle(record)
            record.running = False
            record.running_since = None
            record.instance_id = None
            self._save(record)

    def _release(self, agent_id: str, user_id: int) -> None:
        """The Bot was deleted: stop its computer for good and drop the record."""
        with self._lock(agent_id):
            record = self.record(agent_id, user_id)
            if record.instance_id:
                try:
                    self._driver.stop(record.instance_id)
                except Exception:  # noqa: BLE001 - retried on the next pass
                    logger.warning("stopping the computer of deleted bot %s failed", agent_id)
                    raise
            if record.running:
                self._settle(record)
            self._services.settings_repo.delete(self._key(agent_id))

    def _settle_elapsed(self, agent_id: str, user_id: int, now: float) -> None:
        """Settle chunks that are fully used as soon as they end.

        Lynxce charges a reservation in full if it stays unsettled for long, and ignores a late
        settle; settling each finished chunk right away keeps the ledger exact.
        """
        with self._lock(agent_id):
            record = self.record(agent_id, user_id)
            changed = False
            while (
                record.running
                and len(record.reservations) > 1
                and record.running_since is not None
                and now - record.running_since >= record.reservations[0].minutes * 60
            ):
                done = record.reservations.pop(0)
                try:
                    self._billing.settle(record, done, done.minutes * 60)
                except Exception:  # noqa: BLE001 - Lynxce charges an unsettled chunk in full
                    logger.warning("settling %s failed", done.id)
                record.running_since += done.minutes * 60
                changed = True
            if changed:
                self._save(record)

    def _start_reaper(self) -> None:
        with self._guard:
            if self._reaper is not None:
                return

            def loop() -> None:
                while True:
                    time.sleep(REAP_INTERVAL_SECONDS)
                    try:
                        self.tick()
                    except Exception:  # noqa: BLE001 - keep reaping
                        logger.exception("computer reaper tick failed")

            self._reaper = threading.Thread(target=loop, name="octop-computer-reaper", daemon=True)
            self._reaper.start()

    # Screen and takeover

    def screen(self, agent_id: str, user_id: int) -> tuple[str, dict[str, str]]:
        """Where to reach the running computer's desktop (VNC over WebSocket)."""
        instance = self.ensure_running(agent_id, user_id)
        self.viewing(agent_id, user_id)
        return self._driver.screen(instance)

    def viewing(self, agent_id: str, user_id: int) -> None:
        with self._lock(agent_id):
            record = self.record(agent_id, user_id)
            record.viewed_at = record.active_at = self._clock()
            self._save(record)

    def set_takeover(self, agent_id: str, user_id: int, active: bool) -> ComputerRecord:
        with self._lock(agent_id):
            record = self.record(agent_id, user_id)
            record.takeover = active
            record.active_at = self._clock()
            self._save(record)
            return record

    def taken_over(self, agent_id: str, user_id: int) -> bool:
        return self.record(agent_id, user_id).takeover

    def _controlled(self, agent_id: str, user_id: int) -> str:
        """The instance the user has taken over; typing and the clipboard need takeover."""
        record = self.record(agent_id, user_id)
        if not (record.takeover and record.running and record.instance_id):
            raise OctopError.localized(ErrorCode.BOT_COMPUTER_NOT_TAKEN_OVER)
        return record.instance_id

    def paste_text(self, agent_id: str, user_id: int, text: str) -> None:
        self._driver.paste_text(self._controlled(agent_id, user_id), text)
        self.viewing(agent_id, user_id)

    def read_clipboard(self, agent_id: str, user_id: int) -> str:
        text = self._driver.read_clipboard(self._controlled(agent_id, user_id))
        self.viewing(agent_id, user_id)
        return text

    # Work

    def run(self, agent_id: str, user_id: int, command: str, timeout: int) -> tuple[int, str]:
        instance = self.ensure_running(agent_id, user_id)
        with self._guard:
            self._busy[agent_id] = self._busy.get(agent_id, 0) + 1
        try:
            return self._driver.run(instance, command, timeout)
        except Exception:
            # The instance may have gone away underneath (expired, stopped elsewhere).
            if self._driver.state(instance) == "gone":
                self._lost(agent_id, user_id)
            raise
        finally:
            with self._guard:
                self._busy[agent_id] -= 1
            self.touch(agent_id, user_id)

    def write(self, agent_id: str, user_id: int, path: str, data: bytes) -> None:
        self._driver.write(self.ensure_running(agent_id, user_id), path, data)

    def read(self, agent_id: str, user_id: int, path: str) -> bytes | None:
        return self._driver.read(self.ensure_running(agent_id, user_id), path)


_manager: ComputerManager | None = None
_manager_lock = threading.Lock()


def current_manager() -> ComputerManager | None:
    """The manager set up at server start, if cloud computers are configured."""
    return _manager


def computer_manager(services: SharedServices) -> ComputerManager | None:
    """The process-wide manager, or ``None`` when AGS is not configured."""
    global _manager
    config = AgsConfig.from_env()
    if config is None:
        return None
    with _manager_lock:
        if _manager is None:
            _manager = ComputerManager(services, AgsDriver(config))
            # Computers left running by a previous process are billed and paused from now on,
            # not from their next tool call.
            _manager._start_reaper()
        return _manager
