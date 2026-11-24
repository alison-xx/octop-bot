"""Copy the bundled Bot market into the static website.

Usage:
    uv run python scripts/export_bot_market.py

Writes ``website/market/catalog.json`` (both locales) and ``website/market/avatars/``
from ``src/octop/infra/agents/bot_market``, so octop-bot.lynxce.cn/market.html shows
exactly the templates the app imports.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from octop.infra.agents.bot_market.catalog import avatar_path, load_catalog
from octop.infra.connectors.catalog import get_catalog_entry

OUT = Path(__file__).resolve().parents[1] / "website" / "market"


def main() -> None:
    catalog = load_catalog()
    avatars = OUT / "avatars"
    if avatars.exists():
        shutil.rmtree(avatars)
    avatars.mkdir(parents=True)
    templates = []
    for t in catalog.templates:
        data = t.model_dump(exclude={"avatar_subject"})
        source = avatar_path(t.slug)
        data["avatar"] = None
        if source:
            shutil.copyfile(source, avatars / source.name)
            data["avatar"] = f"market/avatars/{source.name}?v={t.version}"
        data["integrations"] = [
            {"kind": kind, "name": {"zh": e.name.zh, "en": e.name.en}, "color": e.color}
            for kind in t.integrations
            if (e := get_catalog_entry(kind)) is not None
        ]
        templates.append(data)
    payload = {
        "categories": [c.model_dump() for c in catalog.categories],
        "roles": [r.model_dump() for r in catalog.roles],
        "templates": templates,
    }
    (OUT / "catalog.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    print(f"{len(templates)} templates → {OUT}")


if __name__ == "__main__":
    main()
