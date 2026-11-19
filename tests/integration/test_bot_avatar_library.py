"""Account boundaries and reusable, independently stored native Bot avatars."""

import asyncio
import base64
import hashlib

from tests.support.auth import create_agent

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAOeUm3cAAAAASUVORK5CYII="
)
GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==")
LIBRARY = "/api/octop-bot/avatar-library"


async def test_batch_import_reuse_owner_isolation_and_deletion(env_admin_alice, monkeypatch):
    client, server, admin, alice = env_admin_alice
    first_bot = await create_agent(client, admin, name="portrait 1")
    second_bot = await create_agent(client, admin, name="portrait 2")
    alice_bot = await create_agent(client, alice, name="another owner")
    digest = hashlib.sha256(PNG).hexdigest()
    png = ("files", ("猫.png", PNG, "image/png"))
    gif = ("files", ("猫.gif", GIF, "image/gif"))
    repo = server.services.repos.bot_avatar_photo_repo
    store = repo.store

    def import_one(owner, digest, name, mime, content, *, capacity):
        if name == "unreadable.gif":
            raise OSError("simulated storage failure for one item")
        return store(owner, digest, name, mime, content, capacity=capacity)

    monkeypatch.setattr(repo, "store", import_one)
    result = await client.post(
        LIBRARY + "/import",
        headers=admin,
        files=[
            png,
            ("files", ("wrong.png", b"not an image", "image/png")),
            ("files", ("unreadable.gif", GIF, "image/gif")),
            gif,
            png,
            ("files", ("large.jpg", b"X" * 120000, "image/jpeg")),
        ],
    )
    result.raise_for_status()
    body = result.json()
    assert [r["name"] for r in body["imported"]] == ["猫.png", "猫.gif"]
    assert body["duplicates"] == [{"id": digest, "name": "猫.png"}]
    assert [r["name"] for r in body["failed"]] == ["wrong.png", "unreadable.gif", "large.jpg"]
    page = (await client.get(LIBRARY, headers=admin, params={"limit": 1})).json()
    assert page["total"] == 2 and page["next"] == 1
    assert page["items"][0]["image"] == "data:image/gif;base64," + base64.b64encode(GIF).decode()
    next_page = (await client.get(LIBRARY, headers=admin, params={"limit": 1, "offset": 1})).json()
    assert next_page["items"][0]["id"] == digest
    assert (await client.get(LIBRARY, headers=alice)).json()["total"] == 0

    def apply(bot, headers):
        return client.put(
            f"/api/octop-bot/bots/{bot}/avatar-photo", headers=headers, json={"photo_id": digest}
        )

    assert (await apply(alice_bot, alice)).status_code == 404
    assert (await apply(alice_bot, admin)).status_code == 404
    assert (await client.delete(LIBRARY + "/" + digest, headers=alice)).status_code == 404
    # Copies use the normal workspace I/O even when the target is stopped.
    await server.app_runtime.agent_registry.stop(second_bot)
    urls = []
    for bot in (first_bot, second_bot):
        res = await apply(bot, admin)
        res.raise_for_status()
        urls.append(res.json()["icon_url"])

    simultaneous = await asyncio.gather(
        *(client.post(LIBRARY + "/import", headers=alice, files=[png]) for _ in range(2))
    )
    assert sorted(len(r.json()["imported"]) for r in simultaneous) == [0, 1]
    assert (await client.delete(LIBRARY + "/" + digest, headers=admin)).status_code == 204
    for url in urls:
        res = await client.get(url, headers=admin)
        assert res.status_code == 200 and res.content == PNG
    assert (await client.get(LIBRARY, headers=alice)).json()["total"] == 1
    assert (await apply(alice_bot, alice)).status_code == 200
    assert (
        await client.post(LIBRARY + "/import", headers=admin, files=[png] * 21)
    ).status_code == 422
