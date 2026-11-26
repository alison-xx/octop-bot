"""Await side effects that must finish before releasing their owning resource."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any


async def finish[T](operation: Coroutine[Any, Any, T]) -> T:
    """Finish a side effect, including when the caller is cancelled."""
    task = asyncio.create_task(operation)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        task.result()
        raise
