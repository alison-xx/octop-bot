"""A trusted background turn may return only the computer it exclusively woke."""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from filelock import FileLock

if TYPE_CHECKING:
    from octop.infra.cloud.computers.manager import ComputerManager


@dataclass(eq=False)
class BackgroundComputerTurn:
    user_id: int
    agent_id: str
    thread_id: str
    manager: ComputerManager | None = field(default=None, init=False, repr=False)
    active: bool = field(default=True, init=False, repr=False)


_current: ContextVar[BackgroundComputerTurn | None] = ContextVar(
    "background_computer", default=None
)


@contextmanager
def background_computer_turn(
    user_id: int, agent_id: str, thread_id: str
) -> Iterator[BackgroundComputerTurn]:
    """Bind once at trusted cron/IM turn entry. The handle stays in this execution."""
    turn = BackgroundComputerTurn(user_id, agent_id, thread_id)
    token = _current.set(turn)
    try:
        yield turn
    finally:
        turn.active = False
        if turn.manager is not None:
            turn.manager.forget_background_turn(turn)
        _current.reset(token)


def current_background_turn(user_id: int, agent_id: str) -> BackgroundComputerTurn | None:
    turn = _current.get()
    if (
        turn
        and turn.active
        and turn.thread_id
        and (turn.user_id, turn.agent_id) == (user_id, agent_id)
    ):
        return turn
    return None


def pause_background_computer(turn: BackgroundComputerTurn | None = None) -> bool:
    """After the pending card commits. Never look up, create or wake a manager/instance."""
    turn = turn or _current.get()
    return bool(turn and turn.active and turn.manager and turn.manager.pause_for_handoff(turn))


class SingleComputerController:
    """Prove this manager has been alone since startup on the shared POSIX SQLite volume.

    Each process holds a shared lock for its lifetime. A joining controller invalidates the
    old generation before it can serve requests. The registration lock excludes new controllers
    while an eligible one pauses. Replicas with PostgreSQL cannot use a host-local witness.
    """

    def __init__(self, database: Path) -> None:
        database = database.resolve()
        path = database.with_name(database.name + ".computer-controllers")
        self._join = FileLock(str(path) + ".lock")
        self._generation = uuid.uuid4().hex.encode()
        self._pid = os.getpid()
        self._file: BinaryIO
        if sys.platform == "win32":
            raise NotImplementedError("Single-controller detection requires POSIX flock")
        import fcntl  # noqa: PLC0415

        with self._join:
            self._file = path.open("a+b")
            fcntl.flock(self._file, fcntl.LOCK_SH)
            try:
                fcntl.flock(self._file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                marker = self._generation
            except BlockingIOError:
                marker = b""
            finally:
                fcntl.flock(self._file, fcntl.LOCK_SH)
            self._file.seek(0)
            self._file.truncate()
            self._file.write(marker)
            self._file.flush()

    @contextmanager
    def exclusive(self) -> Iterator[bool]:
        with self._join:
            if self._file.closed or self._pid != os.getpid():
                yield False
                return
            self._file.seek(0)
            yield self._file.read() == self._generation

    def close(self) -> None:
        with self._join:
            self._file.close()
