"""Self-contained browser receipt for the native OAuth flow."""

from html import escape
from typing import Literal

from aiohttp import web

from octop.i18n import tr
from octop.infra.utils.locale import resolve_locale


def reply(
    request: web.Request,
    user_locale: str | None,
    outcome: Literal["connected", "denied", "failed"],
    status: int = 200,
) -> web.Response:
    locale = resolve_locale(
        user_locale=user_locale, explicit=request.headers.get("Accept-Language", "").split(",")[0]
    )
    title = escape(tr(f"octop_bot.lynxce.callback_{outcome}", locale))
    note = escape(
        tr(
            "octop_bot.lynxce.callback_return"
            if outcome == "connected"
            else "octop_bot.lynxce.callback_retry",
            locale,
        )
    )
    html = f'''<!doctype html>
<html lang="{locale}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · Octop Bot</title><style>
:root {{ color-scheme:light dark; --paper:#fbfaf8; --ink:#292a2c; --quiet:#656569; --line:#dfddda; }}
@media(prefers-color-scheme:dark) {{ :root {{ --paper:#1d1d1e; --ink:#f3f2ef; --quiet:#b4b1ad; --line:#41403e }} }}
* {{ box-sizing:border-box }} body {{ margin:0; background:var(--paper); color:var(--ink);
font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:34rem; margin:clamp(4rem,19vh,11rem) auto 0; padding:0 1.5rem; }}
header {{ display:flex; align-items:center; gap:.6rem; font-weight:650; padding-bottom:1rem; border-bottom:1px solid var(--line); }}
header::before {{ content:""; width:.75rem; height:.75rem; border-radius:50%; background:#df795f; }}
h1 {{ font-size:clamp(1.7rem,6vw,2.35rem); line-height:1.25; margin:1.6rem 0 .6rem; }} p {{ color:var(--quiet); margin:0; }}
</style></head><body><main><header>Octop Bot</header><h1>{title}</h1><p>{note}</p></main></body></html>'''
    return web.Response(
        text=html,
        content_type="text/html",
        status=status,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'",
        },
    )
