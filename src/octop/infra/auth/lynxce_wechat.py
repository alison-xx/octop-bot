"""Short-lived desktop WeChat sign-in flows; credentials never leave this process."""

import asyncio
import hmac
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from pydantic import BaseModel

from octop.infra.auth import lynxce_cloud as cloud
from octop.infra.db.services import SharedServices
from octop.infra.errors import ErrorCode, OctopError


class StartResult(BaseModel):
    flow_id: str
    qr_url: str
    redirect_uri: str


class BindRequired(BaseModel):
    need_bind_phone: bool = True
    nickname: str | None = None
    avatar_url: str | None = None


@dataclass
class _Flow:
    user_id: int
    state: str = field(repr=False)
    redirect_uri: str
    expires: float
    attempts: int = 0
    last_attempt: float = float("-inf")
    used: bool = False
    binding: bool = False
    bind_token: str | None = field(default=None, repr=False)


_flows: dict[str, _Flow] = {}


def _error(code: ErrorCode = ErrorCode.LYNXCE_WECHAT_FAILED, status: int = 400) -> OctopError:
    return OctopError.localized(code, status=status)


async def _request(method: str, path: str, body: dict[str, str] | None = None) -> Any:
    # No X-Lynxce-App: Lynxce's config then returns its default callback, which the
    # desktop window intercepts. New accounts still record Octop Bot as their origin.
    headers = {"Accept": "application/json", "X-Lynxce-Client": "web"}
    if body is not None:
        headers["X-Lynxce-Signup-Site"] = cloud.SIGNUP_SITE
    try:
        async with cloud._client() as client:
            response = await client.request(
                method, cloud._ORIGIN + path, headers=headers, json=body
            )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError
        if "data" in result:
            if result.get("code") != 0:
                raise ValueError
            return result["data"]
        return result
    except (httpx.HTTPError, ValueError):
        raise _error() from None


def _get(flow_id: str, user_id: int) -> _Flow:
    flow = _flows.get(flow_id)
    now = time.monotonic()
    if flow is None or flow.user_id != user_id or flow.expires <= now:
        if flow is not None and flow.expires <= now:
            _flows.pop(flow_id, None)
        raise _error(ErrorCode.LYNXCE_WECHAT_FLOW_EXPIRED)
    if flow.attempts >= 5 or now - flow.last_attempt < 1:
        raise _error(status=429)
    flow.attempts += 1
    flow.last_attempt = now
    return flow


async def start(user_id: int) -> StartResult:
    data = await _request("GET", "/api/auth/wechat-web/config")
    if not isinstance(data, dict):
        raise _error()
    if not data.get("enabled"):
        raise _error(ErrorCode.LYNXCE_WECHAT_DISABLED)
    app_id, redirect, state = data.get("appId"), data.get("redirectUri"), data.get("state")
    if not all(isinstance(v, str) and v and len(v) <= 2048 for v in (app_id, redirect, state)):
        raise _error()
    assert isinstance(app_id, str) and isinstance(redirect, str) and isinstance(state, str)
    try:
        parsed = urlsplit(redirect)
    except ValueError:
        raise _error() from None
    if parsed.scheme != "https" or not parsed.hostname or not state.isascii():
        raise _error()
    now = time.monotonic()
    for key, flow in list(_flows.items()):
        if flow.expires <= now:
            del _flows[key]
    owned = [key for key, flow in _flows.items() if flow.user_id == user_id]
    while len(owned) >= 3:
        del _flows[owned.pop(0)]
    flow_id = secrets.token_urlsafe(32)
    _flows[flow_id] = _Flow(user_id, state, redirect, now + 600)
    params = urlencode(
        {
            "appid": app_id,
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": "snsapi_login",
            "state": state,
        }
    )
    return StartResult(
        flow_id=flow_id,
        qr_url=f"https://open.weixin.qq.com/connect/qrconnect?{params}#wechat_redirect",
        redirect_uri=redirect,
    )


async def _save(services: SharedServices, user_id: int, data: Any) -> cloud.CloudAccountStatus:
    try:
        grant = cloud._grant_from_session(data)
    except OctopError:
        raise _error() from None
    async with cloud._lock(services, user_id):
        await cloud._finish(asyncio.to_thread(cloud._save, services, user_id, grant))
    return grant.status()


async def finish(
    services: SharedServices, user_id: int, flow_id: str, code: str, state: str
) -> cloud.CloudAccountStatus | BindRequired:
    flow = _get(flow_id, user_id)
    if flow.used or not state.isascii() or not hmac.compare_digest(flow.state, state):
        raise _error()
    flow.used = True
    data = await _request("POST", "/api/auth/wechat-web/login", {"code": code, "state": state})
    if isinstance(data, dict) and data.get("needBindPhone") is True:
        token = data.get("bindToken")
        if not isinstance(token, str) or not token or len(token) > 32768:
            raise _error()
        flow.bind_token = token
        profile = data.get("profile")
        profile = profile if isinstance(profile, dict) else {}
        return BindRequired(
            nickname=cloud.display_name(profile), avatar_url=cloud._avatar(profile) or None
        )
    _flows.pop(flow_id, None)
    return await _save(services, user_id, data)


async def bind(
    services: SharedServices,
    user_id: int,
    flow_id: str,
    phone: str,
    code: str,
    password: str | None,
) -> cloud.CloudAccountStatus:
    flow = _get(flow_id, user_id)
    if not flow.used or not flow.bind_token or flow.binding:
        raise _error()
    if cloud.code_target(phone)[0] != "phone":
        raise _error()
    body = {"bindToken": flow.bind_token, "phone": phone, "code": code}
    if password is not None:
        body["password"] = password
    flow.binding = True
    try:
        data = await _request("POST", "/api/auth/wechat-web/bind-phone", body)
        result = await _save(services, user_id, data)
        _flows.pop(flow_id, None)
        return result
    finally:
        flow.binding = False
