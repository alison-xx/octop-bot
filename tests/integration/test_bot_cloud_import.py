"""A confirmed import copies only visible text and never replaces a cloud transcript."""

import json
from uuid import UUID

import httpx
import pytest

from octop.infra.auth import lynxce_cloud
from octop.infra.db.repos.thread_messages import ThreadMessageInput
from octop.infra.gateway.threads import ThreadRegistry

API = "/api/octop-bot/cloud"
MODEL = "catalog::personal"


def message(role, content, ts=1710000000, **kwargs):
    return ThreadMessageInput(
        None, role, json.dumps({"data": {"content": content, "additional_kwargs": kwargs}}), ts
    )


class Hosted:
    def __init__(self):
        self.sessions = {}
        self.writes = []
        self.lose_reply = False

    def __call__(self, request):
        def reply(data):
            return httpx.Response(200, json={"code": 0, "data": data})

        path = request.url.path
        payload = json.loads(request.content) if request.content else {}
        if path == "/api/auth/password-login":
            return reply(
                {
                    "user": {"id": payload["account"]},
                    "accessToken": "access",
                    "refreshToken": "refresh",
                }
            )
        assert request.headers["Authorization"] == "Bearer access"
        if path.endswith("/capabilities"):
            return reply({"enabled": True, "supportedModelIds": [MODEL], "defaultModelId": MODEL})
        if path == "/api/user/personal-api-keys":  # desktop sign-in mints its chat key
            return reply({"id": "key-1", "secret": "sk-desktop-test"})
        assert path.startswith("/api/user/web-chat-sessions/")
        if request.method == "GET":
            sid = path.split("/")[-1]
            return reply(self.sessions[sid]) if sid in self.sessions else httpx.Response(404)
        assert path.endswith("/items") and request.method == "POST"
        self.writes.append(payload)
        sid = path.split("/")[-2]
        row = self.sessions.setdefault(sid, {"id": sid, "model": payload["model"], "items": []})
        for item in payload["items"]:
            previous = next(
                (
                    m
                    for m in row["items"]
                    if (m["role"], m["createdAt"]) == (item["role"], item["createdAt"])
                ),
                None,
            )
            if previous is None:
                row["items"].append(item)
            else:
                previous.update(item)
        if self.lose_reply:
            self.lose_reply = False
            raise httpx.ReadTimeout("lost after commit", request=request)
        return reply({"id": sid, "appended": len(payload["items"])})


@pytest.fixture
def cloud(monkeypatch):
    monkeypatch.setenv("OCTOP_DESKTOP_SHELL", "1")
    monkeypatch.setenv("OCTOP_DESKTOP_PRODUCT", "bot")
    hosted = Hosted()
    monkeypatch.setattr(
        lynxce_cloud, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(hosted))
    )
    return hosted


def source(
    server,
    *,
    kind="expert",
    private=False,
    shared=False,
    tid="plain",
    channel="dashboard",
    session_key=None,
):
    services = server.services
    owner = server.user_manager.get("admin").id
    bot = services.agent_repo.create(
        agent_id="editor",
        user_id=owner,
        name="编辑",
        description="校对公开资料。",
        system_prompt="PRIVATE_SYSTEM",
        kind=kind,
        config_json=json.dumps({"octop_bot": {"private": private}}),
    )
    if shared:
        services.agent_repo.set_shared(bot, True)
    services.thread_repo.insert(
        thread_id=tid,
        agent_id=bot,
        user_id=owner,
        channel_type=channel,
        session_key=session_key or ThreadRegistry.dashboard_key(agent_id=bot, user_id=owner),
        title="采访草稿",
    )
    return API + "/import/" + bot + "/" + tid


async def login(client, auth, account="owner"):
    (
        await client.post(
            API + "/account", headers=auth, json={"account": account, "password": "only-for-test"}
        )
    ).raise_for_status()


async def test_cloud_preview_and_confirm_only_visible_text(env_admin_alice, cloud):
    client, server, owner, other = env_admin_alice
    url = source(server)
    repo = server.services.thread_message_repo
    repo.replace_all(
        "plain",
        [
            message("system", "PRIVATE_SYSTEM"),
            message("tool", "TOOL_RESULT"),
            message(
                "human",
                [
                    {
                        "type": "text",
                        "text": "采访大纲\n\n[附件] draft.doc\n工作区路径：SECRET\n\n[附件正文：draft.doc]\n\nDOC_CONTENT",
                    },
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,SECRET"}},
                ],
                octop_inbound_attachments=[{"path": "SECRET"}],
            ),
            message("human", "unrelated", octop_author_user_id=9999),
            message("human", "summary with tools", lc_source="summarization"),
            message("ai", "internal failure", octop_stream_error=True),
            message("ai", "secret transcript", hidden=True),
            message(
                "ai",
                [
                    {"type": "thinking", "thinking": "SECRET"},
                    {"type": "text", "text": "<think>SECRET</think>公开答复"},
                    {"type": "tool_use", "input": {"key": "SECRET"}},
                ],
            ),
            message("human", '再看看\n{"type":"image_url","workspace_path":"inbound/photo.png"}'),
            message("ai", "附上[报告](/api/private/file)"),
        ],
    )
    assert (await client.get(url, headers=other)).status_code == 404
    preview = (await client.get(url, headers=owner)).json()
    assert preview["title"] == "采访草稿"
    assert [(m["role"], m["content"]) for m in preview["items"]] == [
        ("user", "采访大纲"),
        ("assistant", "公开答复"),
        ("user", "再看看"),
        ("assistant", "附上报告"),
    ]
    submit = {"model": MODEL, "account_id": "owner", "revision": preview["revision"]}
    assert (await client.post(url, headers=owner, json=submit)).status_code == 403
    await login(client, owner)
    assert (
        await client.post(url, headers=owner, json={**submit, "account_id": "other"})
    ).status_code == 403
    assert (
        await client.post(url, headers=owner, json={**submit, "model": "unknown"})
    ).status_code == 422
    cloud.lose_reply = True
    assert (await client.post(url, headers=owner, json=submit)).status_code == 502
    imported = await client.post(url, headers=owner, json=submit)
    imported.raise_for_status()
    sid = imported.json()["session_id"]
    assert UUID(sid.removeprefix("octop-bot-v1-")).version == 5
    row = cloud.sessions[sid]
    assert len(cloud.writes) == 1
    sent = row["items"]
    assert len(sent) == 4
    assert "校对公开资料" in sent[2]["content"]
    assert not any(
        s in str(sent)
        for s in ["PRIVATE_SYSTEM", "SECRET", "TOOL_RESULT", "DOC_CONTENT", "/api/private"]
    )
    assert len({m["createdAt"] for m in sent}) == 4
    foreign = {
        "role": "assistant",
        "createdAt": "2026-08-01T04:34:12.000Z",
        "content": "Cloud follow-up",
    }
    sent.append(foreign)
    sent[0]["content"] = "edited in cloud"
    repo.append_if_ready("plain", [message("human", "新的本地问题")])
    assert (await client.post(url, headers=owner, json=submit)).status_code == 409
    fresh = (await client.get(url, headers=owner)).json()
    imported = await client.post(url, headers=owner, json={**submit, "revision": fresh["revision"]})
    assert imported.json() == {"session_id": sid}
    assert len(cloud.writes) == 2 and len(cloud.writes[-1]["items"]) == 1
    assert foreign in row["items"] and sent[0]["content"] == "edited in cloud"


async def test_rolling_preview_and_ordered_dates_are_stable(env_admin_alice, cloud):
    client, server, auth, _ = env_admin_alice
    url = source(server)
    repo = server.services.thread_message_repo
    await login(client, auth)
    repo.replace_all("plain", [])
    preview = (await client.get(url, headers=auth)).json()
    assert preview["items"] == []

    async def send(view):
        return await client.post(
            url,
            headers=auth,
            json={"model": MODEL, "account_id": "owner", "revision": view["revision"]},
        )

    assert (await send(preview)).status_code == 422
    repo.append_if_ready("plain", [message("human", str(i), 0) for i in range(60)])
    first = (await client.get(url, headers=auth)).json()
    assert [m["content"] for m in first["items"]] == [str(i) for i in range(40, 60)]
    (await send(first)).raise_for_status()
    repo.append_if_ready("plain", [message("human", "60", 0)])
    second = (await client.get(url, headers=auth)).json()
    (await send(second)).raise_for_status()
    assert [len(p["items"]) for p in cloud.writes] == [20, 1]
    all_dates = [i["createdAt"] for p in cloud.writes for i in p["items"]]
    assert all_dates == sorted(set(all_dates))
    repo.append_if_ready("plain", [message("ai", "💬" * 6200) for _ in range(5)])
    cropped = (await client.get(url, headers=auth)).json()
    assert len(cropped["items"]) == 4 and all(
        m["content"] == "💬" * 5999 + "…" for m in cropped["items"]
    )
    (await send(cropped)).raise_for_status()
    assert [m["content"] for m in cloud.writes[-1]["items"]] == [
        m["content"] for m in cropped["items"]
    ]


@pytest.mark.parametrize(
    "args",
    [
        {"kind": "team"},
        {"private": True},
        {"shared": True},
        {"channel": "telegram"},
        {"channel": "octop_bot_group"},
        {"tid": "room~editor"},
        {"session_key": "editor:dashboard:1:peer:room"},
        {"session_key": "editor:dashboard:1:team:room"},
    ],
)
async def test_ineligible_chat_is_unavailable(env_admin_alice, cloud, args):
    client, server, auth, _ = env_admin_alice
    url = source(server, **args)
    assert (await client.get(url, headers=auth)).status_code == 404
    response = await client.post(
        url, headers=auth, json={"account_id": "owner", "revision": "a" * 64, "model": MODEL}
    )
    assert response.status_code == 404
    assert not cloud.writes


async def test_publicly_shared_and_contributed_threads_stay_local(env_admin_alice, cloud):
    client, server, auth, _ = env_admin_alice
    url = source(server)
    services = server.services
    services.thread_share_repo.ensure(
        thread_id="plain", agent_id="editor", created_by=server.user_manager.get("admin").id
    )
    assert (await client.get(url, headers=auth)).status_code == 404
    services.thread_share_repo.revoke("plain")
    services.thread_repo.set_contributed("plain", True)
    assert (await client.get(url, headers=auth)).status_code == 404


async def test_pending_legacy_history_is_queued_only_for_the_owner(
    env_admin_alice, cloud, monkeypatch
):
    client, server, owner, other = env_admin_alice
    url = source(server)
    server.services.thread_message_repo.mark_projection("plain", "pending")
    queued = []
    monkeypatch.setattr(
        "octop.api.routers.bot_cloud_import._queue_projection",
        lambda srv, bot, tid, user: queued.append((bot, tid)),
    )
    assert (await client.get(url, headers=other)).status_code == 404
    assert not queued
    response = await client.get(url, headers=owner)
    assert response.status_code == 409 and queued == [("editor", "plain")]
    server.services.thread_message_repo.replace_all(
        "plain",
        [
            ThreadMessageInput(None, "human", "invalid legacy row", 0),
            ThreadMessageInput(None, "human", '{"role":"user","content":"Recovered caption"}', 0),
            message("ai", [{"type": "text", "hidden": True, "text": "internal"}]),
        ],
    )
    assert (await client.get(url, headers=owner)).json()["items"] == [
        {"role": "user", "content": "Recovered caption"}
    ]


async def test_privacy_changed_while_cloud_was_loading_is_respected(
    env_admin_alice, cloud, monkeypatch
):
    client, server, owner, _ = env_admin_alice
    url = source(server)
    server.services.thread_message_repo.replace_all(
        "plain", [message("human", "do not upload after sharing")]
    )
    view = (await client.get(url, headers=owner)).json()
    await login(client, owner)

    def became_shared(request):
        if request.url.path.endswith("/capabilities"):
            server.services.agent_repo.set_shared("editor", True)
        return cloud(request)

    monkeypatch.setattr(
        lynxce_cloud,
        "_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(became_shared)),
    )
    result = await client.post(
        url,
        headers=owner,
        json={"account_id": "owner", "revision": view["revision"], "model": MODEL},
    )
    assert result.status_code == 404 and not cloud.writes
