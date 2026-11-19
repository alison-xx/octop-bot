import hashlib

from octop.config import OctopConfig
from octop.infra.agents import bot_avatar_library as library
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import build_shared_services
from octop.infra.utils.paths import PathLayout


def test_limit_deduplication_and_restart(tmp_path, monkeypatch):
    path = tmp_path / "control.db"
    paths = PathLayout(tmp_path)
    pool = SqlitePool(path)
    run_migrations(pool)
    services = build_shared_services(db=pool, paths=paths, config=OctopConfig())
    uid = services.user_repo.create(username="owner", role="user")
    data = b"GIF89a\x01\x00\x01\x00"
    monkeypatch.setattr(library, "MAX_PHOTOS", 1)
    assert library.store_photo(services, uid, "first", data)[0] == "imported"
    pool.close()

    restored = SqlitePool(path)
    try:
        run_migrations(restored)
        services = build_shared_services(db=restored, paths=paths, config=OctopConfig())
        status, entry = library.store_photo(services, uid, "renamed", data)
        assert (status, entry.name, entry.id) == (
            "duplicate",
            "first",
            hashlib.sha256(data).hexdigest(),
        )
        assert library.store_photo(services, uid, "second", data + b"second")[0] == "full"
        refs = library.list_photo_refs(services, uid)
        assert refs.items == [entry] and refs.total == 1
        assert services.repos.bot_avatar_photo_repo.content(uid, entry.id) == data
    finally:
        restored.close()
