"""The website's local Lynxce mock: answers only local pages and behaves like the endpoints it fakes."""

from __future__ import annotations

import importlib.util
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "website" / "mock_lynxce.py"


@pytest.fixture
def base() -> Iterator[str]:
    spec = importlib.util.spec_from_file_location("mock_lynxce", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    server = ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def call(
    url: str, body: dict[str, Any] | None = None, origin: str = "http://127.0.0.1:8000"
) -> tuple[int, dict[str, str], dict[str, Any]]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers={"Origin": origin})
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 - local test server
            return response.status, dict(response.headers), json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), json.load(error)


def test_cors_only_for_local_pages(base: str) -> None:
    _, headers, _ = call(base + "/api/oauth/workbuddy/config")
    assert headers.get("Access-Control-Allow-Origin") == "http://127.0.0.1:8000"
    _, headers, _ = call(base + "/api/oauth/workbuddy/config", origin="https://evil.example")
    assert "Access-Control-Allow-Origin" not in headers


def test_code_login(base: str) -> None:
    status, _, body = call(
        base + "/api/auth/phone-login", {"phone": "13800000000", "code": "123456"}
    )
    assert status == 200 and body["data"]["accessToken"]
    status, _, body = call(
        base + "/api/auth/phone-login", {"phone": "13800000000", "code": "000000"}
    )
    assert status == 400 and body["code"] == "invalid_code"


def test_new_email_needs_password(base: str) -> None:
    status, _, body = call(
        base + "/api/auth/email-login", {"email": "new@example.com", "code": "123456"}
    )
    assert status == 400 and body["code"] == "signup_password_required"


@pytest.mark.parametrize("order", ["paid", "pending", "cancelled"])
def test_order_status(base: str, order: str) -> None:
    _, _, body = call(f"{base}/api/user/purchase-orders/{order}/status")
    assert body["data"]["order"]["status"] == order
