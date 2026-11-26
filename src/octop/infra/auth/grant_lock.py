"""Serialize tenant credential changes across processes sharing a control plane."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any, Literal

from filelock import AsyncFileLock

from octop.infra.db.pool import PostgresPool
from octop.infra.db.services import SharedServices


def grant_lock(
    services: SharedServices, user_id: int, kind: Literal["cloud", "oauth", "cloud-key"]
) -> AbstractAsyncContextManager[Any]:
    namespace = f"lynxce-{kind}"
    if isinstance(services.db, PostgresPool):
        return services.db.advisory_lock(namespace, user_id)
    return AsyncFileLock(services.paths.root / f".{namespace}-{user_id}.lock")
