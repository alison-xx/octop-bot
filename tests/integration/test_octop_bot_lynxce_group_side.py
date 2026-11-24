"""Group members and side conversations bill the chosen personal account."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from aiohttp import web
from aiohttp.test_utils import TestServer

from octop.infra.agents.providers import lynxce
from octop.infra.auth import lynxce as oauth
from octop.infra.db.repos.thread_messages import ThreadMessageInput


async def test_group_and_side_chat_use_current_personal_bearer_instead_of_shared_provider(
    env_with_agent, monkeypatch
):
    client, server, auth, member = env_with_agent
    monkeypatch.setenv("OCTOP_DESKTOP_SHELL", "1")
    monkeypatch.setenv("OCTOP_DESKTOP_PRODUCT", "bot")
    services = server.services
    owner = services.agent_repo.get(member).user_id
    monkeypatch.setattr(oauth, "connection_id", lambda _, uid: "grant" if uid == owner else None)
    token = AsyncMock(return_value="first-test-access")
    monkeypatch.setattr(oauth, "get_access_token", token)
    seen = []

    async def chat(request):
        body = await request.json()
        seen.append((request.headers["Authorization"], body["model"]))
        common = {"id": "fixture", "created": 1, "model": body["model"]}
        answer = {"role": "assistant", "content": "personal reply"}
        if not body.get("stream"):
            return web.json_response(
                {
                    **common,
                    "object": "chat.completion",
                    "choices": [{"index": 0, "message": answer, "finish_reason": "stop"}],
                }
            )
        chunks = [
            {"index": 0, "delta": answer, "finish_reason": None},
            {"index": 0, "delta": {}, "finish_reason": "stop"},
        ]
        data = "".join(
            "data: "
            + json.dumps({**common, "object": "chat.completion.chunk", "choices": [chunk]})
            + "\n\n"
            for chunk in chunks
        )
        return web.Response(text=data + "data: [DONE]\n\n", content_type="text/event-stream")

    async def catalog(_):
        return web.json_response({"data": [{"id": "tencent/personal-only"}]})

    upstream = web.Application()
    upstream.add_routes([web.get("/models", catalog), web.post("/chat/completions", chat)])
    async with TestServer(upstream) as http:
        monkeypatch.setattr(lynxce, "BASE_URL", str(http.make_url("/")).rstrip("/"))
        await lynxce.select_account_model(services, owner, "tencent/personal-only")
        room = await client.post(
            "/api/octop-bot/groups",
            headers=auth,
            json={
                "name": "Billing test",
                "admin_id": member,
                "member_ids": [member],
            },
        )
        room.raise_for_status()
        group_id = room.json()["group_id"]
        post = await client.post(
            f"/api/octop-bot/groups/{group_id}/messages",
            headers=auth,
            json={
                "text": "test",
                "mention_ids": [member],
                "request_id": "personal-group",
            },
        )
        post.raise_for_status()
        assert any(
            item["role"] == "assistant" and "personal reply" in item["text"] for item in post.json()
        ), post.text
        assert seen and set(seen) == {("Bearer first-test-access", "tencent/personal-only")}
        token.return_value = "refreshed-test-access"
        thread = "personal-side"
        services.thread_repo.insert(
            thread_id=thread,
            agent_id=member,
            user_id=owner,
            channel_type="dashboard",
            session_key=thread,
        )
        services.thread_message_repo.replace_all(
            thread,
            [
                ThreadMessageInput(
                    "previous", "human", json.dumps({"data": {"content": "earlier"}}), 1
                )
            ],
        )
        side = await client.post(
            f"/api/octop-bot/bots/{member}/side",
            headers=auth,
            json={"thread_id": thread, "question": "summary"},
        )
        side.raise_for_status()
        assert side.json()["answer"] == "personal reply"
        assert seen[-1] == ("Bearer refreshed-test-access", "tencent/personal-only")
        monkeypatch.setattr(oauth, "connection_id", lambda *_: None)
        refused = await client.post(
            f"/api/octop-bot/bots/{member}/side",
            headers=auth,
            json={"thread_id": thread, "question": "again"},
        )
        assert refused.status_code == 403
