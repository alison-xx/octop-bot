"""Lynxce token-login shape and verified payload rules."""

import jwt
import pytest

from octop.api.routers.auth_lynxce import (
    _is_session_token,
    _session_payload,
    _valid_session_payload,
)


@pytest.mark.parametrize("token", ["sk-api-key", "first.second", "a..c", "a.b.="])
def test_token_login_rejects_non_session_shapes(token: str) -> None:
    assert not _is_session_token(token)


@pytest.mark.parametrize(
    ("claims", "accepted"),
    [
        ({"typ": "refresh"}, False),
        ({"typ": "access", "client": "desktop"}, False),
        ({"typ": "access", "client": "mobile"}, False),
        *[
            ({"typ": "access", key: None}, False)
            for key in ("appId", "appVer", "desktopVer", "mobileVer")
        ],
        ({"typ": "access"}, True),
        ({"typ": "access", "client": "web"}, True),
    ],
)
def test_token_login_verified_claims(claims: dict[str, object], accepted: bool) -> None:
    token = jwt.encode(claims, "secret", algorithm="HS256")
    assert _is_session_token(token)
    assert _valid_session_payload(_session_payload(token), require_src=False) is accepted


def test_token_login_undecodable_payload() -> None:
    assert _is_session_token("a.a.c")
    assert not _valid_session_payload(_session_payload("a.a.c"), require_src=False)


@pytest.mark.parametrize(
    ("claims", "accepted"),
    [({"typ": "access"}, False), ({"typ": "access", "src": "octopbot"}, True)],
)
def test_token_login_required_src(claims: dict[str, str], accepted: bool) -> None:
    assert _valid_session_payload(claims, require_src=True) is accepted
