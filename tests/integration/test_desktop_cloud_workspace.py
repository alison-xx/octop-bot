"""Exercise the desktop sidecar's app, registry, mounted tools and real harness workspace."""

from unittest.mock import AsyncMock

import httpx
import pytest

from octop.infra.agents.middleware.bot_workspace import BotWorkspaceTools
from octop.infra.auth import lynxce_cloud
from octop.infra.cloud.computers import remote, remote_tools
from octop.infra.errors import ErrorCode, OctopError
from tests.support.app import octop_client
from tests.support.auth import auth_header, bootstrap_admin, create_agent, seed_openai_provider


async def test_desktop_switch_and_workspace_upload(tmp_octop_home, monkeypatch):
    monkeypatch.setenv("OCTOP_DESKTOP_SHELL", "1")
    monkeypatch.setenv("OCTOP_DESKTOP_PRODUCT", "bot")
    stored = {}

    def cloud(request):
        path = request.url.path
        if path.endswith("/token-login"):
            return httpx.Response(200, json={"access_token": "test-jwt", "expires_in": 3600})
        if "/remote-bots/" in path:
            return httpx.Response(
                200, json={"agent_id": "test-shadow", "origin": path.split("/")[-1]}
            )
        assert path.startswith("/api/octop-bot/computers/test-shadow")
        if path.endswith("/files"):
            key = request.url.params["path"]
            if request.method == "PUT":
                stored[key] = request.content
                return httpx.Response(200, json={"path": key, "size": len(request.content)})
            return httpx.Response(200, content=stored[key])
        return httpx.Response(200, json={"state": "none", "spec": "standard", "takeover": False})

    monkeypatch.setattr(
        remote,
        "cloud_client",
        lambda: httpx.AsyncClient(
            base_url="https://cloud.test", transport=httpx.MockTransport(cloud)
        ),
    )
    monkeypatch.setattr(remote_tools, "ask", lambda **kwargs: (True, "test-approved"))
    async with octop_client(tmp_octop_home, patch_llm=False) as (api, server):
        await bootstrap_admin(api, tmp_octop_home)
        auth = await auth_header(api)
        await seed_openai_provider(api, auth)
        bot = await create_agent(api, auth)
        registry = server.app_runtime.agent_registry
        row = registry.get_row(bot)
        assert row.user_id
        lynxce_cloud._save(
            server.services,
            row.user_id,
            lynxce_cloud._Grant("test-identity", None, "test-bind", "test-access", "test-refresh"),
        )
        root = "/api/octop-bot"
        assert (await api.get(root + "/server-info", headers=auth)).json()["capabilities"][
            "cloud_computer"
        ]
        assert not (await api.get(root + "/server-info")).json()["capabilities"]["cloud_computer"]
        result = await api.put(
            f"{root}/bots/{bot}/computer-target", headers=auth, json={"target": "cloud"}
        )
        assert result.status_code == 200, result.text
        cards = (await api.get(root + "/workspace", headers=auth)).json()["bots"]
        assert next(card for card in cards if card["agent_id"] == bot)["computer"] == "cloud"
        agent = registry.get_agent(bot)
        kit = next(m for m in agent.config.middleware if isinstance(m, BotWorkspaceTools))
        tools = {tool.name: tool for tool in kit.tools}
        assert {"cloud_computer", "request_takeover", "cloud_computer_workspace"} <= tools.keys()
        assert "octop_computer" not in tools
        tool = tools["cloud_computer_workspace"]
        workspace = agent.workspace
        await workspace.aupload_bytes("sample.txt", b"desktop sample")
        args = {"action": "upload", "local_path": "sample.txt", "cloud_path": "sample.txt"}
        if not hasattr(workspace, "adownload_bytes_capped"):
            with pytest.raises(OctopError) as absent:
                await tool.ainvoke(args)
            assert absent.value.code == ErrorCode.BOT_WORKSPACE_BOUNDED_READ_REQUIRED
        else:
            await tool.ainvoke(args)
            assert stored == {"sample.txt": b"desktop sample"}
            await tool.ainvoke({**args, "action": "download", "local_path": "copy.txt"})
            assert await workspace.adownload_bytes_capped("copy.txt") == b"desktop sample"
            with pytest.raises(OctopError) as missing:
                await tool.ainvoke({**args, "local_path": "missing.txt"})
            assert missing.value.code == ErrorCode.NOT_FOUND
            await workspace.aupload_bytes("large.bin", bytes(50 * 1024 * 1024 + 1))
            with pytest.raises(OctopError) as too_large:
                await tool.ainvoke({**args, "local_path": "large.bin"})
            assert too_large.value.status == 413
            assert stored == {"sample.txt": b"desktop sample"}
        # A rejected refresh can remove the grant without an explicit sign-out.
        # The very next ordinary invocation must rebuild its computer tools.
        old_grant = lynxce_cloud._load(server.services, row.user_id)
        monkeypatch.setattr(
            lynxce_cloud, "_send", AsyncMock(side_effect=lynxce_cloud._UpstreamFailure(403))
        )
        with pytest.raises(OctopError):
            await lynxce_cloud._refresh(server.services, row.user_id, old_grant)
        async with registry._track_invocation(bot):
            refreshed = registry.get_agent(bot)
            kit = next(m for m in refreshed.config.middleware if isinstance(m, BotWorkspaceTools))
            names = {entry.name for entry in kit.tools}
            assert "octop_computer" in names
            assert "cloud_computer" not in names and "cloud_computer_workspace" not in names
        lynxce_cloud._save(server.services, row.user_id, old_grant)
        async with registry._track_invocation(bot):
            kit = next(
                m
                for m in registry.get_agent(bot).config.middleware
                if isinstance(m, BotWorkspaceTools)
            )
            assert "cloud_computer_workspace" in {entry.name for entry in kit.tools}
        assert (
            await api.put(
                f"{root}/bots/{bot}/computer-target", headers=auth, json={"target": "local"}
            )
        ).is_success
        assert (await api.get(f"{root}/computers/{bot}", headers=auth)).status_code == 404
