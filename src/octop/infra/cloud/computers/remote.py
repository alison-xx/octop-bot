"""Desktop credentials for the remote computer service.

The cloud session is bound to the locally stored Lynxce grant, so signing in as a
new account cannot reuse a previous account's computer token.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from pathlib import PureWindowsPath
from typing import Any, Literal

import httpx
from filelock import AsyncFileLock

from octop.infra.agents.bot_workspace import require_own_bot
from octop.infra.agents.settings.profile import parse_config_json
from octop.infra.auth import lynxce_cloud
from octop.infra.crypto.fernet import decrypt_json, encrypt_json
from octop.infra.db.repos.agents import AgentRow
from octop.infra.db.services import SharedServices
from octop.infra.desktop import bot_cloud_origin, bot_desktop_enabled
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.ulid import new_ulid


def _key(user_id: int) -> str:
    return f"octop_bot.remote_computer.user.{user_id}"


def cloud_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=bot_cloud_origin(), timeout=45, trust_env=False)


def clear_token(services: SharedServices, user_id: int) -> None:
    services.secret_repo.delete(_key(user_id))


class RemoteCredentials:
    """Exchange and cache a short-lived cloud token, never the Lynxce refresh token."""

    def __init__(
        self,
        services: SharedServices,
        user_id: int,
        *,
        client: Callable[[], httpx.AsyncClient] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._services = services
        self._user_id = user_id
        self._client = client or cloud_client
        self._clock = clock

    async def token(self, *, force: bool = False, binding: str | None = None) -> str:
        services, user_id = self._services, self._user_id
        key = _key(user_id)
        async with lynxce_cloud._lock(services, user_id):
            grant = await asyncio.to_thread(lynxce_cloud._load, services, user_id)
            if grant is None or (binding is not None and grant.binding != binding):
                raise OctopError.localized(ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED, status=409)
            blob = await asyncio.to_thread(services.secret_repo.get, key)
            if blob and not force:
                cached = decrypt_json(services.secret_repo, key + ".fernet", blob)
                token = cached.get("token")
                expires = cached.get("expires")
                if (
                    cached.get("binding") == grant.binding
                    and isinstance(token, str)
                    and isinstance(expires, (int, float))
                    and expires > self._clock()
                ):
                    return token

            async def exchange(access_token: str, server_code: str | None = None) -> httpx.Response:
                payload = {"access_token": access_token}
                if server_code:
                    payload["server_code"] = server_code
                try:
                    async with self._client() as client:
                        return await client.post("/api/auth/lynxce/token-login", json=payload)
                except httpx.HTTPError:
                    raise OctopError.localized(ErrorCode.NETWORK_ERROR) from None

            response = await exchange(grant.access_token)
            if response.status_code in (401, 403):
                grant = await lynxce_cloud._finish(lynxce_cloud._refresh(services, user_id, grant))
                response = await exchange(grant.access_token)
            if (
                response.status_code == 409
                and lynxce_cloud._error_code(response) == "BOT_CLOUD_SESSION_REQUIRED"
            ):
                # Older Lynxce installations lack the code issuer. Keep interactive
                # verification available during the staged rollout.
                try:
                    issued = await lynxce_cloud._send(
                        "POST",
                        "/api/auth/login-codes",
                        bearer=grant.access_token,
                        json={"scope": "server", "site": "octop-bot"},
                    )
                except lynxce_cloud._UpstreamFailure as exc:
                    if exc.status in {400, 403, 404, 405, 422}:
                        raise OctopError.localized(ErrorCode.BOT_CLOUD_REVERIFY_REQUIRED) from None
                    raise lynxce_cloud._rejected(exc.status) from None
                response = await exchange(grant.access_token, lynxce_cloud._token(issued, "code"))
                if response.status_code == 422 or (
                    response.status_code == 409
                    and lynxce_cloud._error_code(response) == "BOT_CLOUD_SESSION_REQUIRED"
                ):
                    raise OctopError.localized(ErrorCode.BOT_CLOUD_REVERIFY_REQUIRED)
            if response.status_code in (401, 403):
                raise OctopError.localized(ErrorCode.AUTH_FAILED, status=403)
            if not response.is_success:
                raise OctopError.localized(ErrorCode.NETWORK_ERROR)
            try:
                body = response.json()
                token = body["access_token"]
                ttl = body["expires_in"]
                if (
                    not isinstance(token, str)
                    or not token
                    or not token.isascii()
                    or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in token)
                    or type(ttl) is not int
                    or not 1 <= ttl <= 3600
                ):
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                raise OctopError.localized(ErrorCode.NETWORK_ERROR) from None
            payload = {"token": token, "expires": self._clock() + ttl, "binding": grant.binding}
            encrypted = encrypt_json(services.secret_repo, key + ".fernet", payload)
            await lynxce_cloud._finish(asyncio.to_thread(services.secret_repo.put, key, encrypted))
            return token


# Cloud boot/resume may wait for the desktop before the requested operation starts.
STARTUP_TIMEOUT = 360

_AGENT = re.compile(r"[A-Za-z0-9_-]{1,64}")
Target = Literal["local", "cloud"]


def configured_target(row: AgentRow) -> Target:
    config = parse_config_json(row.config_json).get("octop_bot")
    return "cloud" if isinstance(config, dict) and config.get("computer") == "cloud" else "local"


def _owned(services: SharedServices, user_id: int, agent_id: str) -> AgentRow:
    if not bot_desktop_enabled() or not _AGENT.fullmatch(agent_id):
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    row = require_own_bot(services, user_id, agent_id)
    if row.is_shared or row.kind not in ("expert", "managed"):
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    return row


def _failure(response: httpx.Response) -> OctopError:
    # Only forward recognized error codes. Upstream messages can contain submitted data.
    upstream_code = lynxce_cloud._error_code(response)
    if response.status_code == 409 and upstream_code == "BOT_CLOUD_SESSION_REQUIRED":
        return OctopError.localized(ErrorCode.BOT_CLOUD_REVERIFY_REQUIRED)
    if response.status_code == 401:
        # Dashboard's AUTH_FAILED/TOKEN_EXPIRED recovery is for the local login only.
        return OctopError.localized(ErrorCode.BOT_CLOUD_REQUEST_REJECTED, status=401)
    code = ErrorCode.NETWORK_ERROR
    with suppress(ValueError):
        code = ErrorCode(upstream_code or "")
    return OctopError.localized(code, status=response.status_code if response.is_error else 502)


class RemoteComputerManager:
    """Calls are bound to a local owner, a Bot and one generation of the Lynxce login."""

    def __init__(
        self, services: SharedServices, user_id: int, agent_id: str, grant: lynxce_cloud._Grant
    ):
        self.services = services
        self.user_id = user_id
        self.agent_id = agent_id
        self.binding = grant.binding
        self.account = hashlib.sha256(grant.account_id.encode()).hexdigest()
        self.credentials = RemoteCredentials(services, user_id)
        self._shadow_key = f"octop_bot:shadow:{user_id}:{self.agent_id}:{self.account}"

    @classmethod
    def owned(
        cls, services: SharedServices, user_id: int, agent_id: str, *, selecting: bool = False
    ) -> RemoteComputerManager:
        row = _owned(services, user_id, agent_id)
        if not selecting and configured_target(row) != "cloud":
            raise OctopError.localized(ErrorCode.NOT_FOUND)
        grant = lynxce_cloud._load(services, user_id)
        if grant is None:
            raise OctopError.localized(ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED, status=409)
        return cls(services, user_id, row.agent_id, grant)

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        screen_session = kwargs.pop("screen_session", None)
        limit = kwargs.pop("limit", 8 * 1024 * 1024)
        source = kwargs.pop("source", None)
        destination = kwargs.pop("destination", None)

        async def chunks() -> AsyncIterator[bytes]:
            await asyncio.to_thread(source.seek, 0)
            while chunk := await asyncio.to_thread(source.read, 64 * 1024):
                yield chunk

        for force in (False, True):
            if source is not None:
                kwargs["content"] = chunks()
            if screen_session:
                headers["X-Octop-Screen-Session"] = screen_session
            else:
                token = await self.credentials.token(force=force, binding=self.binding)
                headers["Authorization"] = f"Bearer {token}"
            try:
                async with (
                    cloud_client() as client,
                    client.stream(method, path, headers=headers, **kwargs) as stream,
                ):
                    data = bytearray()
                    size = 0
                    async for part in stream.aiter_bytes(chunk_size=64 * 1024):
                        size += len(part)
                        if size > (limit if stream.is_success else 64 * 1024):
                            raise OctopError.localized(
                                ErrorCode.ATTACHMENT_TOO_LARGE,
                                details={"max_mb": limit // (1024 * 1024)},
                                max_mb=limit // (1024 * 1024),
                            )
                        if destination is not None and stream.is_success:
                            await asyncio.to_thread(destination.write, part)
                        else:
                            data.extend(part)
                    response = httpx.Response(stream.status_code, content=bytes(data))
            except (httpx.ReadTimeout, httpx.WriteTimeout):
                if method in {"POST", "PUT", "DELETE"}:
                    raise OctopError.localized(ErrorCode.BOT_COMPUTER_OPERATION_TIMEOUT) from None
                raise OctopError.localized(ErrorCode.NETWORK_ERROR) from None
            except httpx.HTTPError:
                raise OctopError.localized(ErrorCode.NETWORK_ERROR) from None
            if response.is_success:
                return response
            if response.status_code != 401 or force or screen_session:
                raise _failure(response)
        raise AssertionError

    async def shadow(self, *, selecting: bool = False) -> str:
        row = await asyncio.to_thread(_owned, self.services, self.user_id, self.agent_id)
        if not selecting and configured_target(row) != "cloud":
            raise OctopError.localized(ErrorCode.NOT_FOUND)
        settings = self.services.settings_repo
        async with AsyncFileLock(self.services.paths.root / f".shadow-{self.agent_id}.lock"):
            raw = await asyncio.to_thread(settings.get, self._shadow_key)
            cached = json.loads(raw) if raw else {}
            name = row.name[:64]
            if (
                cached.get("account") == self.account
                and cached.get("name") == name
                and cached.get("updated", 0) > time.time() - 86400
            ):
                return str(cached["id"])
            install = await asyncio.to_thread(
                settings.get_or_insert, "octop_bot:install_id", new_ulid()
            )
            origin = f"{install}:{self.agent_id}"
            response = await self._request(
                "PUT", f"/api/octop-bot/remote-bots/{origin}", json={"name": name}
            )
            try:
                result = response.json()
                shadow = result["agent_id"]
                if (
                    result["origin"] != origin
                    or not isinstance(shadow, str)
                    or not _AGENT.fullmatch(shadow)
                ):
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                raise OctopError.localized(ErrorCode.NETWORK_ERROR) from None
            await asyncio.to_thread(
                settings.set,
                self._shadow_key,
                json.dumps(
                    {
                        "id": shadow,
                        "account": self.account,
                        "name": name,
                        "updated": time.time(),
                    }
                ),
            )
            return shadow

    async def computer(self, method: str, action: str = "", **kwargs: Any) -> httpx.Response:
        shadow = await self.shadow()
        if action in ("/run", "/python"):
            key = (str(self.services.paths.root), self.user_id, self.agent_id)
            now = time.monotonic()
            with _guard:
                if now < _next_command.get(key, 0):
                    raise OctopError.localized(ErrorCode.BOT_COMPUTER_BUSY, status=429)
                _next_command[key] = now + 1
        if action in ("/screenshot", "/accessibility", "/files", "/run", "/python", "/takeover"):
            execution_time = kwargs.pop("timeout", 60)
            kwargs["timeout"] = httpx.Timeout(STARTUP_TIMEOUT + execution_time, connect=10)
        return await self._request(method, f"/api/octop-bot/computers/{shadow}{action}", **kwargs)

    def _check(self, agent_id: str, user_id: int) -> None:
        if (self.agent_id, self.user_id) != (agent_id, user_id):
            raise OctopError.localized(ErrorCode.NOT_FOUND)

    def use[T](self, agent_id: str, user_id: int, work: Callable[[RemoteDriver, str], T]) -> T:
        self._check(agent_id, user_id)
        return work(RemoteDriver(self), agent_id)

    def taken_over(self, agent_id: str, user_id: int) -> bool:
        self._check(agent_id, user_id)
        return bool(asyncio.run(self.computer("GET")).json()["takeover"])

    def set_takeover(self, agent_id: str, user_id: int, active: bool) -> None:
        self._check(agent_id, user_id)
        asyncio.run(self.computer("POST", "/takeover", json={"active": active}))

    def claim_screen(self, agent_id: str, holder: str) -> bool:
        from octop.infra.cloud.computers.manager import SCREEN_HOLD_SECONDS

        key = (str(self.services.paths.root), self.user_id, agent_id)
        now = time.monotonic()
        with _guard:
            previous = _holders.get(key)
            if previous and previous[0] != holder and now < previous[1]:
                return False
            _holders[key] = (holder, now + SCREEN_HOLD_SECONDS)
        return True

    def note(self, agent_id: str, kind: str) -> None:
        with _guard:
            _activity[(str(self.services.paths.root), self.user_id, agent_id)] = (kind, time.time())

    def activity(self) -> tuple[str, float] | None:
        with _guard:
            return _activity.get((str(self.services.paths.root), self.user_id, self.agent_id))


_guard = threading.Lock()
type _BotKey = tuple[str, int, str]
_next_command: dict[_BotKey, float] = {}
_holders: dict[_BotKey, tuple[str, float]] = {}
_activity: dict[_BotKey, tuple[str, float]] = {}
MAX_FILE_BYTES = 50 * 1024 * 1024


def transfer_path(path: str) -> str:
    # Keep system-managed workspace trees and both platforms' absolute/parent paths out.
    parts = path.split("/")
    if (
        not path
        or len(path) > 4096
        or path != path.strip()
        or path.startswith("~")
        or PureWindowsPath(path).drive
        or "\\" in path
        or ":" in path
        or any(not p or p.startswith(".") for p in parts)
        or any(ord(c) < 32 for c in path)
    ):
        raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS)
    return path


class RemoteDriver:
    """Synchronous adapter for the existing computer-use tool's worker thread."""

    def __init__(self, manager: RemoteComputerManager):
        self.manager = manager

    def request(self, instance: str, method: str, action: str, **kwargs: Any) -> httpx.Response:
        if instance != self.manager.agent_id:
            raise OctopError.localized(ErrorCode.NOT_FOUND)
        return asyncio.run(self.manager.computer(method, action, **kwargs))

    def screenshot(self, instance: str) -> bytes:
        return self.request(instance, "GET", "/screenshot").content

    def accessibility(self, instance: str) -> str:
        return str(self.request(instance, "GET", "/accessibility").json()["xml"])

    def run_python(self, instance: str, code: str) -> str:
        from octop.infra.cloud.computers.backend import TAKEN_OVER

        result = self.request(instance, "POST", "/python", json={"code": code}, timeout=310).json()
        if result["taken_over"]:
            raise RuntimeError(TAKEN_OVER)
        return str(result["output"])

    def run(self, instance: str, command: str, timeout: int) -> tuple[int, str]:
        result = self.request(
            instance,
            "POST",
            "/run",
            json={"command": command, "timeout": timeout},
            timeout=timeout + 10,
        ).json()
        return int(result["exit_code"]), str(result["output"])

    def read(self, instance: str, path: str) -> bytes:
        return self.request(
            instance, "GET", "/files", params={"path": transfer_path(path)}, limit=MAX_FILE_BYTES
        ).content

    def write(self, instance: str, path: str, data: bytes) -> None:
        if len(data) > MAX_FILE_BYTES:
            raise OctopError.localized(ErrorCode.ATTACHMENT_TOO_LARGE, max_mb=50)
        self.request(instance, "PUT", "/files", params={"path": transfer_path(path)}, content=data)


async def set_target(
    services: SharedServices, registry: Any, user_id: int, agent_id: str, target: Target
) -> Target:
    await asyncio.to_thread(_owned, services, user_id, agent_id)
    binding = None
    if target == "cloud":
        remote = await asyncio.to_thread(
            RemoteComputerManager.owned, services, user_id, agent_id, selecting=True
        )
        binding = remote.binding
        await remote.credentials.token(binding=binding)
        await remote.shadow(selecting=True)

    def persist() -> None:
        if binding is not None:
            grant = lynxce_cloud._load(services, user_id)
            if grant is None or binding != grant.binding:
                raise OctopError.localized(ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED, status=409)
        for _ in range(3):
            row = _owned(services, user_id, agent_id)
            if configured_target(row) == target:
                return
            config = parse_config_json(row.config_json)
            config.setdefault("octop_bot", {})["computer"] = target
            if services.agent_repo.replace_owned_bot_config(
                user_id, agent_id, row.config_json, json.dumps(config)
            ):
                return
        raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS, status=409)

    async with lynxce_cloud._lock(services, user_id):
        await asyncio.to_thread(persist)
    # A previous request may have persisted this selection but failed to reload the agent.
    await registry.reload(agent_id)
    return target


async def clean_deleted_shadows(services: SharedServices, user_id: int) -> None:
    """A missing local Bot's mapping is its retry record, scoped to the original cloud account."""
    if not bot_desktop_enabled():
        return
    grant = await asyncio.to_thread(lynxce_cloud._load, services, user_id)
    if grant is None:
        return
    prefix = f"octop_bot:shadow:{user_id}:"
    settings = services.settings_repo
    records = await asyncio.to_thread(settings.with_prefix, prefix)
    install = await asyncio.to_thread(settings.get, "octop_bot:install_id")
    if not install:
        return
    for key, raw in records.items():
        agent_id = key.removeprefix(prefix).split(":", 1)[0]
        if (
            not _AGENT.fullmatch(agent_id)
            or (await asyncio.to_thread(services.agent_repo.get, agent_id)) is not None
        ):
            continue
        remote = RemoteComputerManager(services, user_id, agent_id, grant)
        if json.loads(raw).get("account") != remote.account:
            continue
        try:
            await remote._request(
                "DELETE", f"/api/octop-bot/remote-bots/{install}:{agent_id}", timeout=5
            )
        except OctopError as exc:
            if exc.status != 404:
                continue
        await asyncio.to_thread(settings.delete, key)


async def pause_shadows(
    services: SharedServices, user_id: int, account_id: str, token: str
) -> None:
    """Called under the login lock. Use its current token without recursively exchanging it."""
    records = await asyncio.to_thread(
        services.settings_repo.with_prefix, f"octop_bot:shadow:{user_id}:"
    )
    account = hashlib.sha256(account_id.encode()).hexdigest()
    async with cloud_client() as client:
        for raw in records.values():
            data = json.loads(raw)
            if data.get("account") == account and _AGENT.fullmatch(data["id"]):
                try:
                    await client.post(
                        f"/api/octop-bot/computers/{data['id']}/pause",
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=3,
                    )
                except httpx.HTTPError:
                    continue


async def reverify(
    services: SharedServices,
    user_id: int,
    action: Literal["code", "login", "code-login"],
    body: dict[str, Any],
) -> dict[str, Any]:
    grant = await asyncio.to_thread(lynxce_cloud._load, services, user_id)
    if grant is None:
        raise OctopError.localized(ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED, status=409)
    try:
        async with cloud_client() as client:
            response = await client.post(f"/api/auth/lynxce/{action}", json=body)
    except httpx.HTTPError:
        raise OctopError.localized(ErrorCode.NETWORK_ERROR) from None
    if not response.is_success:
        raise _failure(response)
    if action == "code":
        return {"channel": response.json()["channel"]}
    # Discard the full cloud login response. Confirm the original local identity can now
    # exchange its own grant, even if the user typed credentials for a different account.
    await RemoteCredentials(services, user_id).token(force=True, binding=grant.binding)
    return {}
