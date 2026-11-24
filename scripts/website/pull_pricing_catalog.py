"""Refresh the website's fallback copy of Lynxce's public model price list.

The pricing page reads https://api.lynxce.cn/api/models/pricing-catalog in the browser and only
falls back to website/data/pricing-catalog.json when that fails. Run this before a deploy (or
whenever Lynxce changes prices) to keep the fallback close:

    uv run python scripts/website/pull_pricing_catalog.py

Only the fields the page shows are kept. The endpoint is public; no key is sent.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

URL = "https://api.lynxce.cn/api/models/pricing-catalog"
OUT = Path(__file__).resolve().parents[2] / "website" / "data" / "pricing-catalog.json"


def trim(data: dict[str, Any]) -> dict[str, Any]:
    def text(m: dict[str, Any]) -> dict[str, Any]:
        return {
            "modelName": m.get("modelName"),
            "providerLabel": m.get("providerLabel"),
            "supportsImage": bool(m.get("supportsImage")),
            "supportsThinking": bool(m.get("supportsThinking")),
            "creditsPerKInputTokens": m.get("creditsPerKInputTokens"),
            "creditsPerKOutputTokens": m.get("creditsPerKOutputTokens"),
        }

    def media(m: dict[str, Any]) -> dict[str, Any]:
        pricing = m.get("pricing") or {}
        return {
            "displayName": m.get("displayName"),
            "provider": m.get("provider"),
            "pricing": {
                k: pricing.get(k)
                for k in ("creditsPerImage", "videoPricingTiers", "defaultResolution", "unitCredits")
                if k in pricing
            },
        }

    return {
        "textModels": [text(m) for m in data.get("textModels") or []],
        "imageModels": [media(m) for m in data.get("imageModels") or []],
        "videoModels": [media(m) for m in data.get("videoModels") or []],
    }


def main() -> None:
    request = urllib.request.Request(URL, headers={"User-Agent": "octop-bot-website-build"})
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - fixed https URL
        body = json.load(response)
    if body.get("code") != 0 or not isinstance(body.get("data"), dict):
        raise SystemExit(f"unexpected response: code={body.get('code')!r}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"data": trim(body["data"])}, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
