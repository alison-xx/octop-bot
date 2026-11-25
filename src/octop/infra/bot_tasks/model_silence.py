"""Watch one model invocation without ever restarting a tool or an agent graph."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.runnables.config import ensure_config, merge_configs, set_config_context

SILENT_SECONDS = 120.0


class ModelSilence(Exception):
    """No model output arrived within the task's idle window."""


class _ModelOutput(AsyncCallbackHandler):
    run_inline = True

    def __init__(self, timer: asyncio.Timeout) -> None:
        self._timer = timer

    async def on_llm_new_token(self, token: Any, **kwargs: Any) -> None:
        if not self._timer.expired():
            self._timer.reschedule(asyncio.get_running_loop().time() + SILENT_SECONDS)


async def watch_model_output[T](invoke: Callable[[], Awaitable[T]]) -> T:
    timer = asyncio.timeout(SILENT_SECONDS)
    config = merge_configs(ensure_config(), {"callbacks": [_ModelOutput(timer)]})

    async def run() -> T:
        return await invoke()

    try:
        async with timer:
            with set_config_context(config) as context:
                return await asyncio.create_task(run(), context=context)
    except TimeoutError as exc:
        if timer.expired():
            raise ModelSilence from exc
        raise
