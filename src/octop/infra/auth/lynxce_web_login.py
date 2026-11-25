"""Lynxce browser grants for the hosted Octop Bot workspace."""

import secrets
from typing import Any, Literal
from urllib.parse import urlencode

from pydantic import BaseModel

from octop.infra.auth import lynxce_cloud as cloud
from octop.infra.errors import ErrorCode, OctopError

Provider = Literal["wechat", "workbuddy"]
SITE = "octop-bot-cloud"
CALLBACK = "https://bot.lynxce.cn/login"
WECHAT_RELAY = "https://api.lynxce.cn/api/auth/wechat-web/cloud-relay"


class WebLoginConfig(BaseModel):
    enabled: bool
    url: str = ""
    state: str = ""


class PhoneBinding(BaseModel):
    bind_token: str


async def _call(method: str, path: str, **kwargs: Any) -> Any:
    try:
        return await cloud._send(method, path, **kwargs)
    except cloud._UpstreamFailure as exc:
        if exc.status in (400, 401, 403, 409, 422):
            raise OctopError.localized(ErrorCode.AUTH_FAILED) from None
        raise cloud._rejected(exc.status) from None


async def config(provider: Provider) -> WebLoginConfig:
    prefix = "/api/auth/wechat-web" if provider == "wechat" else "/api/oauth/workbuddy"
    data = await _call("GET", prefix + "/config", params={"site": SITE})
    # Older Lynxce servers resolve an unknown site to the desktop or website app.
    if not isinstance(data, dict) or not (
        data.get("enabled") is True
        and data.get("site") == SITE
        and data.get("callbackUrl") == CALLBACK
    ):
        return WebLoginConfig(enabled=False)
    if provider == "wechat":
        app_id, redirect, qr_state, state = (
            data.get(k) for k in ("appId", "redirectUri", "state", "browserState")
        )
        if not (
            isinstance(app_id, str)
            and app_id
            and redirect == WECHAT_RELAY
            and isinstance(qr_state, str)
            and qr_state
            and isinstance(state, str)
            and state
        ):
            return WebLoginConfig(enabled=False)
        params = urlencode(
            {
                "appid": app_id,
                "redirect_uri": redirect,
                "response_type": "code",
                "scope": "snsapi_login",
                "state": qr_state,
            }
        )
        url = "https://open.weixin.qq.com/connect/qrconnect?" + params + "#wechat_redirect"
    else:
        state = secrets.token_urlsafe(32)
        params = urlencode({"site": SITE, "signupSite": cloud.SIGNUP_SITE, "clientState": state})
        url = cloud._ORIGIN + "/api/oauth/workbuddy/start?" + params
    return WebLoginConfig(enabled=True, url=url, state=state)


async def exchange(provider: Provider, code: str, state: str) -> cloud.CloudSession | PhoneBinding:
    # Dedicated exchange paths fail closed on an older service. Lynxce checks the signed
    # site and state (or WorkBuddy clientState) and consumes the grant exactly once.
    if provider == "wechat":
        data = await _call(
            "POST",
            "/api/auth/wechat-web/cloud-login",
            json={"code": code, "state": state, "site": SITE},
        )
        if isinstance(data, dict) and data.get("needBindPhone") is True:
            return PhoneBinding(bind_token=cloud._token(data, "bindToken"))
    else:
        data = await _call(
            "POST",
            "/api/oauth/workbuddy/cloud-session",
            json={"code": code, "clientState": state, "site": SITE},
        )
    return cloud._grant_from_session(data)


async def bind(token: str, phone: str, code: str) -> cloud.CloudSession:
    data = await _call(
        "POST",
        "/api/auth/wechat-web/cloud-bind-phone",
        json={"site": SITE, "bindToken": token, "phone": phone, "code": code},
    )
    return cloud._grant_from_session(data)
