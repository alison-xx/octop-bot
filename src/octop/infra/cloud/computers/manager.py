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
import os
import threading
import time
import uuid
from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from datetime import time as daytime
from typing import TYPE_CHECKING, Any, Literal

from octop.infra.cloud.computers import DiskBalanceInsufficient
from octop.infra.cloud.computers.driver import AgsConfig, AgsDriver, ComputerDriver, Spec
from octop.infra.cloud.computers.handoff import (
    BackgroundComputerTurn,
    SingleComputerController,
    current_background_turn,
)
from octop.infra.errors import ErrorCode, OctopError

if TYPE_CHECKING:
    from octop.infra.db.services import SharedServices

# Fills a brand-new computer: called with ``write(path_on_computer, data)``.
Seeder = Callable[[Callable[[str, bytes], None]], None]


@dataclass(frozen=True)
class ComputerIO:
    """A computer that just started or resumed, for a wake callback (which runs under the
    computer's lock, so it must use these and never the manager's own methods)."""

    write: Callable[[str, bytes], None]
    read: Callable[[str], bytes | None]
    run: Callable[[str], tuple[int, str]]


Waker = Callable[[ComputerIO], None]
# A wake callback's commands are short listings; the desktop server stops a request at 120 s.
WAKE_COMMAND_TIMEOUT = 90

logger = logging.getLogger(__name__)

IDLE_PAUSE_SECONDS = 10 * 60
# A screen viewer reports in every 30 s; miss a few and the computer can idle again, and a
# takeover with no one watching is handed back to the Bot.
VIEWER_GRACE_SECONDS = 90
# A conversation that stopped using a computer's screen this long ago lets another one use it.
SCREEN_HOLD_SECONDS = 120
CHUNK_MINUTES = 5
# Reaper passes (30 s apart) a failing settle is retried; Lynxce settles a reservation itself
# 15 minutes after it expires, so an hour is plenty.
MAX_SETTLE_ATTEMPTS = 120
REAP_INTERVAL_SECONDS = 30
# Instances this server started but has no record of (a start that timed out, a crash before the
# record was saved) are stopped once they are this old; younger ones may still be starting.
ORPHAN_AGE_SECONDS = 15 * 60
ORPHAN_SCAN_SECONDS = 10 * 60
# How often shadow Bots (desktop Bots' stand-ins, see bot_cloud/shadows.py) are checked for
# having gone unused long enough to be deleted.
SHADOW_SCAN_SECONDS = 60 * 60
SERVER_ID_KEY = "octop_bot:computers:server_id"
# When AGS is out of capacity, a running computer whose Bot has not acted for this long is
# paused to make room (it would pause at IDLE_PAUSE_SECONDS anyway; resuming takes seconds).
MAKE_ROOM_IDLE_SECONDS = 2 * 60
# A disk charge Lynxce did not take (out of credits, Lynxce down, disk not priced) is tried
# again this much later, not on every 30 s pass.
DISK_RETRY_SECONDS = 10 * 60
# Display fallback; Lynxce's admin price is the source of truth for charges.
DISK_DAILY_CREDITS_PER_GB = 4.80
_BEIJING_OFFSET_SECONDS = 8 * 3600


def disk_billing_enabled() -> bool:
    return os.environ.get("OCTOP_DISK_BILLING", "").strip().lower() in {"1", "true", "on", "yes"}


def reclaim_enabled() -> bool:
    return os.environ.get("OCTOP_COMPUTER_RECLAIM", "").strip().lower() in {
        "1",
        "true",
        "on",
        "yes",
    }


def beijing_day(timestamp: float) -> str:
    """The calendar day in Beijing time, which is how Lynxce prepays disks (YYYY-MM-DD)."""
    return time.strftime("%Y-%m-%d", time.gmtime(timestamp + _BEIJING_OFFSET_SECONDS))


@dataclass
class Reservation:
    id: str
    minutes: int


@dataclass(frozen=True)
class Glance:
    window: str | None
    # Base64 JPEG, 320 px wide.
    thumbnail: str | None


# The Bot counts as "on the computer" for this long after its last action (screenshots and
# model turns sit between actions).
BUSY_AFTER_ACTION_SECONDS = 20
GLANCE_CACHE_SECONDS = 5
GLANCE_SCRIPT = """
import base64, io, subprocess
def _run(*args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=3).stdout
    except Exception:
        return ""
win = _run("xprop", "-root", "_NET_ACTIVE_WINDOW").split()[-1:] or [""]
title = ""
if win[0].startswith("0x") and win[0] != "0x0":
    raw = _run("xprop", "-id", win[0], "_NET_WM_NAME")
    if "=" in raw:
        title = raw.split("=", 1)[1].strip().strip('"')
print("WINDOW:" + title.replace("\\n", " "))
try:
    import pyautogui
    shot = pyautogui.screenshot().convert("RGB")
    shot.thumbnail((320, 180))
    buf = io.BytesIO()
    shot.save(buf, "JPEG", quality=60)
    print("THUMB:" + base64.b64encode(buf.getvalue()).decode())
except Exception:
    pass
"""


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
    starting: bool = False
    starting_at: float | None = None
    # Billing cursor: the start of the oldest reservation still open.
    running_since: float | None = None
    # When the computer last started or resumed, for "running for N minutes".
    started_at: float | None = None
    active_at: float = 0.0
    paid_until: float = 0.0
    reservations: list[Reservation] = field(default_factory=list)
    # The user has the mouse and keyboard; the Bot waits until it is handed back. It only
    # holds while the screen is watched (see ``controlled``).
    takeover: bool = False
    # The next model-visible frame after human input must be checked for password controls.
    check_handoff_frame: bool = False
    # Last time someone was watching the screen; a watched computer is not idle.
    viewed_at: float = 0.0
    unsettled: list[Unsettled] = field(default_factory=list)
    # The Bot's object-store files were copied onto its computer once.
    seeded: bool = False
    # The Beijing day the disk is paid for, and when to retry a disk charge that failed.
    disk_paid_day: str = ""
    disk_failed_day: str = ""
    disk_insufficient_day: str = ""  # Last day Lynxce confirmed insufficient credits.
    disk_retry_at: float = 0.0
    reminded_at: float | None = None
    reclaim_reason: Literal["idle", "unpaid"] | None = None
    reclaim_at: float | None = None
    reclaim_seen_at: float | None = None
    reclaim_unpaid_since: str = ""

    def clear_disk_arrears(self) -> None:
        self.disk_failed_day = ""
        self.disk_insufficient_day = ""
        self.reclaim_unpaid_since = ""
        if self.reclaim_reason == "unpaid":
            self.reminded_at = None
            self.reclaim_reason = None
            self.reclaim_at = None

    def controlled(self, now: float) -> bool:
        """Taken over and still watched: a closed tab or a phone that left hands it back."""
        return self.takeover and now - self.viewed_at < VIEWER_GRACE_SECONDS

    @classmethod
    def load(cls, raw: str) -> ComputerRecord:
        data = json.loads(raw)
        data.setdefault("check_handoff_frame", bool(data.get("takeover")))
        data["reservations"] = [Reservation(**r) for r in data.get("reservations", [])]
        data["unsettled"] = [
            Unsettled(
                Reservation(**u["reservation"]), int(u["used_seconds"]), int(u.get("attempts", 0))
            )
            for u in data.get("unsettled", [])
        ]
        known = set(cls.__dataclass_fields__)
        record = cls(**{k: v for k, v in data.items() if k in known})
        if "disk_insufficient_day" not in data:
            # Older records counted upstream and authentication errors as unpaid days.
            record.clear_disk_arrears()
        return record

    def dump(self) -> str:
        return json.dumps(asdict(self))


# Tencent Cloud error codes that mean "no room right now": the account quota of AGS or CVM
# (instances, CPU cores, memory), or a CVM type sold out in every zone tried.
_CAPACITY_CODES = (
    "LimitExceeded",
    "ResourceInsufficient",
    "ResourcesSoldOut",
    "InstancesSoldOut",
    "NoAvailableZone",
)


def capacity_full(exc: BaseException) -> bool:
    """The provider refused for lack of capacity, not a passing error (anywhere in the chain:
    the CVM driver wraps the last zone's error)."""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = str(getattr(current, "code", "") or "")
        if code.startswith(_CAPACITY_CODES) and code != "LimitExceeded.APIKeyQuota":
            return True
        current = current.__cause__
    return False


def error_codes(exc: BaseException) -> list[str]:
    """The provider error codes along ``exc``'s cause chain, for the log."""
    codes: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = str(getattr(current, "code", "") or "")
        if code:
            codes.append(code)
        current = current.__cause__
    return codes


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

    def charge_disk(self, record: ComputerRecord, day: str, size_gb: int) -> None:
        """Prepay the disk for a Beijing day; Lynxce charges each computer once per day."""
        from octop.infra.auth import lynxce_cloud  # noqa: PLC0415

        _run(
            lynxce_cloud.tenant_call(
                self._services,
                record.user_id,
                "POST",
                "/api/billing/octop-bot/compute/disk/charge",
                {"computerId": record.agent_id, "day": day, "sizeGb": size_gb},
            )
        )


class FreeBilling:
    """No Lynxce billing: a self-hosted server on its own AGS account, or a local test run
    (``OCTOP_BOT_COMPUTE_BILLING=off``). The operator pays AGS directly."""

    def reserve(self, record: ComputerRecord, minutes: int) -> Reservation:
        return Reservation(f"free-{uuid.uuid4().hex[:12]}", minutes)

    def settle(self, record: ComputerRecord, reservation: Reservation, used_seconds: int) -> None:
        return None

    def charge_disk(self, record: ComputerRecord, day: str, size_gb: int) -> None:
        return None


def billing_for(services: SharedServices) -> Billing | FreeBilling:
    """Lynxce credits in Octop Bot cloud, unless the operator turned billing off."""
    import os  # noqa: PLC0415

    from octop.infra.desktop import bot_cloud_enabled  # noqa: PLC0415

    off = (os.environ.get("OCTOP_BOT_COMPUTE_BILLING") or "").strip().lower() in {"off", "0"}
    if off or not bot_cloud_enabled():
        return FreeBilling()
    return Billing(services)


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


MAX_RUNNING_COMPUTERS_PER_USER = 2
STARTING_STALE_SECONDS = 10 * 60


class ComputerUnavailable(OSError):
    """The requested existing instance cannot currently accept Bot work."""


class ComputerManager:
    def __init__(
        self,
        services: SharedServices,
        driver: ComputerDriver,
        *,
        billing: Billing | FreeBilling | None = None,
        clock: Callable[[], float] = time.time,
        controller: SingleComputerController | None = None,
    ) -> None:
        self._services = services
        self._driver = driver
        self._billing = billing or Billing(services)
        self._clock = clock
        self._controller = controller
        self._exclusive_wakes: dict[str, tuple[BackgroundComputerTurn, str]] = {}
        self._locks: dict[str, threading.RLock] = {}
        # Commands running right now, per agent: a computer mid-command is never idle.
        self._busy: dict[str, int] = {}
        self._guard = threading.Lock()
        self._user_locks: dict[int, threading.Lock] = {}
        self._reaper: threading.Thread | None = None
        self._stopping = threading.Event()
        # What the Bot last did on each computer, for the chat's floating screen: (kind, time).
        self._activity: dict[str, tuple[str, float]] = {}
        # Short-lived glances (window title + thumbnail) so several viewers share one request.
        self._glances: dict[str, tuple[float, Glance]] = {}
        # Which conversation drives each computer's screen, and when it last did: (thread, time).
        self._screen_holders: dict[str, tuple[str, float]] = {}
        self._last_orphan_scan = 0.0
        # Per Bot: called whenever its computer starts or resumes (see ``on_wake``).
        self._wakers: dict[str, Waker] = {}
        self._last_shadow_scan = 0.0
        self.remind: Callable[[ComputerRecord, float], bool] | None = None

    # Records

    @staticmethod
    def _key(agent_id: str) -> str:
        return f"octop_bot:computer:{agent_id}"

    def _lock(self, agent_id: str) -> threading.RLock:
        with self._guard:
            return self._locks.setdefault(agent_id, threading.RLock())

    def _user_lock(self, user_id: int) -> threading.Lock:
        with self._guard:
            return self._user_locks.setdefault(user_id, threading.Lock())

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

    def disk_status(self, record: ComputerRecord) -> tuple[int, int]:
        """Billed disk size and days since the first unpaid Beijing day (inclusive)."""
        disk_gb = getattr(self._driver, "disk_gb", None)
        size = max(0, int(disk_gb(record.instance_id))) if record.instance_id and disk_gb else 0
        overdue = 0
        if record.disk_failed_day:
            overdue = max(
                0,
                (
                    date.fromisoformat(beijing_day(self._clock()))
                    - date.fromisoformat(record.disk_failed_day)
                ).days
                + 1,
            )
        return size, overdue

    def _cancel_reclaim(self, record: ComputerRecord, *, used: bool = False) -> None:
        if used and record.reclaim_reason == "unpaid":
            record.reclaim_unpaid_since = beijing_day(self._clock())
        record.reminded_at = None
        record.reclaim_reason = None
        record.reclaim_at = None

    def reclaim_status(self, record: ComputerRecord) -> tuple[int, str | None, float | None]:
        now = self._clock()
        last = max(record.active_at or 0, record.started_at or 0, record.reclaim_seen_at or 0)
        idle_days = max(0, int((now - last) // 86400)) if last else 0
        if not record.instance_id:
            return idle_days, None, None
        confirmed_today = self._unpaid_confirmed(record, now)
        if record.reclaim_reason == "unpaid" and disk_billing_enabled() and not confirmed_today:
            # A day rollover can precede the next scheduled debit. Preserve the actual notice
            # and require a fresh balance decision before the reaper can act on its deadline.
            return idle_days, None, None
        valid_notice = record.reclaim_reason != "unpaid" or confirmed_today
        if valid_notice and record.reminded_at is not None and record.reclaim_at is not None:
            state = "pending_reclaim" if now >= record.reclaim_at else "reminded"
            return idle_days, state, record.reclaim_at
        failed_day = record.reclaim_unpaid_since or record.disk_failed_day
        if confirmed_today and failed_day:
            first = date.fromisoformat(failed_day)
            overdue = (date.fromisoformat(beijing_day(now)) - first).days + 1
            if overdue >= 23:
                deadline = datetime.combine(
                    first + timedelta(days=29), daytime.min, tzinfo=timezone(timedelta(hours=8))
                ).timestamp()
                return idle_days, "pending_reclaim" if now >= deadline else "reminded", deadline
        if not record.running and last and idle_days >= 30:
            deadline = last + 37 * 86400
            if not valid_notice:
                deadline = max(deadline, now + 7 * 86400)
            return idle_days, "pending_reclaim" if now >= deadline else "reminded", deadline
        return idle_days, None, None

    @staticmethod
    def _unpaid_confirmed(record: ComputerRecord, now: float) -> bool:
        return disk_billing_enabled() and record.disk_insufficient_day == beijing_day(now)

    def _reclaim_tick(self, agent_id: str, user_id: int, now: float) -> None:
        with self._lock(agent_id):
            record = self.record(agent_id, user_id)
            if not record.instance_id:
                return
            if not record.active_at and not record.started_at and record.reclaim_seen_at is None:
                record.reclaim_seen_at = now
                self._save(record)
            if record.reclaim_reason == "unpaid" and not disk_billing_enabled():
                # An idle reclaim needs its own delivered warning and full grace period.
                self._cancel_reclaim(record)
                self._save(record)
            _, state, deadline = self.reclaim_status(record)
            if not reclaim_enabled() or state is None:
                return
            if record.reminded_at is not None:
                if state == "pending_reclaim" and not self._busy.get(agent_id, 0):
                    if record.reclaim_reason == "unpaid":
                        # Wait for a balance decision at or after the reclaim deadline.
                        last_check = record.disk_retry_at - DISK_RETRY_SECONDS
                        if not disk_billing_enabled() or deadline is None or last_check < deadline:
                            return
                    self._release(agent_id, user_id)
                return
            failed_day = record.reclaim_unpaid_since or record.disk_failed_day
            overdue = (
                (date.fromisoformat(beijing_day(now)) - date.fromisoformat(failed_day)).days + 1
                if failed_day
                else 0
            )
            record.reclaim_reason = (
                "unpaid" if self._unpaid_confirmed(record, now) and overdue >= 23 else "idle"
            )
            # A delayed reaper or unavailable notification must still allow seven days.
            deadline = max(deadline or now, now + 7 * 86400)
        # Delivery runs on the server event loop; never hold the computer lock while waiting.
        if self.remind is None or not self.remind(record, deadline):
            return
        with self._lock(agent_id):
            current = self.record(agent_id, user_id)
            if (
                current.instance_id != record.instance_id
                or current.active_at != record.active_at
                or current.disk_failed_day != record.disk_failed_day
                or current.reminded_at is not None
            ):
                return
            current.reclaim_reason = record.reclaim_reason
            current.reminded_at = now
            current.reclaim_at = deadline
            self._save(current)

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
            turn = self._observe_use(agent_id, user_id)
            record.active_at = now
            self._cancel_reclaim(record, used=True)
            if record.running and record.instance_id:
                self._save(record)
                return record.instance_id
            self._exclusive_wakes.pop(agent_id, None)
            with self._user_lock(user_id):
                records = self._services.settings_repo.with_prefix("octop_bot:computer:").values()
                running = sum(
                    1
                    for raw in records
                    if (other := ComputerRecord.load(raw)).user_id == user_id
                    and other.agent_id != agent_id
                    and (
                        other.running
                        or (
                            other.starting
                            and other.starting_at is not None
                            and now - other.starting_at < STARTING_STALE_SECONDS
                        )
                    )
                )
                if running >= MAX_RUNNING_COMPUTERS_PER_USER:
                    raise OctopError.localized(ErrorCode.BOT_COMPUTER_LIMIT)
                record.starting = True
                record.starting_at = now
                self._save(record)
            try:
                reservation = self._billing.reserve(record, CHUNK_MINUTES)
            except BaseException:
                record.starting = False
                record.starting_at = None
                self._save(record)
                raise
            try:
                try:
                    wake = self._wake(record)
                except Exception as exc:
                    # Out of AGS capacity: pause this user's idle computer and retry.
                    if not (capacity_full(exc) and self._make_room(agent_id, user_id)):
                        raise
                    wake = self._wake(record)
            except Exception as exc:
                # Settle first: a settle that fails is kept in ``unsettled``, saved here.
                self._settle_one(record, reservation, 0)
                record.starting = False
                record.starting_at = None
                self._save(record)
                if capacity_full(exc):
                    logger.warning(
                        "no capacity for the computer of %s (codes %s): %s",
                        agent_id,
                        ",".join(error_codes(exc)) or "-",
                        exc,
                    )
                    raise OctopError.localized(ErrorCode.BOT_COMPUTER_BUSY) from exc
                raise
            # AGS says RUNNING before the desktop listens; wait so the first command works.
            try:
                self._driver.wait_ready(record.instance_id or "")
            except Exception:  # noqa: BLE001 - commands will report the failure themselves
                logger.warning("computer %s is slow to come up", agent_id)
            record.running = True
            record.starting = False
            record.starting_at = None
            record.running_since = now
            record.started_at = now
            record.paid_until = now + CHUNK_MINUTES * 60
            record.reservations = [reservation]
            self._save(record)
            assert record.instance_id is not None
            viewer_present = bool(
                record.viewed_at and now - record.viewed_at < VIEWER_GRACE_SECONDS
            )
            screen = self._screen_holders.get(agent_id)
            if (
                wake != "already_running"
                and self._controller
                and turn
                and turn.manager is None
                and not record.takeover
                and not viewer_present
                and not (
                    screen and screen[0] != turn.thread_id and now - screen[1] < SCREEN_HOLD_SECONDS
                )
            ):
                with self._controller.exclusive() as sole:
                    if sole:
                        turn.manager = self
                        self._exclusive_wakes[agent_id] = (turn, record.instance_id)
            if wake == "started" and seed is not None and not record.seeded:
                instance = record.instance_id
                try:
                    seed(lambda path, data: self._driver.write(instance, path, data))
                    record.seeded = True
                    self._save(record)
                except Exception:  # noqa: BLE001 - the computer works; files are copied next time
                    logger.warning("copying files onto the computer of %s failed", agent_id)
            waker = self._wakers.get(agent_id)
            if waker is not None:
                instance = record.instance_id
                try:
                    waker(
                        ComputerIO(
                            write=lambda path, data: self._driver.write(instance, path, data),
                            read=lambda path: self._driver.read(instance, path),
                            run=lambda command: self._driver.run(
                                instance, command, WAKE_COMMAND_TIMEOUT
                            ),
                        )
                    )
                except Exception:  # noqa: BLE001 - the computer works; files sync next time
                    logger.warning("syncing files with the computer of %s failed", agent_id)
            return record.instance_id

    def on_wake(self, agent_id: str, waker: Waker) -> None:
        """Call ``waker`` each time this Bot's computer starts or resumes, whatever woke it (a
        command, ``cloud_computer``, the user opening its screen). The latest one wins."""
        self._wakers[agent_id] = waker

    def _wake(self, record: ComputerRecord) -> Literal["started", "resumed", "already_running"]:
        """Distinguish a physical wake from adoption of a computer already running."""
        state = self._driver.state(record.instance_id) if record.instance_id else "gone"
        if state == "paused":
            self._driver.resume(record.instance_id or "")
            return "resumed"
        if state != "gone":
            return "already_running"
        # A start that times out after AGS made the instance, or a crash right after, leaves an
        # instance no record knows: the orphan scan stops it by its octop-server label.
        record.instance_id = None
        self._save(record)
        record.instance_id = self._driver.start(
            spec=record.spec,
            labels={
                "octop-user": str(record.user_id),
                "octop-bot": record.agent_id,
                "octop-server": self.server_id(),
            },
        )
        return "started"

    def _make_room(self, agent_id: str, user_id: int) -> bool:
        """Pause the user's longest-idle running computer to free AGS capacity.

        Never one in use: mid-command, acted on lately, or with its screen open.
        """
        now = self._clock()
        idle: list[ComputerRecord] = []
        for raw in self._services.settings_repo.with_prefix("octop_bot:computer:").values():
            if not isinstance(raw, str):
                continue
            try:
                other = ComputerRecord.load(raw)
            except Exception:  # noqa: BLE001 - a broken record is the reaper's to report
                continue
            if (
                other.user_id != user_id
                or other.agent_id == agent_id
                or not other.running
                or self._busy.get(other.agent_id, 0) > 0
                or now - other.viewed_at < VIEWER_GRACE_SECONDS
                or now - other.active_at < MAKE_ROOM_IDLE_SECONDS
            ):
                continue
            idle.append(other)
        for other in sorted(idle, key=lambda r: r.active_at):
            try:
                self.pause(other.agent_id, other.user_id)
            except Exception:  # noqa: BLE001 - try the next one
                logger.warning("pausing the computer of %s to make room failed", other.agent_id)
                continue
            logger.info("paused the idle computer of %s to make room", other.agent_id)
            return True
        return False

    def touch(self, agent_id: str, user_id: int) -> None:
        with self._lock(agent_id):
            self._observe_use(agent_id, user_id)
            record = self.record(agent_id, user_id)
            record.active_at = self._clock()
            self._cancel_reclaim(record, used=True)
            self._save(record)

    def _observe_use(self, agent_id: str, user_id: int) -> BackgroundComputerTurn | None:
        """Called with the Bot lock before an operation can touch its computer."""
        turn = current_background_turn(user_id, agent_id)
        claim = self._exclusive_wakes.get(agent_id)
        if claim and claim[0] is not turn:
            del self._exclusive_wakes[agent_id]
        return turn

    def forget_background_turn(self, turn: BackgroundComputerTurn) -> None:
        with self._lock(turn.agent_id):
            claim = self._exclusive_wakes.get(turn.agent_id)
            if claim and claim[0] is turn:
                del self._exclusive_wakes[turn.agent_id]

    def pause_for_handoff(self, turn: BackgroundComputerTurn) -> bool:
        with self._lock(turn.agent_id):
            claim = self._exclusive_wakes.get(turn.agent_id)
            if not turn.active or not claim or claim[0] is not turn or self._controller is None:
                return False
            del self._exclusive_wakes[turn.agent_id]
            owner = self._services.agent_repo.get(turn.agent_id)
            if owner is None or owner.user_id != turn.user_id:
                return False
            record = self.record(turn.agent_id, turn.user_id)
            if (
                not record.running
                or record.instance_id != claim[1]
                or self._busy.get(turn.agent_id, 0)
                or record.takeover
                or (record.viewed_at and self._clock() - record.viewed_at < VIEWER_GRACE_SECONDS)
            ):
                return False
            with self._controller.exclusive() as sole:
                if not sole:
                    return False
                try:
                    if self._driver.state(claim[1]) != "running":
                        return False
                    self._driver.pause(claim[1])
                except Exception:  # noqa: BLE001 - an optional handoff never substitutes a stop
                    logger.warning("background pause unavailable for computer %s", turn.agent_id)
                    return False
                self._finish_pause(record)
                return True

    def pause(self, agent_id: str, user_id: int) -> None:
        with self._lock(agent_id):
            record = self.record(agent_id, user_id)
            if not record.running:
                return
            self._exclusive_wakes.pop(agent_id, None)
            if record.instance_id:
                try:
                    self._driver.pause(record.instance_id)
                except Exception:  # noqa: BLE001 - a computer that cannot pause is stopped instead
                    logger.warning("computer %s did not pause; stopping it", agent_id)
                    self._driver.stop(record.instance_id)
                    record.instance_id = None
            self._finish_pause(record)

    def _finish_pause(self, record: ComputerRecord) -> None:
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
        if now - self._last_shadow_scan >= SHADOW_SCAN_SECONDS:
            self._last_shadow_scan = now
            try:
                self._reap_shadows(now)
            except Exception:  # noqa: BLE001 - retried on the next scan
                logger.exception("shadow Bot scan failed")

    def _reap_shadows(self, now: float) -> None:
        """Delete shadow Bots unused for a long time (the desktop was uninstalled or stopped
        using the cloud). Their computers are stopped and settled by the next pass, like any
        deleted Bot's; a computer in use keeps its shadow."""
        from octop.infra.cloud.bot_cloud.shadows import IDLE_DAYS, idle_shadows  # noqa: PLC0415

        def last_use(row: Any) -> float:
            if row.user_id is None:
                return 0.0
            record = self.record(row.agent_id, row.user_id)
            return max(record.active_at, record.viewed_at)

        for row in idle_shadows(self._services, last_use, now):
            if row.user_id is None:
                continue
            if self.record(row.agent_id, row.user_id).running or self.busy(row.agent_id):
                continue
            logger.info("deleting shadow Bot %s, unused for %s days", row.agent_id, IDLE_DAYS)
            self._services.agent_repo.delete(row.agent_id)
            self._services.settings_repo.delete(f"octop_bot:shadow:{row.agent_id}")

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
        # Before the running check: a stopped CVM computer still has a disk to pay for.
        self._charge_disk(record.agent_id, record.user_id, now)
        self._reclaim_tick(record.agent_id, record.user_id, now)
        record = self.record(record.agent_id, record.user_id)
        if not record.running:
            return
        if record.instance_id and self._driver.state(record.instance_id) == "gone":
            self._lost(record.agent_id, record.user_id)
            return
        if record.takeover:
            record = self._viewer_record(record.agent_id, record.user_id)
        busy = self._busy.get(record.agent_id, 0) > 0
        watched = now - record.viewed_at < VIEWER_GRACE_SECONDS
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

    def _charge_disk(self, agent_id: str, user_id: int, now: float) -> None:
        """Prepay today's disk once per Beijing day while the computer exists.

        A failed charge (out of credits, Lynxce down, disk not priced yet) is retried every
        ``DISK_RETRY_SECONDS``; prolonged non-payment may trigger the reclaim policy.
        """
        if not disk_billing_enabled():
            return
        disk_gb = getattr(self._driver, "disk_gb", None)
        if disk_gb is None:
            return
        day = beijing_day(now)
        with self._lock(agent_id):
            record = self.record(agent_id, user_id)
            if not record.instance_id or record.disk_paid_day == day or now < record.disk_retry_at:
                return
            try:
                size = int(disk_gb(record.instance_id))
                # A stopped computer's record is not polled otherwise; never bill a disk the
                # provider has already deleted (terminated in the console, expired).
                gone = size > 0 and self._driver.state(record.instance_id) == "gone"
            except Exception:  # noqa: BLE001 - provider hiccup, tried on the next pass
                logger.warning("checking the disk of computer %s failed", agent_id)
                return
            if size <= 0 or gone:
                return
            try:
                self._billing.charge_disk(record, day, size)
            except Exception as exc:  # noqa: BLE001 - retry transient billing failures as well
                logger.info("disk of computer %s not paid for %s; retrying later", agent_id, day)
                if isinstance(exc, DiskBalanceInsufficient):
                    record.disk_failed_day = record.disk_failed_day or day
                    record.disk_insufficient_day = day
                else:
                    record.clear_disk_arrears()
                record.disk_retry_at = now + DISK_RETRY_SECONDS
                self._save(record)
                return
            record.clear_disk_arrears()
            record.disk_paid_day = day
            record.disk_retry_at = 0.0
            self._save(record)

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

    # Screen and takeover

    def screen_ssl(self, agent_id: str, user_id: int) -> Any:
        """TLS settings for this computer's screen WebSocket when its provider pins its own CA
        (CVM); ``None`` for public certificates (AGS)."""
        instance = self.record(agent_id, user_id).instance_id
        context = getattr(self._driver, "ssl_context_for", None)
        return context(instance) if callable(context) and instance else None

    def screen(self, agent_id: str, user_id: int) -> tuple[str, dict[str, str]]:
        """Where to reach the running computer's desktop (VNC over WebSocket)."""
        instance = self.ensure_running(agent_id, user_id)
        self.viewing(agent_id, user_id)
        return self._driver.screen(instance)

    def _viewer_record(self, agent_id: str, user_id: int) -> ComputerRecord:
        """Read the current lease and finalize an expired handback under the device lock."""
        with self._lock(agent_id):
            self._exclusive_wakes.pop(agent_id, None)
            record = self.record(agent_id, user_id)
            now = self._clock()
            if record.takeover and not record.controlled(now):
                record.takeover = False
                record.check_handoff_frame = True
                record.active_at = now
                self._save(record)
            return record

    def viewing(self, agent_id: str, user_id: int) -> None:
        with self._lock(agent_id):
            record = self._viewer_record(agent_id, user_id)
            record.viewed_at = record.active_at = self._clock()
            self._cancel_reclaim(record, used=True)
            self._save(record)

    def set_takeover(self, agent_id: str, user_id: int, active: bool) -> ComputerRecord:
        with self._lock(agent_id):
            self._exclusive_wakes.pop(agent_id, None)
            record = self.record(agent_id, user_id)
            record.check_handoff_frame |= active or record.takeover
            record.takeover = active
            record.active_at = self._clock()
            self._cancel_reclaim(record, used=True)
            if active:
                # The screen opens right after; its heartbeat keeps the takeover from here.
                record.viewed_at = record.active_at
            self._save(record)
            return record

    def release_takeover_if_held(self, agent_id: str, user_id: int) -> None:
        with self._lock(agent_id):
            record = self.record(agent_id, user_id)
            if record.takeover:
                record.takeover = False
                record.check_handoff_frame = True
                record.active_at = self._clock()
                self._save(record)

    def model_screen[T](
        self,
        agent_id: str,
        user_id: int,
        taken_over: str,
        work: Callable[[ComputerDriver, str], T],
        review: Callable[[ComputerDriver, str], tuple[T, bool]],
    ) -> T | str:
        """Serialize the model's observation with human takeover and handback."""

        def observe(driver: ComputerDriver, instance: str) -> T | str:
            with self._lock(agent_id):
                record = self._viewer_record(agent_id, user_id)
                if record.takeover:
                    return taken_over
                if record.check_handoff_frame:
                    result, clear = review(driver, instance)
                    if clear:
                        record.check_handoff_frame = False
                        self._save(record)
                    return result
                return work(driver, instance)

        return self.use(agent_id, user_id, observe)

    def taken_over(self, agent_id: str, user_id: int) -> bool:
        return self._viewer_record(agent_id, user_id).takeover

    def _controlled(self, agent_id: str, user_id: int) -> str:
        """The instance the user has taken over; typing and the clipboard need takeover."""
        record = self._viewer_record(agent_id, user_id)
        if not (record.takeover and record.running and record.instance_id):
            raise OctopError.localized(ErrorCode.BOT_COMPUTER_NOT_TAKEN_OVER)
        return record.instance_id

    def paste_text(self, agent_id: str, user_id: int, text: str) -> None:
        with self._lock(agent_id):
            self._driver.paste_text(self._controlled(agent_id, user_id), text)
            self.viewing(agent_id, user_id)

    def read_clipboard(self, agent_id: str, user_id: int) -> str:
        with self._lock(agent_id):
            text = self._driver.read_clipboard(self._controlled(agent_id, user_id))
            self.viewing(agent_id, user_id)
            return text

    def close(self) -> None:
        """Stop the reaper (server shutdown): it must not touch a closed database."""
        self._stopping.set()
        if self._controller is not None:
            self._controller.close()
        reaper = self._reaper
        if reaper is not None and reaper is not threading.current_thread():
            reaper.join(timeout=REAP_INTERVAL_SECONDS)

    # Work

    @contextmanager
    def _working(
        self, agent_id: str, user_id: int, seed: Seeder | None, *, start: bool = True
    ) -> Iterator[str]:
        # Admission precedes ensure_running, so a handoff cannot cut between admission and I/O.
        with self._lock(agent_id):
            self._observe_use(agent_id, user_id)
            with self._guard:
                self._busy[agent_id] = self._busy.get(agent_id, 0) + 1
        instance = None
        try:
            if start:
                instance = self.ensure_running(agent_id, user_id, seed)
            else:
                with self._lock(agent_id):
                    record = self.record(agent_id, user_id)
                    if (
                        not record.running
                        or not record.instance_id
                        or record.controlled(self._clock())
                    ):
                        raise ComputerUnavailable(
                            "The cloud computer is paused or under human control."
                        )
                    instance = record.instance_id
            yield instance
        finally:
            with self._lock(agent_id):
                with self._guard:
                    self._busy[agent_id] -= 1
                if instance is not None:
                    record = self.record(agent_id, user_id)
                    if record.running and record.instance_id == instance:
                        self.touch(agent_id, user_id)

    def run(
        self,
        agent_id: str,
        user_id: int,
        command: str,
        timeout: int,
        *,
        seed: Seeder | None = None,
    ) -> tuple[int, str]:
        with self._working(agent_id, user_id, seed) as instance:
            self.note(agent_id, "command")
            try:
                return self._driver.run(instance, command, timeout)
            except Exception:
                if self._driver.state(instance) == "gone":
                    self._lost(agent_id, user_id)
                raise

    def note(self, agent_id: str, kind: str) -> None:
        """Remember the Bot's latest action on its computer (click, type, command, …)."""
        self._activity[agent_id] = (kind, self._clock())

    def claim_screen(self, agent_id: str, holder: str) -> bool:
        """One conversation at a time points and types on a computer's screen.

        A private chat and a group can both reach the same Bot's computer; the other waits
        until the holder has left the screen alone for SCREEN_HOLD_SECONDS.
        """
        now = self._clock()
        with self._lock(agent_id):
            current = self._screen_holders.get(agent_id)
            if current and current[0] != holder and now - current[1] < SCREEN_HOLD_SECONDS:
                return False
            claim = self._exclusive_wakes.get(agent_id)
            if claim and (
                claim[0].thread_id != holder
                or current_background_turn(claim[0].user_id, agent_id) is not claim[0]
            ):
                self._exclusive_wakes.pop(agent_id, None)
            self._screen_holders[agent_id] = (holder, now)
            return True

    def activity(self, agent_id: str) -> tuple[str, float] | None:
        return self._activity.get(agent_id)

    def busy(self, agent_id: str) -> bool:
        """The Bot is working on the computer right now (mid-command or just acted)."""
        if self._busy.get(agent_id, 0) > 0:
            return True
        last = self._activity.get(agent_id)
        return last is not None and self._clock() - last[1] < BUSY_AFTER_ACTION_SECONDS

    def glance(self, agent_id: str, user_id: int) -> Glance | None:
        """Front window title and a small thumbnail of a running computer; never starts it."""
        with self._lock(agent_id):
            self._exclusive_wakes.pop(agent_id, None)
            record = self.record(agent_id, user_id)
        if not (record.running and record.instance_id):
            return None
        now = self._clock()
        cached = self._glances.get(agent_id)
        if cached is not None and now - cached[0] < GLANCE_CACHE_SECONDS:
            return cached[1]
        output = self._driver.run_python(record.instance_id, GLANCE_SCRIPT)
        window, thumbnail = None, None
        for line in output.splitlines():
            if line.startswith("WINDOW:"):
                window = line[len("WINDOW:") :].strip() or None
            elif line.startswith("THUMB:"):
                thumbnail = line[len("THUMB:") :].strip() or None
        glance = Glance(window=window, thumbnail=thumbnail)
        self._glances[agent_id] = (now, glance)
        return glance

    def use[T](
        self,
        agent_id: str,
        user_id: int,
        work: Callable[[ComputerDriver, str], T],
        *,
        seed: Seeder | None = None,
        start: bool = True,
    ) -> T:
        """Use one instance. An inspection may only borrow an already running computer."""
        with self._working(agent_id, user_id, seed, start=start) as instance:
            return work(self._driver, instance)

    def write(
        self, agent_id: str, user_id: int, path: str, data: bytes, *, seed: Seeder | None = None
    ) -> None:
        with self._working(agent_id, user_id, seed) as instance:
            self._driver.write(instance, path, data)

    def read(
        self,
        agent_id: str,
        user_id: int,
        path: str,
        *,
        seed: Seeder | None = None,
        max_bytes: int | None = None,
    ) -> bytes | None:
        with self._working(agent_id, user_id, seed) as instance:
            if max_bytes is None:
                return self._driver.read(instance, path)
            return self._driver.read(instance, path, max_bytes=max_bytes)


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


def computer_driver() -> ComputerDriver | None:
    """The configured cloud-computer provider: Tencent Cloud CVM or AGS.

    ``OCTOP_COMPUTER_PROVIDER`` picks one (``cvm`` / ``ags``). Unset, new computers start on
    CVM when it is configured, and when AGS is configured too, computers made on AGS before the
    switch keep running there. ``None`` when nothing usable is configured.
    """
    from octop.infra.cloud.computers.cvm import CvmConfig, CvmDriver  # noqa: PLC0415
    from octop.infra.cloud.computers.mixed import MixedDriver  # noqa: PLC0415

    choice = (os.environ.get("OCTOP_COMPUTER_PROVIDER") or "").strip().lower()
    cvm_config = CvmConfig.from_env() if choice in ("", "cvm") else None
    ags_config = AgsConfig.from_env() if choice in ("", "ags") else None
    if cvm_config is not None and ags_config is not None:
        return MixedDriver(CvmDriver(cvm_config), AgsDriver(ags_config))
    if cvm_config is not None:
        return CvmDriver(cvm_config)
    return AgsDriver(ags_config) if ags_config is not None else None


def computer_manager(services: SharedServices) -> ComputerManager | None:
    """The process-wide manager, or ``None`` when no cloud-computer provider is configured."""
    global _manager
    with _manager_lock:
        if _manager is None:
            driver = computer_driver()
            if driver is None:
                return None
            database = services.config.database
            controller = None
            if os.name == "posix" and database.is_sqlite:
                controller = SingleComputerController(
                    database.resolve_sqlite_path(services.paths.root)
                )
            _manager = ComputerManager(
                services, driver, billing=billing_for(services), controller=controller
            )
            # Computers left running by a previous process are billed and paused from now on,
            # not from their next tool call.
            _manager._start_reaper()
        return _manager
