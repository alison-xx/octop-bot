"""Per-Bot control of explicitly selected local application windows."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from octop.infra.control.desktop.setup import desktop_status
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import User
from octop.infra.users.permissions import user_has_permission

Level = Literal["off", "view", "background", "foreground"]
Action = Literal["windows", "read", "click", "set_value", "handoff"]
_BLOCKED = {
    "octop",
    "octop-desktop",
    "electron",
    "codex",
    "dsh",
    "dsbot",
    "dsh-desktop",
    "cua-driver",
    "control",
    "systemsettings",
    "system settings",
    "settings",
    "credentialmanager",
    "credential manager",
    "credwiz",
    "passwords",
    "keychain access",
    "1password",
    "bitwarden",
    "keepass",
    "keepassxc",
    "lastpass",
    "dashlane",
}


class AllowedApp(BaseModel):
    id: str
    name: str


class ComputerPolicy(BaseModel):
    level: Level = "off"
    apps: list[AllowedApp] = Field(default_factory=list)


class ComputerState(ComputerPolicy):
    available: bool
    paused: bool
    active_app: str | None
    # macOS privacy grants this app still lacks ("screen_recording", "accessibility").
    # Without them the screen stream is refused and the Bot cannot use any window.
    permissions_needed: list[str] = Field(default_factory=list)


class NativeWindows:
    """The optional SDK never receives an unscoped action or a full desktop capture."""

    def __init__(self) -> None:
        self.driver: Any = None

    def connect(self) -> Any:
        if self.driver is None:
            sdk = importlib.import_module("cua_driver")
            self.driver = sdk.CuaDriver.create()
        return self.driver

    async def apps(self) -> dict[int, AllowedApp]:
        sdk = importlib.import_module("cua_driver")
        result = await self.connect().list_apps(sdk.ListAppsInput())
        return await asyncio.to_thread(self.running_apps, result.apps)

    @staticmethod
    def running_apps(rows: list[Any]) -> dict[int, AllowedApp]:
        psutil = importlib.import_module("psutil")
        apps = {}
        for row in rows:
            if not row.running or not row.pid:
                continue
            try:
                executable = psutil.Process(row.pid).exe()
            except (psutil.Error, OSError):
                continue
            if not executable:
                continue
            path = os.path.normcase(os.path.realpath(executable))
            if {Path(path).stem.casefold(), row.name.strip().casefold()} & _BLOCKED:
                continue
            if any(
                name in path.casefold()
                for name in ("keychain access.app", "system settings.app", "passwords.app")
            ):
                continue
            apps[row.pid] = AllowedApp(id=hashlib.sha256(path.encode()).hexdigest(), name=row.name)
        return apps

    async def windows(self, pid: int) -> list[dict[str, Any]]:
        sdk = importlib.import_module("cua_driver")
        result = await self.connect().list_windows(
            sdk.ListWindowsInput(pid=pid, on_screen_only=True)
        )
        return [
            {"pid": pid, "window_id": w.window_id, "title": w.title}
            for w in result.windows
            if w.pid == pid
        ]

    async def read(self, session: str, pid: int, window_id: int) -> list[dict[str, Any]]:
        sdk = importlib.import_module("cua_driver")
        result = await self.connect().get_window_state(
            sdk.GetWindowStateInput(
                pid=pid,
                window_id=window_id,
                session=session,
                query=None,
                include_accessibility_tree=True,
                include_screenshot=False,
                screenshot_out_file=None,
                max_elements=200,
                max_depth=None,
                max_dimension=None,
                max_image_dimension=None,
                timeout_ms=4000,
            )
        )
        return [
            {
                "token": e.element_token,
                "role": e.role,
                "label": e.label,
                "value": e.value,
                "actions": e.actions,
            }
            for e in (result.elements or [])
        ]

    async def act(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        import json

        result = await self.connect().call_tool(action, json.dumps(args))
        return {"ok": not result.is_error, "message": result.text[:3000], "code": result.error_code}

    async def close(self) -> None:
        if self.driver is not None:
            await self.driver.shutdown()
            self.driver = None


class BotComputer:
    def __init__(self) -> None:
        self.native = NativeWindows()
        self.active: dict[str, tuple[int, str]] = {}
        self.foreground = False
        self.observed: dict[tuple[int, str], tuple[int, int, set[str]]] = {}

    @staticmethod
    def available() -> bool:
        return importlib.util.find_spec("cua_driver") is not None

    @staticmethod
    def permissions_needed() -> list[str]:
        """Missing macOS grants, probed without prompting; none elsewhere."""
        if sys.platform != "darwin":
            return []
        return list(desktop_status().permissions_needed)

    @staticmethod
    def key(repos: RepoBundle, owner: int, bot: str) -> str:
        row = repos.agent_repo.get(bot)
        if row is None or row.user_id != owner or row.kind != "expert" or row.is_shared:
            raise OctopError.localized(ErrorCode.AGENT_NOT_FOUND)
        account = repos.user_repo.get(owner)
        if (
            account is None
            or account.disabled
            or not user_has_permission(
                User(
                    owner,
                    account.username,
                    account.role,
                    account.display_name,
                    permissions=account.permissions,
                ),
                "desktop",
            )
        ):
            raise OctopError.localized(ErrorCode.FORBIDDEN)
        return f"octop_bot:computer:{owner}:{bot}"

    def state(self, repos: RepoBundle, owner: int, bot: str) -> ComputerState:
        key = self.key(repos, owner, bot)
        policy = ComputerPolicy.model_validate_json(repos.settings_repo.get(key) or "{}")
        active_app = next(
            (app.name for app in policy.apps if self.active.get(app.id) == (owner, bot)), None
        )
        return ComputerState(
            **policy.model_dump(),
            available=self.available(),
            permissions_needed=self.permissions_needed() if self.available() else [],
            paused=bool(repos.settings_repo.get(key + ":pause")),
            active_app=active_app,
        )

    async def choices(self) -> list[AllowedApp]:
        if not self.available():
            return []
        apps = await self.native.apps()
        return sorted({a.id: a for a in apps.values()}.values(), key=lambda a: a.name.casefold())

    async def configure(
        self, repos: RepoBundle, owner: int, bot: str, level: Level, app_ids: list[str]
    ) -> ComputerState:
        old = await asyncio.to_thread(self.state, repos, owner, bot)
        apps = {a.id: a for a in old.apps}
        if any(i not in apps for i in app_ids):
            apps.update({a.id: a for a in await self.choices()})
        if any(i not in apps for i in app_ids):
            raise OctopError.localized(ErrorCode.NOT_FOUND)
        key = await asyncio.to_thread(self.key, repos, owner, bot)
        policy = ComputerPolicy(level=level, apps=[apps[i] for i in dict.fromkeys(app_ids)])
        await asyncio.to_thread(repos.settings_repo.set, key, policy.model_dump_json())
        self.observed.pop((owner, bot), None)
        return await asyncio.to_thread(self.state, repos, owner, bot)

    def pause(self, repos: RepoBundle, owner: int, bot: str, paused: bool) -> ComputerState:
        key = self.key(repos, owner, bot) + ":pause"
        if paused:
            repos.settings_repo.set(key, "1")
        else:
            repos.settings_repo.delete(key)
        self.observed.pop((owner, bot), None)
        return self.state(repos, owner, bot)

    async def run(
        self,
        repos: RepoBundle,
        owner: int,
        bot: str,
        action: Action,
        app_id: str,
        pid: int,
        window_id: int,
        token: str,
        value: str,
        foreground: bool,
    ) -> Any:
        state = await asyncio.to_thread(self.state, repos, owner, bot)
        if action == "handoff":
            await asyncio.to_thread(self.pause, repos, owner, bot, True)
            return {"paused": True}
        if not state.available or state.paused or state.level == "off":
            raise OctopError.localized(ErrorCode.FORBIDDEN)
        grants = {a.id for a in state.apps}
        apps = await self.native.apps()
        if action == "windows":
            result = []
            for process, app in apps.items():
                if app.id in grants:
                    for window in await self.native.windows(process):
                        result.append({**window, "app_id": app.id, "app": app.name})
            return result
        if app_id not in grants or pid not in apps or apps[pid].id != app_id:
            raise OctopError.localized(ErrorCode.FORBIDDEN)
        if not any(w["window_id"] == window_id for w in await self.native.windows(pid)):
            raise OctopError.localized(ErrorCode.NOT_FOUND)
        # Recheck the user's current grant after asynchronous native discovery.
        state = await asyncio.to_thread(self.state, repos, owner, bot)
        if state.paused or state.level == "off" or app_id not in {a.id for a in state.apps}:
            raise OctopError.localized(ErrorCode.FORBIDDEN)
        if app_id in self.active or (foreground and self.foreground):
            raise OctopError.localized(ErrorCode.DESKTOP_SESSION_LIMIT)
        subject = (owner, bot)
        session = "octop-" + hashlib.sha256(repr(subject).encode()).hexdigest()[:24]
        write = action != "read"
        if write:
            if state.level == "view" or (foreground and state.level != "foreground"):
                raise OctopError.localized(ErrorCode.FORBIDDEN)
            observation = self.observed.get(subject)
            if (
                not token
                or observation is None
                or observation[:2] != (pid, window_id)
                or token not in observation[2]
            ):
                raise OctopError.localized(ErrorCode.NOT_FOUND)
        self.active[app_id] = subject
        if write and foreground:
            self.foreground = True
        try:
            if not write:
                tokens: set[str] = set()
                pending = (pid, window_id, tokens)
                self.observed[subject] = pending
                elements = await self.native.read(session, pid, window_id)
                if self.observed.get(subject) is not pending:
                    raise OctopError.localized(ErrorCode.FORBIDDEN)
                tokens.update(e["token"] for e in elements if e["token"])
                return elements
            args = {
                "session": session,
                "pid": pid,
                "window_id": window_id,
                "element_token": token,
                "delivery_mode": "foreground" if foreground else "background",
            }
            if action == "set_value":
                args["value"] = value
            self.observed.pop(subject, None)
            return await self.native.act(action, args)
        finally:
            self.active.pop(app_id, None)
            if write and foreground:
                self.foreground = False
