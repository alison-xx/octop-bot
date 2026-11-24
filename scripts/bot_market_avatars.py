"""Generate Bot market portraits with gpt-image-2.5 on Lynxce.

Usage:
    LYNXCE_API_KEY=... uv run python scripts/bot_market_avatars.py [slug ...] [--force]

Each portrait is the template's soft SVG character (shape + colour) redrawn as a
small 3D figure holding the prop from ``avatar_subject``, saved as a 512px WebP
in ``src/octop/infra/agents/bot_market/avatars/<slug>.webp``. Existing files are
skipped unless ``--force`` is given.
"""

from __future__ import annotations

import base64
import io
import json
import os
import socket
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image

from octop.infra.agents.bot_market.catalog import AVATARS_DIR, Template, load_catalog

API = "https://api.lynxce.cn/api/v1"
_getaddrinfo = socket.getaddrinfo


def _ipv4_only(*args, **kwargs):  # type: ignore[no-untyped-def]
    # Lynxce's CDN hangs over IPv6 from some networks; IPv4 always answers.
    return [a for a in _getaddrinfo(*args, **kwargs) if a[0] == socket.AF_INET]


socket.getaddrinfo = _ipv4_only
MODEL = "gpt-image-2.5"
BODY = {
    "orb": "a round ball-shaped body",
    "heart": "a plump heart-shaped body",
    "sparkle": "a soft four-pointed star-shaped body",
    "drop": "a soft rounded droplet-shaped body",
    "cloud": "a fluffy cloud-shaped body",
    "bean": "a wide rounded bean-shaped body",
}
COLOR = {
    "red": "coral red",
    "orange": "warm orange",
    "green": "fresh mint green",
    "blue": "clear sky blue",
    "violet": "soft violet",
    "yellow": "sunny yellow",
    "cyan": "aqua cyan",
    "magenta": "berry magenta",
    "brown": "caramel brown",
    "gray": "warm grey",
    "rose": "rose pink",
    "sky": "pale sky blue",
    "tangerine": "tangerine",
    "cobalt": "cobalt blue",
    "charcoal": "charcoal",
}


def prompt(t: Template) -> str:
    return (
        f"A single cute mascot character: {BODY[t.look.shape]} in {COLOR.get(t.look.color, t.look.color)}, "
        "smooth matte soft-touch material like a vinyl toy, no mouth, no nose, "
        "two tall slanted black capsule-shaped eyes with a tiny white highlight, "
        "small simple stubby arms. "
        f"The character is {t.avatar_subject}. "
        "Friendly 3D render, soft studio lighting, gentle shadow under the character, "
        "centred and fully in frame with generous margin, facing slightly to the right, "
        "plain very light warm off-white background (#F6F4F0), square composition. "
        "No text, no letters, no numbers on props, no logos, no watermark, no frame."
    )


def _request(method: str, path: str, key: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        API + path,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def generate(t: Template, key: str) -> bytes:
    job = _request(
        "POST",
        "/images/generations",
        key,
        {
            "model": MODEL,
            "prompt": prompt(t),
            "size": "1024x1024",
            "n": 1,
            "response_format": "b64_json",
        },
    )
    for _ in range(90):
        data = job.get("data") or []
        if data and (data[0].get("b64_json") or data[0].get("url")):
            item = data[0]
            if item.get("b64_json"):
                return base64.b64decode(item["b64_json"])
            with urllib.request.urlopen(item["url"], timeout=120) as resp:
                return resp.read()
        if job.get("status") in {"failed", "error"}:
            raise RuntimeError(f"{t.slug}: {job}")
        time.sleep(4)
        job = _request("GET", f"/generations/{job['id']}", key)
    raise TimeoutError(t.slug)


def save(slug: str, raw: bytes) -> None:
    image = Image.open(io.BytesIO(raw)).convert("RGB").resize((512, 512), Image.LANCZOS)
    AVATARS_DIR.mkdir(exist_ok=True)
    image.save(AVATARS_DIR / f"{slug}.webp", "WEBP", quality=86, method=6)


def main() -> None:
    key = os.environ["LYNXCE_API_KEY"]
    force = "--force" in sys.argv
    slugs = {a for a in sys.argv[1:] if not a.startswith("--")}
    todo = [
        t
        for t in load_catalog().templates
        if (not slugs or t.slug in slugs)
        and (force or not (AVATARS_DIR / f"{t.slug}.webp").exists())
    ]

    def run(t: Template) -> str:
        error: Exception | None = None
        for _ in range(2):  # one retry, then report and keep going
            try:
                save(t.slug, generate(t, key))
                return f"ok   {t.slug}"
            except Exception as exc:  # noqa: BLE001
                error = exc
        return f"FAIL {t.slug}: {error}"

    # Two at a time: the image API is shared with production traffic.
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in as_completed([pool.submit(run, t) for t in todo]):
            print(future.result(), flush=True)


if __name__ == "__main__":
    main()
