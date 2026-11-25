"""Local Lynxce mock: python3 scripts/website/mock_lynxce.py [--port 18850].

Serve website separately with `python3 -m http.server 8000 --directory website`.
Use http://127.0.0.1:18850 as apiBase in a temporary auth.json. The code is
123456. Order IDs paid, pending and cancelled choose the result status.
This mock only accepts origins on 127.0.0.1 and must not be exposed publicly.
"""

import argparse
import json
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

INVOICES = []
REMOVED_DEVICES = set()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def respond(self, data, status=200):
        origin = self.headers.get("Origin", "")
        parsed = urlsplit(origin)
        self.send_response(status)
        if parsed.scheme == "http" and parsed.hostname == "127.0.0.1":
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Authorization, Content-Type, X-Lynxce-App, X-Lynxce-Signup-Site, X-Lynxce-Client",
        )
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_OPTIONS(self):
        self.respond({})

    def do_GET(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        today = date.today()
        orders = [
            {
                "id": f"order-{i}",
                "outTradeNo": f"MOCK-{i}",
                "orderType": "recharge",
                "status": "paid",
                "amountYuan": i * 50,
                "createdAt": today.isoformat(),
            }
            for i in range(1, 4)
        ]
        if path == "/api/user/profile":
            data = {
                "displayName": "Mock User",
                "avatarUrl": "",
                "email": "mock@example.com",
                "emailBound": True,
            }
        elif path == "/api/user/quota":
            data = {"creditsRemaining": 1234}
        elif path == "/api/user/usage-overview":
            data = {"balance": {"creditsUsedThisMonth": 641}}
        elif path == "/api/user/usage-trend":
            days = [today - timedelta(days=i) for i in reversed(range(365))]
            data = {
                "days": [d.isoformat() for d in days],
                "credits": [0 if i % 4 == 0 else (i * 17) % 150 for i in range(365)],
            }
        elif path == "/api/user/usage-ledger":
            page = max(1, int(query.get("page", ["1"])[0]))
            start = query.get("from", [today.replace(day=1).isoformat()])[0]
            kinds = [
                ("model", None),
                ("media", "image"),
                ("media", "video"),
                ("computer", None),
                ("disk", None),
            ]
            rows = []
            for i in range(20):
                kind, media = kinds[(i + page) % len(kinds)]
                rows.append(
                    {
                        "id": f"usage-{page}-{i}",
                        "createdAt": start + "T12:00:00Z",
                        "subjectType": kind,
                        "metadata": {"type": media},
                        "model": "mock-model",
                        "creditsUsed": i + 1,
                    }
                )
            data = {
                "items": rows,
                "pagination": {"page": page, "pageSize": 20, "total": 60, "totalPages": 3},
            }
        elif path == "/api/user/purchase-orders":
            data = {
                "items": orders,
                "pagination": {"page": 1, "totalPages": 1, "total": len(orders)},
            }
        elif path == "/api/user/invoice-requests/orders":
            data = {
                "items": [
                    {
                        "orderId": o["id"],
                        "outTradeNo": o["outTradeNo"],
                        "amountYuan": o["amountYuan"],
                        "canApply": not any(invoice["orderId"] == o["id"] for invoice in INVOICES),
                    }
                    for o in orders
                ]
            }
        elif path == "/api/user/invoice-requests":
            data = {"items": INVOICES}
        elif path == "/api/user/login-devices":
            data = {
                "devices": [
                    {
                        "id": "desktop:one",
                        "deviceName": "MacBook",
                        "platform": "macos",
                        "lastSeenAt": today.isoformat(),
                    },
                    {
                        "id": "mobile:two",
                        "deviceName": "Phone",
                        "platform": "ios",
                        "lastSeenAt": today.isoformat(),
                    },
                ]
            }
            data["devices"] = [d for d in data["devices"] if d["id"] not in REMOVED_DEVICES]
        elif path.startswith("/api/user/purchase-orders/") and path.endswith("/status"):
            order = path.split("/")[-2]
            data = {"paid": order == "paid", "order": {"status": order, "credits": 500}}
        elif path.endswith("/config"):
            data = {
                "enabled": True,
                "appId": "wxmock",
                "redirectUri": "http://127.0.0.1:18850/relay",
                "state": "mock-state",
            }
        else:
            self.respond({"code": "not_found", "message": "Not found"}, 404)
            return
        self.respond({"code": 0, "data": data})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        path = urlsplit(self.path).path
        if path.endswith("-code"):
            data = {"sent": True}
        elif path == "/api/billing/recharge/checkout-link":
            data = {"url": "https://invalid.example/recharge?token=mock"}
        elif path in {"/api/auth/phone-login", "/api/auth/email-login", "/api/auth/password-login"}:
            if (
                path.endswith("email-login")
                and body.get("email", "").startswith("new")
                and not body.get("password")
            ):
                self.respond(
                    {"code": "signup_password_required", "message": "Password required"}, 400
                )
                return
            if path.endswith("password-login") or body.get("code") == "123456":
                data = {
                    "accessToken": "mock-access",
                    "refreshToken": "mock-refresh",
                    "user": {"name": "Mock User"},
                }
            else:
                self.respond({"code": "invalid_code", "message": "Invalid code"}, 400)
                return
        elif path == "/api/user/invoice-requests":
            data = {
                "id": f"invoice-{len(INVOICES) + 1}",
                **body,
                "amountYuan": 50,
                "status": "pending",
            }
            INVOICES.append(data)
        elif path == "/api/user/logout-all":
            data = {"ok": True}
        elif path == "/api/auth/refresh":
            data = {"accessToken": "mock-refreshed", "refreshToken": "mock-refresh"}
        elif path in {
            "/api/oauth/workbuddy/session",
            "/api/auth/wechat-web/login",
            "/api/auth/wechat-web/bind-phone",
            "/api/auth/login-codes/redeem",
        }:
            data = {
                "accessToken": "mock-access",
                "refreshToken": "mock-refresh",
                "user": {"name": "Mock User"},
            }
        else:
            self.respond({"code": "not_found", "message": "Not found"}, 404)
            return
        self.respond({"code": 0, "data": data})

    def do_DELETE(self):
        if urlsplit(self.path).path.startswith("/api/user/login-devices/"):
            REMOVED_DEVICES.add(unquote(urlsplit(self.path).path.rsplit("/", 1)[-1]))
            self.respond({"code": 0, "data": {"ok": True}})
        else:
            self.respond({"code": "not_found", "message": "Not found"}, 404)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18850)
    args = parser.parse_args()
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
