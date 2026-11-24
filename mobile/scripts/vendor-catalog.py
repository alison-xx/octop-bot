#!/usr/bin/env python3
"""Write the model vendor catalog and vendor logos the phone apps use without signing in.

Not signed in, a phone talks to the user's own model vendor directly, so it carries its own copy
of the server's own-key vendor list (`octop.infra.agents.providers.own_keys.vendor_catalog`). Phones
speak only the OpenAI-compatible protocol, so Anthropic-protocol vendors are left out.

Run from the repository root with the server's environment:

    uv run python mobile/scripts/vendor-catalog.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IOS = ROOT / "mobile/ios/OctopBot/Resources"
ANDROID = ROOT / "mobile/android/app/src/main"
LOGOS = ROOT / "dashboard/src/assets/providers"

# "Get a key" pages, by vendor id or company (dashboard/src/assets/providers/index.ts).
DOCS = {
    "tencent": "https://console.cloud.tencent.com/tokenhub",
    "aliyun": "https://bailian.console.aliyun.com/?tab=model#/api-key",
    "volcengine": "https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey",
    "deepseek": "https://platform.deepseek.com/api_keys",
    "zhipu": "https://bigmodel.cn/usercenter/proj-mgmt/apikeys",
    "kimi": "https://platform.moonshot.cn/console/api-keys",
    "minimax": "https://platform.minimaxi.com/user-center/basic-information/interface-key",
    "siliconflow": "https://cloud.siliconflow.cn/account/ak",
    "openai": "https://platform.openai.com/api-keys",
    "gemini": "https://aistudio.google.com/apikey",
    "openrouter": "https://openrouter.ai/settings/keys",
    "groq": "https://console.groq.com/keys",
    "modelscope": "https://modelscope.cn/my/myaccesstoken",
    "mimo": "https://platform.xiaomimimo.com",
    "iflytek": "https://console.xfyun.cn",
    "opencode": "https://opencode.ai/docs/zh-cn/zen/",
}

# Company → logo file in the dashboard. DeepSeek uses the plain mark, as the desktop Bot does.
LOGO_FILES = {
    "tencent": "tencent-coding-plan.png",
    "aliyun": "dashscope.png",
    "volcengine": "volces.svg",
    "zhipu": "zhipu.png",
    "kimi": "moonshot.webp",
    "minimax": "minimax.png",
    "siliconflow": "silicon.png",
    "openai": "openai.png",
    "gemini": "gemini.png",
    "openrouter": "openrouter.png",
    "groq": "groq.png",
    "modelscope": "modelscope.png",
    "mimo": "mimo.svg",
    "iflytek": "iflytek.svg",
    "opencode": "opencode.svg",
    "lynxce": "lynxce.png",
    "ollama": "ollama.png",
}
SIZE = 120


def catalog() -> list[dict[str, object]]:
    from octop.infra.agents.providers.own_keys import vendor_catalog

    rows = []
    for v in vendor_catalog():
        if v["protocol"] != "openai":
            continue
        rows.append(
            {
                "id": v["id"],
                "name": v["name"],
                "vendor": v["vendor"],
                "base_url": v["base_url"],
                "api_key_prefix": v["api_key_prefix"],
                "docs": DOCS.get(str(v["id"])) or DOCS.get(str(v["vendor"])) or "",
                "models": v["models"],
            }
        )
    return rows


# Draws an SVG into a square PNG with AppKit (macOS 14+ reads SVG).
SVG_TO_PNG = """
import AppKit
let a = CommandLine.arguments
let size = Int(a[3])!
let image = NSImage(contentsOf: URL(fileURLWithPath: a[1]))!
let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size, bitsPerSample: 8,
    samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
image.draw(in: NSRect(x: 0, y: 0, width: size, height: size))
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: a[2]))
"""


def png(source: Path, out: Path) -> None:
    """Square PNG of SIZE px: sips for bitmaps, AppKit for SVG."""
    if source.suffix == ".svg":
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "svg.swift"
            script.write_text(SVG_TO_PNG)
            subprocess.run(
                ["swift", str(script), str(source), str(out), str(SIZE)],
                check=True,
                capture_output=True,
            )
    else:
        subprocess.run(
            [
                "sips",
                "-s",
                "format",
                "png",
                "-z",
                str(SIZE),
                str(SIZE),
                str(source),
                "--out",
                str(out),
            ],
            check=True,
            capture_output=True,
        )


def logos() -> None:
    assets = IOS / "Assets.xcassets"
    drawable = ANDROID / "res/drawable-nodpi"
    for company, name in LOGO_FILES.items():
        image = assets / f"vendor-{company}.imageset"
        image.mkdir(parents=True, exist_ok=True)
        png(LOGOS / name, image / f"{company}.png")
        (image / "Contents.json").write_text(
            json.dumps(
                {
                    "images": [{"filename": f"{company}.png", "idiom": "universal"}],
                    "info": {"author": "xcode", "version": 1},
                },
                indent=2,
            )
            + "\n"
        )
        shutil.copy(image / f"{company}.png", drawable / f"vendor_{company}.png")


def main() -> None:
    text = json.dumps(catalog(), ensure_ascii=False, indent=1) + "\n"
    (IOS / "own-key-vendors.json").write_text(text)
    (ANDROID / "assets/own-key-vendors.json").write_text(text)
    if sys.platform == "darwin":
        logos()
    print("wrote own-key-vendors.json and vendor logos into mobile/ios and mobile/android")


if __name__ == "__main__":
    main()
