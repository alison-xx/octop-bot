"""Two providers at once: new computers on CVM, computers made earlier stay where they are.

Switching a server from AGS to CVM must not strand the Bots that already have an AGS computer
(their files are on its disk). Each call goes to the provider that owns the instance: CVM ids
start with ``ins-``; anything else was made by AGS. New computers start on the primary.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from octop.infra.cloud.computers.driver import AgsDriver, Instance, Spec, State


def is_cvm_instance(instance_id: str) -> bool:
    return instance_id.startswith("ins-")


class MixedDriver:
    def __init__(self, cvm: Any, ags: AgsDriver) -> None:
        self._cvm = cvm
        self._ags = ags

    def _for(self, instance_id: str) -> Any:
        return self._cvm if is_cvm_instance(instance_id) else self._ags

    def start(self, *, spec: Spec, labels: Mapping[str, str]) -> str:
        return str(self._cvm.start(spec=spec, labels=labels))

    def instances(self) -> list[Instance]:
        return [*self._cvm.instances(), *self._ags.instances()]

    def ssl_context_for(self, instance_id: str) -> Any:
        """CVM computers pin the instance CA; AGS computers use public certificates."""
        return self._cvm.ssl_context_for(instance_id) if is_cvm_instance(instance_id) else None

    def screen(self, instance_id: str) -> tuple[str, dict[str, str]]:
        return self._for(instance_id).screen(instance_id)  # type: ignore[no-any-return]

    def state(self, instance_id: str) -> State:
        return self._for(instance_id).state(instance_id)  # type: ignore[no-any-return]

    def __getattr__(self, name: str) -> Any:
        """Every other per-instance call (run, read, write, pause, ...) by its first argument."""

        def route(instance_id: str, *args: Any, **kwargs: Any) -> Any:
            return getattr(self._for(instance_id), name)(instance_id, *args, **kwargs)

        return route
