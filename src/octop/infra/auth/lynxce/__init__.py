"""Connect one local Octop account to Lynxce using a public native OAuth client."""

from __future__ import annotations

import asyncio
import hmac
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from aiohttp import web

from octop.infra.auth.lynxce import _grants, _provider
from octop.infra.auth.lynxce._callback_page import reply
from octop.infra.auth.lynxce._grants import connection_id, get_access_token, is_connected
from octop.infra.connectors.oauth.pkce import new_pkce_pair
from octop.infra.db.services import SharedServices
from octop.infra.errors import ErrorCode, OctopError

__all__ = [
    "cancel_login",
    "connection_id",
    "disconnect",
    "get_access_token",
    "is_connected",
    "poll_login",
    "start_login",
]

LoginState = Literal["pending", "connected", "failed", "cancelled", "expired"]
_CALLBACK_PATH = "/oauth/callback"
_ATTEMPT_SECONDS = 600
_RESULT_SECONDS = 120


@dataclass
class _Attempt:
    root: Path
    user_id: int
    runner: web.AppRunner | None = field(repr=False)
    attempt_id: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    csrf: str = field(default_factory=lambda: secrets.token_urlsafe(32), repr=False)
    state: LoginState = "pending"
    detail: str | None = None
    url: str = field(default="", repr=False)
    exchanging: bool = False
    timer: asyncio.TimerHandle | None = None

    def finish(self, state: LoginState, detail: str | None = None) -> None:
        if self.state != "pending":
            return
        self.state, self.detail = state, detail
        if self.timer is not None:
            self.timer.cancel()
        self.csrf, self.url = "", ""
        # Close after the callback has returned its browser response.
        if self.runner is not None:
            task = asyncio.create_task(self.runner.cleanup())
            _closing.add(task)
            task.add_done_callback(_closing.discard)
            self.runner = None
        asyncio.get_running_loop().call_later(_RESULT_SECONDS, _attempts.pop, self.attempt_id, None)

    def expire(self) -> None:
        if not self.exchanging:
            self.finish("expired")


_attempts: dict[str, _Attempt] = {}
_closing: set[asyncio.Task[None]] = set()


def _owned(services: SharedServices, user_id: int, attempt_id: str) -> _Attempt:
    item = _attempts.get(attempt_id)
    if item is None or item.user_id != user_id or item.root != services.paths.root:
        raise OctopError.localized(ErrorCode.NOT_FOUND)
    return item


def _active(services: SharedServices, user_id: int) -> _Attempt | None:
    return next(
        (
            a
            for a in _attempts.values()
            if a.user_id == user_id and a.root == services.paths.root and a.state == "pending"
        ),
        None,
    )


async def start_login(services: SharedServices, user_id: int) -> tuple[str, str]:
    loop = asyncio.get_running_loop()
    async with _grants.account_lock(services, user_id):
        existing = _active(services, user_id)
        if existing is not None:
            return existing.attempt_id, existing.url
        user = await loop.run_in_executor(None, services.user_repo.get, user_id)
        locale = user.locale if user else None
        verifier, challenge = new_pkce_pair()
        app = web.Application()
        runner = web.AppRunner(app, access_log=None, shutdown_timeout=2)
        attempt = _Attempt(services.paths.root, user_id, runner)

        async def callback(request: web.Request) -> web.Response:
            supplied = request.query.getall("state", [])
            if (
                not attempt.url
                or request.host != host
                or attempt.state != "pending"
                or attempt.exchanging
                or len(supplied) != 1
                or not hmac.compare_digest(supplied[0].encode(), attempt.csrf.encode())
            ):
                return reply(request, locale, "failed", 400)
            codes = request.query.getall("code", [])
            if "error" in request.query:
                reason = (
                    "access_denied"
                    if request.query["error"] == "access_denied"
                    else "token_exchange_failed"
                )
                attempt.finish("failed", reason)
                return reply(
                    request, locale, "denied" if reason == "access_denied" else "failed", 400
                )
            if len(codes) != 1 or not codes[0]:
                return reply(request, locale, "failed", 400)
            attempt.exchanging = True
            try:
                payload = await _provider.token(
                    grant_type="authorization_code",
                    client_id=client_id,
                    redirect_uri=redirect,
                    code=codes[0],
                    code_verifier=verifier,
                )
                grant = _grants.grant_from_tokens(payload, client_id)
                async with _grants.account_lock(services, user_id):
                    current = await loop.run_in_executor(
                        None, _grants.load_registration, services, user_id
                    )
                    if (
                        attempt.state != "pending"
                        or current.get("attempt_id") != attempt.attempt_id
                    ):
                        attempt.finish("cancelled")
                        return reply(request, locale, "failed", 400)
                    await asyncio.get_running_loop().run_in_executor(
                        None, _grants.save, services, user_id, grant
                    )
                    attempt.finish("connected")
                return reply(request, locale, "connected")
            except _provider.ProviderError as exc:
                reason = (
                    "missing_chat_scope"
                    if exc.reason == "missing_chat_scope"
                    else "token_exchange_failed"
                )
                attempt.finish("failed", reason)
            except Exception:
                attempt.finish("failed", "token_exchange_failed")
            return reply(request, locale, "failed", 502)

        app.router.add_get(_CALLBACK_PATH, callback, allow_head=False)
        await runner.setup()
        try:
            registration = await loop.run_in_executor(
                None, _grants.load_registration, services, user_id
            )
            saved_port = registration.get("port", 0)
            try:
                await web.TCPSite(runner, "127.0.0.1", saved_port).start()
            except OSError:
                if not saved_port:
                    raise
                await web.TCPSite(runner, "127.0.0.1", 0).start()
            port = runner.addresses[0][1]
            host = f"127.0.0.1:{port}"
            redirect = f"http://{host}{_CALLBACK_PATH}"
            if port == saved_port:
                client_id = str(registration["client_id"])
            else:
                client_id = await _provider.register(redirect)
            await loop.run_in_executor(
                None,
                _grants.save_registration,
                services,
                user_id,
                port,
                client_id,
                attempt.attempt_id,
            )
            attempt.url = _provider.authorize_url(client_id, redirect, attempt.csrf, challenge)
            _attempts[attempt.attempt_id] = attempt
            attempt.timer = asyncio.get_running_loop().call_later(_ATTEMPT_SECONDS, attempt.expire)
        except (OSError, _provider.ProviderError):
            await runner.cleanup()
            raise OctopError.localized(ErrorCode.NETWORK_ERROR) from None
        except BaseException:
            await runner.cleanup()
            raise
        return attempt.attempt_id, attempt.url


async def poll_login(
    services: SharedServices, user_id: int, attempt_id: str
) -> tuple[LoginState, str | None]:
    item = _owned(services, user_id, attempt_id)
    return item.state, item.detail


async def cancel_login(services: SharedServices, user_id: int, attempt_id: str) -> None:
    async with _grants.account_lock(services, user_id):
        _owned(services, user_id, attempt_id).finish("cancelled")


async def disconnect(services: SharedServices, user_id: int) -> None:
    # The issuer advertises no native revocation endpoint. Forget this
    # installation's grant; upstream account-wide revocation is in its portal.
    async with _grants.account_lock(services, user_id):
        pending = _active(services, user_id)
        if pending is not None:
            pending.finish("cancelled")
        await asyncio.get_running_loop().run_in_executor(None, _grants.forget, services, user_id)
