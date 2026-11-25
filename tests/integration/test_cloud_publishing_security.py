"""Cloud publishing and installation policy through the public routes."""

from __future__ import annotations

from typing import Any

from tests.support.auth import create_user


async def test_cloud_publishing_and_tenant_authored_imports(
    env_with_main_agent: Any, monkeypatch: Any
) -> None:
    client, _server, admin, admin_agent = env_with_main_agent
    monkeypatch.setenv("OCTOP_BOT_CLOUD", "0")
    tenant = await create_user(client, admin, username="publisher")
    source = await client.post(
        "/api/agents/from-expert/default", headers=tenant, json={"name": "Tenant source"}
    )
    assert source.status_code == 201, source.text
    tenant_agent = source.json()["agent_id"]
    expert_path = f"/api/agents/{tenant_agent}/publish-expert"
    payload = {"name": "Tenant expert", "description": "Example"}
    published = await client.post(expert_path, headers=tenant, json=payload)
    assert published.status_code == 201, published.text
    expert_id = published.json()["id"]
    package = await client.post(
        "/api/skill-packages", headers=tenant, json={"name": "Tenant package", "shared": True}
    )
    assert package.status_code == 200, package.text
    package_id = package.json()["id"]

    monkeypatch.setenv("OCTOP_BOT_CLOUD", "1")
    refresh = await client.post(expert_path, headers=tenant, json=payload)
    assert refresh.status_code == 403, refresh.text
    shared = await client.post(
        "/api/skill-packages", headers=tenant, json={"name": "Denied package", "shared": True}
    )
    assert shared.status_code == 403, shared.text
    private = await client.post(
        "/api/skill-packages", headers=tenant, json={"name": "Private package"}
    )
    assert private.status_code == 200, private.text
    update = await client.patch(
        f"/api/skill-packages/{private.json()['id']}", headers=tenant, json={"shared": True}
    )
    assert update.status_code == 403, update.text
    admin_expert = await client.post(
        f"/api/agents/{admin_agent}/publish-expert",
        headers=admin,
        json={"name": "Admin expert", "description": "Example"},
    )
    assert admin_expert.status_code == 201, admin_expert.text
    admin_package = await client.post(
        "/api/skill-packages", headers=admin, json={"name": "Admin package", "shared": True}
    )
    assert admin_package.status_code == 200, admin_package.text
    install = await client.post(
        f"/api/experts/published/{expert_id}/install", headers=admin, json={"name": "Imported"}
    )
    assert install.status_code == 403, install.text
    mount = await client.put(
        f"/api/agents/{admin_agent}/skill-packages",
        headers=admin,
        json={"package_ids": [package_id]},
    )
    assert mount.status_code == 403, mount.text
    copy = await client.post(
        f"/api/agents/{admin_agent}/skill-packages/{package_id}/copy",
        headers=admin,
        json={"skill_slugs": []},
    )
    assert copy.status_code == 403, copy.text

    monkeypatch.setenv("OCTOP_BOT_CLOUD", "0")
    shared = await client.patch(
        f"/api/skill-packages/{private.json()['id']}", headers=tenant, json={"shared": True}
    )
    assert shared.status_code == 200, shared.text
    install = await client.post(
        f"/api/experts/published/{expert_id}/install",
        headers=admin,
        json={"name": "Imported off cloud"},
    )
    assert install.status_code == 201, install.text
