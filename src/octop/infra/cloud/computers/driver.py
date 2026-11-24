"""Tencent Cloud Agent Sandbox Service (AGS): one cloud computer per Octop Bot.

Lifecycle (start, pause, resume, stop, state) goes through the AGS cloud API with a CAM
sub-account key. Commands and files go through the desktop's own HTTP server on port 5000 of
the OSWorld sandbox (``/execute``, ``/setup/upload``, ``/file``), reached at
``https://5000-<instance>.<domain>`` with the instance's access token. OSWorld sandboxes do not
serve AGS's E2B-compatible data plane, and run everything as ``user`` without sudo, so the
workspace lives in that user's home. Everything is configured from the environment:

- ``OCTOP_AGS_SECRET_ID`` / ``OCTOP_AGS_SECRET_KEY``: CAM sub-account allowed to manage AGS.
- ``OCTOP_AGS_REGION``: default ``ap-guangzhou``.
- ``OCTOP_AGS_DOMAIN``: default ``<region>.tencentags.com``.
- ``OCTOP_AGS_TOOL`` / ``OCTOP_AGS_TOOL_PRO``: sandbox tool names for the standard / pro specs
  (OSWorld tools created in the AGS console).
- ``OCTOP_AGS_TIMEOUT``: only for time-limited tools, how long an instance may run before AGS
  stops it (e.g. ``6h``). Persistent tools take no timeout; the idle reaper pauses them.
"""

from __future__ import annotations

import base64
import os
import shlex
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

Spec = Literal["standard", "pro"]

# The Bot's workspace inside the sandbox; the agent sees it as ``/``.
WORKSPACE = "/home/user/workspace"
# Commands run detached and leave their output here until it is collected.
_RUNS = "/home/user/.octop/runs"
# The desktop server kills a request's command after 120 s, so each request waits less.
_WAIT_SECONDS = 90
_PENDING = "__octop_pending__"
# x11vnc listens on 5900, which AGS does not route; the bridge relays it to this port.
_SCREEN_PORT = 8080
_BRIDGE = "/home/user/.octop/vnc_bridge.py"
# Presses the paste shortcut in the focused window through XTest (the image has no xdotool);
# terminals paste with Ctrl+Shift+V.
_PRESS_PASTE = """
import time
from Xlib import X, XK, display
from Xlib.ext import xtest
d = display.Display()
root = d.screen().root
name = ""
try:
    active = root.get_full_property(d.intern_atom("_NET_ACTIVE_WINDOW"), X.AnyPropertyType)
    window = d.create_resource_object("window", active.value[0])
    name = " ".join(window.get_wm_class() or ()).lower()
except Exception:
    pass
terminal = any(t in name for t in ("terminal", "xterm", "konsole", "terminator", "kitty", "tilix"))
keys = ["Control_L"] + (["Shift_L"] if terminal else []) + ["v"]
codes = [d.keysym_to_keycode(XK.string_to_keysym(k)) for k in keys]
for code in codes:
    xtest.fake_input(d, X.KeyPress, code)
    d.sync()
    time.sleep(0.02)
for code in reversed(codes):
    xtest.fake_input(d, X.KeyRelease, code)
    d.sync()
"""
State = Literal["running", "paused", "starting", "gone"]


@dataclass(frozen=True)
class Instance:
    instance_id: str
    state: State
    labels: Mapping[str, str]
    created_at: float


class ComputerDriver(Protocol):
    """What the computer manager needs from a sandbox provider (sync; call off the event loop)."""

    def start(self, *, spec: Spec, labels: Mapping[str, str]) -> str: ...
    def resume(self, instance_id: str) -> None: ...
    def pause(self, instance_id: str) -> None: ...
    def stop(self, instance_id: str) -> None: ...
    def state(self, instance_id: str) -> State: ...
    def stopped_at(self, instance_id: str) -> float | None: ...
    def instances(self) -> list[Instance]: ...
    def run(self, instance_id: str, command: str, timeout: int) -> tuple[int, str]: ...
    def write(self, instance_id: str, path: str, data: bytes) -> None: ...
    def read(
        self, instance_id: str, path: str, *, max_bytes: int | None = None
    ) -> bytes | None: ...
    def screen(self, instance_id: str) -> tuple[str, dict[str, str]]: ...
    def screenshot(self, instance_id: str) -> bytes: ...
    def accessibility(self, instance_id: str) -> str: ...
    def run_python(self, instance_id: str, code: str) -> str: ...
    def wait_ready(self, instance_id: str, timeout: float = 90.0) -> None: ...
    def paste_text(self, instance_id: str, text: str) -> None: ...
    def read_clipboard(self, instance_id: str) -> str: ...


@dataclass(frozen=True)
class AgsConfig:
    secret_id: str
    secret_key: str
    region: str
    domain: str
    tools: Mapping[Spec, str]
    timeout: str | None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AgsConfig | None:
        source = os.environ if env is None else env

        def read(name: str) -> str:
            return (source.get(f"OCTOP_AGS_{name}") or "").strip()

        secret_id, secret_key, tool = read("SECRET_ID"), read("SECRET_KEY"), read("TOOL")
        if not (secret_id and secret_key and tool):
            return None
        region = read("REGION") or "ap-guangzhou"
        return cls(
            secret_id=secret_id,
            secret_key=secret_key,
            region=region,
            domain=read("DOMAIN") or f"{region}.tencentags.com",
            tools={"standard": tool, "pro": read("TOOL_PRO") or tool},
            timeout=read("TIMEOUT") or None,
        )


_RUNNING = {"RUNNING"}
_STARTING = {"STARTING", "RESUMING", "PENDING"}
_PAUSED = {"PAUSED", "PAUSING"}


def _timestamp(value: str | None) -> float:
    """AGS ISO-8601 time → Unix time; unknown counts as brand new (never reaped by age).

    A time without a zone is UTC, never this server's local time (which would make a starting
    instance look hours old to the orphan scan).
    """
    from datetime import UTC, datetime  # noqa: PLC0415

    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return time.time()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


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
        self._http: Any = None
        self._tokens: dict[str, str] = {}
        self._lock = threading.Lock()

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
        if self._config.timeout:
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
        if self._config.timeout:
            request.Timeout = self._config.timeout
        self._api().ResumeSandboxInstance(request)

    def pause(self, instance_id: str) -> None:
        request = self._models().PauseSandboxInstanceRequest()
        request.InstanceId = instance_id
        self._api().PauseSandboxInstance(request)

    def stop(self, instance_id: str) -> None:
        self._tokens.pop(instance_id, None)
        request = self._models().StopSandboxInstanceRequest()
        request.InstanceId = instance_id
        self._api().StopSandboxInstance(request)

    def state(self, instance_id: str) -> State:
        request = self._models().DescribeSandboxInstancesRequest()
        request.InstanceIds = [instance_id]
        found = self._api().DescribeSandboxInstances(request).InstanceSet or []
        return state_of(found[0].Status) if found else "gone"

    def stopped_at(self, instance_id: str) -> float | None:
        """When AGS stopped this instance (its last update), or None if it cannot tell."""
        request = self._models().DescribeSandboxInstancesRequest()
        request.InstanceIds = [instance_id]
        found = self._api().DescribeSandboxInstances(request).InstanceSet or []
        if not found or state_of(found[0].Status) != "gone" or not found[0].UpdateTime:
            return None
        return _timestamp(found[0].UpdateTime)

    def instances(self) -> list[Instance]:
        """Every instance in this AGS account and region (for cleaning up lost starts)."""
        found: list[Instance] = []
        offset = 0
        while True:
            request = self._models().DescribeSandboxInstanceListRequest()
            request.Offset, request.Limit = offset, 100
            page = self._api().DescribeSandboxInstanceList(request).InstanceSet or []
            for item in page:
                labels = {m.Name: m.Value for m in (item.Metadata or []) if m.Name}
                found.append(
                    Instance(
                        instance_id=str(item.InstanceId),
                        state=state_of(item.Status),
                        labels=labels,
                        created_at=_timestamp(item.CreateTime),
                    )
                )
            if len(page) < 100:
                return found
            offset += 100

    # -- data plane: the desktop's HTTP server ---------------------------------

    def url(self, instance_id: str, port: int, path: str, *, scheme: str = "https") -> str:
        return f"{scheme}://{port}-{instance_id}.{self._config.domain}{path}"

    def token(self, instance_id: str, *, fresh: bool = False) -> str:
        """The instance's access token (``X-Access-Token``); AGS issues one per instance."""
        with self._lock:
            if fresh:
                self._tokens.pop(instance_id, None)
            token = self._tokens.get(instance_id)
        if token is None:
            request = self._models().AcquireSandboxInstanceTokenRequest()
            request.InstanceId = instance_id
            token = str(self._api().AcquireSandboxInstanceToken(request).Token)
            with self._lock:
                self._tokens[instance_id] = token
        return token

    def _request(
        self, instance_id: str, path: str, *, timeout: float, method: str = "POST", **kwargs: Any
    ) -> Any:
        import httpx  # noqa: PLC0415

        if self._http is None:
            self._http = httpx.Client()
        stream = kwargs.pop("stream", False)
        for attempt in range(2):
            request = self._http.build_request(
                method,
                self.url(instance_id, 5000, path),
                headers={"X-Access-Token": self.token(instance_id, fresh=attempt > 0)},
                timeout=timeout,
                **kwargs,
            )
            response = self._http.send(request, stream=stream)
            if response.status_code not in (401, 403):
                return response
            if attempt == 0:
                response.close()
        return response

    def _execute(self, instance_id: str, script: str) -> str:
        response = self._request(
            instance_id,
            "/execute",
            json={"command": script, "shell": True},
            timeout=_WAIT_SECONDS + 30,
        )
        body = (
            response.json()
            if response.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        if response.status_code != 200 or body.get("status") != "success":
            message = body.get("message") or body.get("error") or response.text
            raise RuntimeError(f"cloud computer command failed ({response.status_code}): {message}")
        return str(body.get("output") or "")

    def run(self, instance_id: str, command: str, timeout: int) -> tuple[int, str]:
        """Run ``command`` with bash in the workspace, however long it takes (up to ``timeout``).

        The command runs detached, so it outlives the desktop server's 120 s request limit;
        each request waits up to ``_WAIT_SECONDS`` for it and then collects the output.
        """
        run = f"{_RUNS}/{uuid.uuid4().hex}"
        out, code, pid = (shlex.quote(f"{run}/{name}") for name in ("out", "rc", "pid"))
        inner = (
            f"cd {WORKSPACE} && bash -c {shlex.quote(command)} > {out} 2>&1 < /dev/null; "
            f"echo $? > {code}.tmp; mv {code}.tmp {code}"
        )
        collect = f"cat {code}; cat {out} 2>/dev/null; rm -rf {shlex.quote(run)}"
        deadline = time.monotonic() + timeout
        script = (
            f"mkdir -p {shlex.quote(run)} {WORKSPACE} || exit 1; "
            f"setsid bash -c {shlex.quote(inner)} > /dev/null 2>&1 < /dev/null & echo $! > {pid}; "
        )
        while True:
            rounds = max(1, min(_WAIT_SECONDS, int(deadline - time.monotonic())) * 2)
            script += (
                f"for i in $(seq 1 {rounds}); do [ -f {code} ] && break; sleep 0.5; done; "
                f"if [ -f {code} ]; then {collect}; else echo {_PENDING}; fi"
            )
            output = self._execute(instance_id, script)
            if output.strip() != _PENDING:
                first, _, rest = output.partition("\n")
                return int(first.strip() or 1), rest
            if time.monotonic() >= deadline:
                break
            script = ""
        tail = self._execute(
            instance_id,
            f"kill -KILL -- -$(cat {pid}) 2>/dev/null; cat {out} 2>/dev/null; "
            f"rm -rf {shlex.quote(run)}",
        )
        return 124, f"{tail}\nCommand timed out after {timeout}s"

    def write(self, instance_id: str, path: str, data: bytes) -> None:
        response = self._request(
            instance_id,
            "/setup/upload",
            data={"file_path": path},
            files={"file_data": (path.rsplit("/", 1)[-1] or "file", data)},
            timeout=120,
        )
        if response.status_code != 200:
            raise OSError(f"upload of {path} failed ({response.status_code}): {response.text}")

    def read(self, instance_id: str, path: str, *, max_bytes: int | None = None) -> bytes | None:
        response = self._request(
            instance_id, "/file", data={"file_path": path}, timeout=120, stream=True
        )
        try:
            if response.status_code == 404:
                return None
            if response.status_code != 200:
                raise OSError(f"download of {path} failed ({response.status_code})")
            if max_bytes is None:
                return bytes(response.read())
            data = bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk[: max_bytes - len(data)])
                if len(data) >= max_bytes:
                    break
            return bytes(data)
        finally:
            response.close()

    def screen(self, instance_id: str) -> tuple[str, dict[str, str]]:
        """The desktop's VNC over WebSocket, and the header that opens it.

        The desktop runs x11vnc on 5900, which AGS does not route; ``vnc_bridge.py`` relays it
        to 8080, which it does. The bridge is uploaded and started on first view and keeps
        running across pauses. Only this server ever holds the access token; browsers reach the
        screen through Octop.
        """
        listening = f"ss -ltn | grep -q ':{_SCREEN_PORT} '"
        if self._execute(instance_id, f"{listening} && echo up || echo down").strip() != "up":
            self.write(instance_id, _BRIDGE, (Path(__file__).parent / "vnc_bridge.py").read_bytes())
            self._execute(
                instance_id,
                f"nohup python3 {_BRIDGE} {_SCREEN_PORT} 5900 > /dev/null 2>&1 < /dev/null & "
                f"for i in $(seq 1 20); do {listening} && break; sleep 0.25; done",
            )
        url = self.url(instance_id, _SCREEN_PORT, "/websockify", scheme="wss")
        return url, {"X-Access-Token": self.token(instance_id)}

    def paste_text(self, instance_id: str, text: str) -> None:
        """Type ``text`` (any language) at the desktop's cursor by pasting it.

        VNC key events cannot carry Chinese or other IME text, so the text goes onto the
        desktop's clipboard (``xclip``, which stays behind as the selection owner) and the
        paste shortcut is pressed; the text stays on the clipboard afterwards.
        """
        encoded = base64.b64encode(text.encode()).decode()
        # xclip stays behind owning the selection; its output must not hold /execute open.
        output = self._execute(
            instance_id,
            f"printf %s {encoded} | base64 -d | xclip -selection clipboard -i > /dev/null 2>&1; "
            f'[ "$(timeout 3 xclip -selection clipboard -o 2>/dev/null | base64 -w0)" = {encoded} ] '
            f"&& python3 -c {shlex.quote(_PRESS_PASTE)} && echo pasted",
        )
        if output.strip() != "pasted":
            raise RuntimeError(f"pasting into the cloud computer failed: {output.strip()[:200]}")

    def read_clipboard(self, instance_id: str) -> str:
        """The desktop's clipboard as text; empty when it holds no text."""
        return self._execute(
            instance_id, "timeout 3 xclip -selection clipboard -o 2>/dev/null || true"
        )

    # -- computer use -----------------------------------------------------------

    def wait_ready(self, instance_id: str, timeout: float = 90.0) -> None:
        """After a start or resume: wait until the desktop's server answers and its screen is up.

        AGS reports RUNNING before the desktop service listens; actions in that window fail
        with 502/503.
        """
        deadline = time.monotonic() + timeout
        probe = "import pyautogui; print(pyautogui.size())"
        while True:
            try:
                response = self._request(
                    instance_id, "/run_python", json={"code": probe}, timeout=15
                )
                if response.status_code == 200 and response.json().get("status") == "success":
                    return
            except Exception:  # noqa: BLE001 - not listening yet
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError("the cloud computer did not come up in time")
            time.sleep(1.5)

    def screenshot(self, instance_id: str) -> bytes:
        """The whole desktop with the pointer, as PNG (1920x1080)."""
        response = self._request(instance_id, "/screenshot", method="GET", timeout=60)
        if response.status_code != 200:
            raise RuntimeError(f"screenshot failed ({response.status_code}): {response.text}")
        return bytes(response.content)

    def accessibility(self, instance_id: str) -> str:
        """The desktop's AT-SPI tree as XML (roles, names, screen coordinates)."""
        response = self._request(instance_id, "/accessibility", method="GET", timeout=60)
        if response.status_code != 200:
            raise RuntimeError(f"accessibility failed ({response.status_code}): {response.text}")
        return str(response.json().get("AT") or "")

    def run_python(self, instance_id: str, code: str) -> str:
        """Run a short Python script on the desktop (pyautogui is there); its output."""
        response = self._request(instance_id, "/run_python", json={"code": code}, timeout=60)
        body = response.json() if response.status_code in (200, 500) else {}
        if response.status_code != 200 or body.get("status") != "success":
            message = body.get("message") or body.get("error") or response.text
            raise RuntimeError(f"desktop action failed: {message}")
        return str(body.get("output") or "")
