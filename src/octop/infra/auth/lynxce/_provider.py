"""Wire protocol for Lynxce's public native OAuth client."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

ISSUER = "https://api.lynxce.cn"
ENDPOINT = ISSUER + "/api/oauth/mcp"
# media: the Bots' image and video generation (agents/providers/lynxce_media.py).
REQUESTED_SCOPE = "chat media recharge"


class ProviderError(Exception):
    """A safe reason; upstream bodies and credentials never escape this boundary."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def _post(endpoint: str, **kwargs: Any) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            response = await client.post(ENDPOINT + endpoint, **kwargs)
            body = response.json()
    except (httpx.HTTPError, ValueError):
        raise ProviderError("provider_unavailable") from None
    if not isinstance(body, dict):
        raise ProviderError("invalid_response")
    if not response.is_success:
        if response.status_code in {400, 401} and body.get("error") in (
            "invalid_client",
            "invalid_grant",
        ):
            raise ProviderError("invalid_grant")
        raise ProviderError("provider_unavailable")
    return body


async def register(redirect: str) -> str:
    result = await _post(
        "/register",
        json={
            "client_name": "Octop Bot",
            "redirect_uris": [redirect],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": REQUESTED_SCOPE,
        },
    )
    client_id = result.get("client_id")
    if not isinstance(client_id, str) or not client_id:
        raise ProviderError("invalid_response")
    return client_id


def authorize_url(client_id: str, redirect: str, state: str, challenge: str) -> str:
    return (
        ENDPOINT
        + "/authorize?"
        + urlencode(
            {
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": redirect,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": REQUESTED_SCOPE,
            }
        )
    )


async def token(**fields: str) -> dict[str, Any]:
    return await _post("/token", data=fields)
