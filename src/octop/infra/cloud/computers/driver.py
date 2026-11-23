"""Tencent Cloud Agent Sandbox Service (AGS): one cloud computer per Octop Bot.

Lifecycle (start, pause, resume, stop, state) goes through the AGS cloud API with a CAM
sub-account key. Commands and files go through AGS's E2B-compatible data plane with the E2B
SDK, connected to the same instance id. Everything is configured from the environment:

- ``OCTOP_AGS_SECRET_ID`` / ``OCTOP_AGS_SECRET_KEY``: CAM sub-account allowed to manage AGS.
- ``OCTOP_AGS_REGION``: default ``ap-guangzhou``.
- ``OCTOP_AGS_API_KEY``: the AGS console API key used by the E2B SDK.
- ``OCTOP_AGS_DOMAIN``: default ``<region>.tencentags.com``.
- ``OCTOP_AGS_TOOL`` / ``OCTOP_AGS_TOOL_PRO``: sandbox tool names for the standard / pro specs.
- ``OCTOP_AGS_TIMEOUT``: how long an instance may run before AGS stops it (default ``6h``).

This is a fork-layer adapter until octop-harness grows an E2B-compatible backend.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

Spec = Literal["standard", "pro"]
State = Literal["running", "paused", "starting", "gone"]


class ComputerDriver(Protocol):
    """What the computer manager needs from a sandbox provider (sync; call off the event loop)."""

    def start(self, *, spec: Spec, labels: Mapping[str, str]) -> str: ...
    def resume(self, instance_id: str) -> None: ...
    def pause(self, instance_id: str) -> None: ...
    def stop(self, instance_id: str) -> None: ...
    def state(self, instance_id: str) -> State: ...
    def run(self, instance_id: str, command: str, timeout: int) -> tuple[int, str]: ...
    def write(self, instance_id: str, path: str, data: bytes) -> None: ...
    def read(self, instance_id: str, path: str) -> bytes | None: ...


@dataclass(frozen=True)
class AgsConfig:
    secret_id: str
    secret_key: str
    region: str
    api_key: str
    domain: str
    tools: Mapping[Spec, str]
    timeout: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AgsConfig | None:
        source = os.environ if env is None else env

        def read(name: str) -> str:
            return (source.get(f"OCTOP_AGS_{name}") or "").strip()

        secret_id, secret_key, api_key, tool = (
            read("SECRET_ID"),
            read("SECRET_KEY"),
            read("API_KEY"),
            read("TOOL"),
        )
        if not (secret_id and secret_key and api_key and tool):
            return None
        region = read("REGION") or "ap-guangzhou"
        return cls(
            secret_id=secret_id,
            secret_key=secret_key,
            region=region,
            api_key=api_key,
            domain=read("DOMAIN") or f"{region}.tencentags.com",
            tools={"standard": tool, "pro": read("TOOL_PRO") or tool},
            timeout=read("TIMEOUT") or "6h",
        )


_RUNNING = {"RUNNING"}
_STARTING = {"STARTING", "RESUMING", "PENDING"}
_PAUSED = {"PAUSED", "PAUSING"}


def state_of(status: str | None) -> State:
    """AGS instance status → manager state; anything stopped, failed or unknown is gone."""
    value = (status or "").upper()
    if value in _RUNNING:
        return "running"
    if value in _STARTING:
        return "starting"
    if value in _PAUSED:
        return "paused"
    return "gone"


class AgsDriver:
    def __init__(self, config: AgsConfig) -> None:
        self._config = config
        self._client: Any = None

    def _api(self) -> Any:
        if self._client is None:
            from tencentcloud.ags.v20250920 import ags_client  # noqa: PLC0415
            from tencentcloud.common.credential import Credential  # noqa: PLC0415

            self._client = ags_client.AgsClient(
                Credential(self._config.secret_id, self._config.secret_key), self._config.region
            )
        return self._client

    @staticmethod
    def _models() -> Any:
        from tencentcloud.ags.v20250920 import models  # noqa: PLC0415

        return models

    def start(self, *, spec: Spec, labels: Mapping[str, str]) -> str:
        models = self._models()
        request = models.StartSandboxInstanceRequest()
        request.ToolName = self._config.tools[spec]
        request.Timeout = self._config.timeout
        metadata = []
        for name, value in labels.items():
            item = models.MetadataVar()
            item.Name, item.Value = name, value
            metadata.append(item)
        request.Metadata = metadata
        response = self._api().StartSandboxInstance(request)
        return str(response.Instance.InstanceId)

    def resume(self, instance_id: str) -> None:
        request = self._models().ResumeSandboxInstanceRequest()
        request.InstanceId = instance_id
        request.Timeout = self._config.timeout
        self._api().ResumeSandboxInstance(request)

    def pause(self, instance_id: str) -> None:
        request = self._models().PauseSandboxInstanceRequest()
        request.InstanceId = instance_id
        self._api().PauseSandboxInstance(request)

    def stop(self, instance_id: str) -> None:
        request = self._models().StopSandboxInstanceRequest()
        request.InstanceId = instance_id
        self._api().StopSandboxInstance(request)

    def state(self, instance_id: str) -> State:
        request = self._models().DescribeSandboxInstancesRequest()
        request.InstanceIds = [instance_id]
        found = self._api().DescribeSandboxInstances(request).InstanceSet or []
        return state_of(found[0].Status) if found else "gone"

    def _sandbox(self, instance_id: str) -> Any:
        from e2b import Sandbox  # noqa: PLC0415

        return Sandbox.connect(
            instance_id, api_key=self._config.api_key, domain=self._config.domain
        )

    def run(self, instance_id: str, command: str, timeout: int) -> tuple[int, str]:
        from e2b.sandbox.commands.command_handle import CommandExitException  # noqa: PLC0415

        try:
            result = self._sandbox(instance_id).commands.run(command, timeout=timeout)
        except CommandExitException as failed:
            result = failed
        output = result.stdout or ""
        if (result.stderr or "").strip():
            output = f"{output}\n{result.stderr}" if output else result.stderr
        return int(result.exit_code or 0), output

    def write(self, instance_id: str, path: str, data: bytes) -> None:
        self._sandbox(instance_id).files.write(path, data)

    def read(self, instance_id: str, path: str) -> bytes | None:
        from e2b.exceptions import NotFoundException  # noqa: PLC0415

        try:
            return bytes(self._sandbox(instance_id).files.read(path, format="bytes"))
        except NotFoundException:
            return None
