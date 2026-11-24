"""Every bundled Bot market template is complete and importable."""

from octop.infra.agents.bot_market.catalog import avatar_path, load_catalog
from octop.infra.agents.bot_market.install import memory_file, persona, skill_file
from octop.infra.connectors.catalog import get_catalog_entry


def test_catalog_covers_every_category_with_portraits_and_known_connectors():
    catalog = load_catalog()
    by_category = {
        c.id: [t for t in catalog.templates if t.category == c.id] for c in catalog.categories
    }
    assert all(len(items) >= 3 for items in by_category.values())
    assert 4 <= sum(t.featured for t in catalog.templates) <= 8
    for t in catalog.templates:
        assert avatar_path(t.slug) is not None, t.slug
        assert all(get_catalog_entry(kind) for kind in t.integrations), t.slug
        assert len(t.starters.zh) >= 3, t.slug


def test_rendered_files_follow_the_locale():
    t = load_catalog().get("store-daily-brief")
    assert t is not None
    zh, en = persona(t, "zh"), persona(t, "en")
    assert zh.startswith(t.role.zh) and "## 工作守则" in zh
    assert en.startswith(t.role.en) and "## Working rules" in en
    path, body = skill_file(t, 0, "en")
    assert path == "skills/daily-brief/SKILL.md"
    assert body.decode().startswith('---\nname: daily-brief\ndescription: "Use when')
    assert t.memories.en[1] in memory_file(t, "en").decode()
