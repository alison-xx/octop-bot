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

# Fills a brand-new computer: called with ``write(path_on_computer, data)``.
Seeder = Callable[[Callable[[str, bytes], None]], None]

logger = logging.getLogger(__name__)

IDLE_PAUSE_SECONDS = 10 * 60
CHUNK_MINUTES = 5
# Reaper passes (30 s apart) a failing settle is retried; Lynxce settles a reservation itself
# 15 minutes after it expires, so an hour is plenty.
MAX_SETTLE_ATTEMPTS = 120
REAP_INTERVAL_SECONDS = 30
# Instances this server started but has no record of (a start that timed out, a crash before the
# record was saved) are stopped once they are this old; younger ones may still be starting.
ORPHAN_AGE_SECONDS = 15 * 60
ORPHAN_SCAN_SECONDS = 10 * 60
SERVER_ID_KEY = "octop_bot:computers:server_id"


@dataclass
class Reservation:
    id: str
    minutes: int


@dataclass
class Unsettled:
    """A settle Lynxce did not take yet; retried by the reaper (an unsettled chunk is charged
    in full, so it must not be dropped)."""

    reservation: Reservation
    used_seconds: int
    attempts: int = 0


@dataclass
class ComputerRecord:
    agent_id: str
    user_id: int
    spec: Spec = "standard"
    instance_id: str | None = None
    running: bool = False
    # Billing cursor: the start of the oldest reservation still open.
    running_since: float | None = None
    # When the computer last started or resumed, for "running for N minutes".
    started_at: float | None = None
    active_at: float = 0.0
    paid_until: float = 0.0
    reservations: list[Reservation] = field(default_factory=list)
    unsettled: list[Unsettled] = field(default_factory=list)
    # The Bot's object-store files were copied onto its computer once.
    seeded: bool = False

    @classmethod
    def load(cls, raw: str) -> ComputerRecord:
        data = json.loads(raw)
        data["reservations"] = [Reservation(**r) for r in data.get("reservations", [])]
        data["unsettled"] = [
            Unsettled(
                Reservation(**u["reservation"]), int(u["used_seconds"]), int(u.get("attempts", 0))
            )
            for u in data.get("unsettled", [])
        ]
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})

    def dump(self) -> str:
        return json.dumps(asdict(self))


def _settle_refused(exc: Exception) -> bool:
    """A settle Lynxce will never accept: the reservation is unknown, or the request invalid."""
    if not isinstance(exc, OctopError):
        return False
    if exc.code == ErrorCode.NOT_FOUND:
        return True
    return exc.code == ErrorCode.BOT_CLOUD_REQUEST_REJECTED and exc.status in {400, 409, 422}


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
        self._stopping = threading.Event()
        self._last_orphan_scan = 0.0

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

    def is_running(self, agent_id: str, user_id: int) -> bool:
        return self.record(agent_id, user_id).running

    def server_id(self) -> str:
        """Stable id of this Octop server, labelled on its instances (several servers may share
        one AGS account; each only ever cleans up its own)."""
        repo = self._services.settings_repo
        value = repo.get(SERVER_ID_KEY)
        if isinstance(value, str) and value:
            return value
        value = uuid.uuid4().hex[:16]
        repo.set(SERVER_ID_KEY, value)
        return value

    # Running

    def ensure_running(self, agent_id: str, user_id: int, seed: Seeder | None = None) -> str:
        """The computer's instance id, started or resumed (and paid for) if needed.

        ``seed`` fills a brand-new computer the first time this Bot gets one.
        """
        self._start_reaper()
        with self._lock(agent_id):
            record = self.record(agent_id, user_id)
            now = self._clock()
            record.active_at = now
            if record.running and record.instance_id:
                self._save(record)
                return record.instance_id
            reservation = self._billing.reserve(record, CHUNK_MINUTES)
            fresh = False
            try:
                state = self._driver.state(record.instance_id) if record.instance_id else "gone"
                if state == "paused":
                    self._driver.resume(record.instance_id or "")
                elif state == "gone":
                    # A start that times out after AGS made the instance, or a crash right
                    # after, leaves an instance no record knows: the orphan scan stops it by its
                    # octop-server label.
                    record.instance_id = None
                    self._save(record)
                    record.instance_id = self._driver.start(
                        spec=record.spec,
                        labels={
                            "octop-user": str(user_id),
                            "octop-bot": agent_id,
                            "octop-server": self.server_id(),
                        },
                    )
                    fresh = True
            except Exception:
                # Settle first: a settle that fails is kept in ``unsettled``, saved here.
                self._settle_one(record, reservation, 0)
                self._save(record)
                raise
            record.running = True
            record.running_since = now
            record.started_at = now
            record.paid_until = now + CHUNK_MINUTES * 60
            record.reservations = [reservation]
            self._save(record)
            assert record.instance_id is not None
            if fresh and seed is not None and not record.seeded:
                instance = record.instance_id
                try:
                    seed(lambda path, data: self._driver.write(instance, path, data))
                    record.seeded = True
                    self._save(record)
                except Exception:  # noqa: BLE001 - the computer works; files are copied next time
                    logger.warning("copying files onto the computer of %s failed", agent_id)
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
            record.started_at = None
            self._save(record)

    def _settle_one(
        self, record: ComputerRecord, reservation: Reservation, used: int, attempts: int = 0
    ) -> None:
        """Settle one reservation; on a passing failure keep it for the reaper to retry.

        Gives up when Lynxce refuses it for good (unknown reservation, invalid request) or after
        ``MAX_SETTLE_ATTEMPTS``: by then Lynxce has settled the expired reservation itself, and
        a record that never empties would keep a deleted Bot's computer record forever.
        """
        try:
            self._billing.settle(record, reservation, used)
        except Exception as exc:  # noqa: BLE001 - classified below
            if _settle_refused(exc):
                logger.warning("Lynxce refused settling %s (%s); dropped", reservation.id, exc)
            elif attempts + 1 >= MAX_SETTLE_ATTEMPTS:
                logger.warning("settling %s failed %s times; dropped", reservation.id, attempts + 1)
            else:
                logger.warning("settling %s failed; will retry", reservation.id)
                record.unsettled.append(Unsettled(reservation, used, attempts + 1))

    def _settle(self, record: ComputerRecord, until: float | None = None) -> None:
        """Settle every open reservation for the time run up to ``until`` (default: now)."""
        end = self._clock() if until is None else until
        used = max(0, int(end - (record.running_since or end)))
        for reservation in record.reservations:
            share = min(used, reservation.minutes * 60)
            used -= share
            self._settle_one(record, reservation, share)
        record.reservations = []
        if used > 0:
            # Ran past what was reserved (the reaper was late, or the process was down): pay
            # for the rest with one more reservation, settled right away.
            minutes = -(-used // 60)
            try:
                extra = self._billing.reserve(record, minutes)
            except Exception:  # noqa: BLE001 - out of credits; logged for reconciliation
                logger.warning(
                    "computer %s ran %ss past its reservations and could not be billed",
                    record.agent_id,
                    used,
                )
            else:
                self._settle_one(record, extra, used)

    def _retry_unsettled(self, agent_id: str, user_id: int) -> None:
        with self._lock(agent_id):
            record = self.record(agent_id, user_id)
            if not record.unsettled:
                return
            pending, record.unsettled = record.unsettled, []
            for item in pending:
                self._settle_one(record, item.reservation, item.used_seconds, item.attempts)
            self._save(record)

    def tick(self) -> None:
        """One pass over every computer; a failure on one never holds up the others."""
        now = self._clock()
        records: list[ComputerRecord] = []
        for key, raw in self._services.settings_repo.with_prefix("octop_bot:computer:").items():
            if not isinstance(raw, str):
                continue
            try:
                record = ComputerRecord.load(raw)
                records.append(record)
                self._tick_one(record, now)
            except Exception:  # noqa: BLE001 - isolated per computer
                logger.exception("computer %s tick failed", key)
        if now - self._last_orphan_scan >= ORPHAN_SCAN_SECONDS:
            self._last_orphan_scan = now
            try:
                self._stop_orphans(records, now)
            except Exception:  # noqa: BLE001 - retried on the next scan
                logger.exception("cloud computer orphan scan failed")

    def _stop_orphans(self, records: list[ComputerRecord], now: float) -> None:
        """Stop this server's instances that no record knows (lost starts, crashes)."""
        known = {r.instance_id for r in records if r.instance_id}
        mine = self.server_id()
        for instance in self._driver.instances():
            if (
                instance.labels.get("octop-server") != mine
                or instance.instance_id in known
                or instance.state == "gone"
                or now - instance.created_at < ORPHAN_AGE_SECONDS
            ):
                continue
            logger.warning("stopping orphaned cloud computer %s", instance.instance_id)
            self._driver.stop(instance.instance_id)

    def _tick_one(self, record: ComputerRecord, now: float) -> None:
        if record.unsettled:
            self._retry_unsettled(record.agent_id, record.user_id)
        if self._services.agent_repo.get(record.agent_id) is None:
            self._release(record.agent_id, record.user_id)
            return
        if not record.running:
            return
        if record.instance_id and self._driver.state(record.instance_id) == "gone":
            self._lost(record.agent_id, record.user_id)
            return
        busy = self._busy.get(record.agent_id, 0) > 0
        if not busy and now - record.active_at >= IDLE_PAUSE_SECONDS:
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
                # Bill only until AGS stopped it (e.g. while this server was down); when AGS
                # cannot tell, only the time already paid for.
                stopped = (
                    self._driver.stopped_at(record.instance_id) if record.instance_id else None
                )
                now = self._clock()
                until = min(stopped, now) if stopped else min(now, record.paid_until)
                self._settle(record, until=until)
            record.running = False
            record.running_since = None
            record.started_at = None
            record.instance_id = None
            self._save(record)

    def _release(self, agent_id: str, user_id: int) -> None:
        """The Bot was deleted: stop its computer for good and drop the record."""
        with self._lock(agent_id):
            record = self.record(agent_id, user_id)
            # Already reclaimed by AGS: nothing to stop, and stopping it would fail forever.
            if record.instance_id and self._driver.state(record.instance_id) != "gone":
                try:
                    self._driver.stop(record.instance_id)
                except Exception:  # noqa: BLE001 - retried on the next pass
                    logger.warning("stopping the computer of deleted bot %s failed", agent_id)
                    raise
            if record.running:
                self._settle(record)
            pending, record.unsettled = record.unsettled, []
            for item in pending:
                self._settle_one(record, item.reservation, item.used_seconds, item.attempts)
            if record.unsettled:
                # Keep the record until Lynxce has every settle; the computer is gone already.
                record.running = False
                record.instance_id = None
                self._save(record)
                return
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
                self._settle_one(record, done, done.minutes * 60)
                record.running_since += done.minutes * 60
                changed = True
            if changed:
                self._save(record)

    def _start_reaper(self) -> None:
        with self._guard:
            if self._reaper is not None:
                return

            def loop() -> None:
                while not self._stopping.wait(REAP_INTERVAL_SECONDS):
                    try:
                        self.tick()
                    except Exception:  # noqa: BLE001 - keep reaping
                        logger.exception("computer reaper tick failed")

            self._reaper = threading.Thread(target=loop, name="octop-computer-reaper", daemon=True)
            self._reaper.start()

    def close(self) -> None:
        """Stop the reaper (server shutdown): it must not touch a closed database."""
        self._stopping.set()
        reaper = self._reaper
        if reaper is not None and reaper is not threading.current_thread():
            reaper.join(timeout=REAP_INTERVAL_SECONDS)

    # Work

    def run(
        self,
        agent_id: str,
        user_id: int,
        command: str,
        timeout: int,
        *,
        seed: Seeder | None = None,
    ) -> tuple[int, str]:
        instance = self.ensure_running(agent_id, user_id, seed)
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

    def write(
        self, agent_id: str, user_id: int, path: str, data: bytes, *, seed: Seeder | None = None
    ) -> None:
        self._driver.write(self.ensure_running(agent_id, user_id, seed), path, data)

    def read(
        self, agent_id: str, user_id: int, path: str, *, seed: Seeder | None = None
    ) -> bytes | None:
        return self._driver.read(self.ensure_running(agent_id, user_id, seed), path)


_manager: ComputerManager | None = None
_manager_lock = threading.Lock()


def current_manager() -> ComputerManager | None:
    """The manager set up at server start, if cloud computers are configured."""
    return _manager


def shutdown_manager() -> None:
    """Server shutdown: stop the reaper and forget the manager (a restart makes a new one)."""
    global _manager
    with _manager_lock:
        manager, _manager = _manager, None
    if manager is not None:
        manager.close()


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
