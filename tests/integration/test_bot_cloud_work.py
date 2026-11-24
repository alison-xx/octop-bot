"""Two independent Octop identities reach only their connected account's hosted conversations."""

import json
from collections import defaultdict
from uuid import uuid4

import httpx
import pytest

from octop.infra.auth import lynxce_cloud
from octop.infra.cloud.bot_work import role_instruction

API = "/api/octop-bot/cloud"
NOW = "2026-11-20T08:00:00.000Z"
MODEL = "catalog::cloud-model"


def success(data):
    return httpx.Response(200, json={"code": 0, "data": data})


class CloudAccount:
    def __init__(self):
        self.tasks = {}
        self.sessions = {}
        self.schedules = {}

    def append(self, sid, title, role, content, task=None):
        row = self.sessions.setdefault(
            sid, {"id": sid, "title": title[:80], "updatedAt": NOW, "model": MODEL, "items": []}
        )
        row["items"].append(
            {
                "role": role,
                "content": content,
                "createdAt": NOW,
                **({"cloudWorkTaskId": task} if task else {}),
            }
        )

    def finish(self, task, result):
        row = self.tasks[task]
        row.update(status="completed", result=result)
        self.append(row["sessionId"], row["instruction"], "assistant", result, task)

    def schedule_run(self, schedule):
        row = self.schedules[schedule]
        row.update(
            lastResultPreview="Hosted digest", lastRunAt=NOW, lastStatus="succeeded", runCount=1
        )
        self.append(row["sessionId"], row["name"], "user", "【定时任务】\n" + row["instruction"])
        self.append(row["sessionId"], row["name"], "assistant", "Hosted digest")


class HostedAPI:
    """Only the production user's cloud endpoints used by the feature; no Octop runtime."""

    def __init__(self):
        self.accounts = defaultdict(CloudAccount)
        self.calls = []
        self.lose_schedule_response = False

    def __call__(self, request):
        path = request.url.path
        method = request.method
        payload = json.loads(request.content) if request.content else {}
        assert request.url.host == "api.lynxce.cn"
        if path == "/api/auth/password-login":
            identity = payload["account"]
            return success(
                {
                    "user": {"id": identity, "displayName": identity},
                    "accessToken": f"access-{identity}",
                    "refreshToken": f"refresh-{identity}",
                }
            )
        identity = request.headers["Authorization"].removeprefix("Bearer access-")
        account = self.accounts[identity]
        if path == "/api/user/personal-api-keys":  # desktop sign-in's chat key, not cloud work
            return success({"id": "key-" + identity, "secret": "sk-" + identity})
        self.calls.append((identity, method, path, payload))
        if path == "/api/auth/logout":
            return success({})
        if path == "/api/user/cloud-work/capabilities":
            return success({"enabled": True, "supportedModelIds": [MODEL], "defaultModelId": MODEL})
        if path == "/api/user/cloud-work/tasks" and method == "POST":
            for row in account.tasks.values():
                if row["requestId"] == payload["requestId"]:
                    return success(row)
            tid = str(uuid4())
            row = {
                "id": tid,
                "requestId": payload["requestId"],
                "sessionId": payload["sessionId"],
                "status": "queued",
                "model": payload["model"],
                "instruction": payload["message"],
                "executor": payload["executor"],
                "createdAt": NOW,
                "updatedAt": NOW,
            }
            account.tasks[tid] = row
            account.append(row["sessionId"], row["instruction"], "user", row["instruction"], tid)
            return success(row)
        if path == "/api/user/cloud-work/tasks":
            return success(
                {
                    "items": [
                        r
                        for r in reversed(account.tasks.values())
                        if r["sessionId"] == request.url.params["sessionId"]
                    ]
                }
            )
        if path.endswith("/actions"):
            row = account.tasks[path.split("/")[-2]]
            row["status"] = {"input": "running", "cancel": "cancelled"}[payload["action"]]
            return success(row)
        if path == "/api/user/web-chat-sessions":
            return success(
                {
                    "items": [
                        {**s, "messageCount": len(s["items"])} for s in account.sessions.values()
                    ],
                    "nextCursor": None,
                }
            )
        if path.startswith("/api/user/web-chat-sessions/"):
            sid = path.rsplit("/", 1)[1]
            return (
                success(account.sessions[sid]) if sid in account.sessions else httpx.Response(404)
            )
        if path == "/api/user/scheduled-tasks" and method == "POST":
            tid = str(uuid4())
            row = {
                "id": tid,
                **payload,
                "sessionId": "sched-" + tid,
                "ruleText": "Weekly · Asia/Shanghai",
                "enabled": True,
                "nextRunAt": NOW,
                "lastRunAt": None,
                "lastStatus": "",
                "lastResultPreview": "",
                "lastError": "",
                "runCount": 0,
            }
            account.schedules[tid] = row
            if self.lose_schedule_response:
                self.lose_schedule_response = False
                raise httpx.ReadTimeout("lost response after hosted commit", request=request)
            return success(row)
        if path == "/api/user/scheduled-tasks":
            return success({"items": list(account.schedules.values())})
        if path.startswith("/api/user/scheduled-tasks/"):
            tid = path.split("/")[4]
            if tid not in account.schedules:
                return httpx.Response(404)
            row = account.schedules[tid]
            if path.endswith("/enabled"):
                row["enabled"] = payload["enabled"]
            return success(row)
        raise AssertionError((method, path))


@pytest.fixture
def upstream(monkeypatch):
    monkeypatch.setenv("OCTOP_DESKTOP_SHELL", "1")
    monkeypatch.setenv("OCTOP_DESKTOP_PRODUCT", "bot")
    hosted = HostedAPI()
    monkeypatch.setattr(
        lynxce_cloud, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(hosted))
    )
    return hosted


async def connect(client, auth, account="same"):
    response = await client.post(
        API + "/account", headers=auth, json={"account": account, "password": "test-only-pass"}
    )
    response.raise_for_status()
    assert response.json()["account_id"] == account


def local_bot(server):
    return server.services.agent_repo.create(
        agent_id="editor",
        user_id=server.user_manager.get("admin").id,
        name="编辑",
        description="负责校对与采访提纲。",
        system_prompt="private-local-instructions",
        config_json='{"private_settings":true}',
    )


async def test_queued_work_continues_after_logout_and_is_resumed_by_second_device(
    env_admin_alice, upstream
):
    client, server, device_a, device_b = env_admin_alice
    await connect(client, device_a)
    bot = local_bot(server)
    hosted = upstream.accounts["same"]
    hosted.append("web-other-app", "Another product", "user", "unrelated conversation")
    turn = {
        "account_id": "same",
        "request_id": str(uuid4()),
        "message": "准备采访提纲",
        "bot_id": bot,
    }
    response = await client.post(API + "/turns", headers=device_a, json=turn)
    assert response.status_code == 202, response.text
    task = response.json()
    sid = task["session_id"]
    assert task["status"] == "queued"
    payload = upstream.calls[-1][3]
    assert (
        payload["executor"] == "cloud"
        and payload["attachments"] == []
        and payload["model"] == MODEL
    )
    assert set(payload) == {
        "message",
        "requestId",
        "sessionId",
        "model",
        "mode",
        "executor",
        "attachments",
    }
    assert (
        "负责校对" in payload["message"] and "private-local-instructions" not in payload["message"]
    )
    assert (await client.post(API + "/turns", headers=device_a, json=turn)).json()["id"] == task[
        "id"
    ]
    assert len(hosted.tasks) == 1
    (await client.delete(API + "/account", headers=device_a)).raise_for_status()
    hosted.finish(task["id"], "采访提纲已就绪。")
    await connect(client, device_b)
    assert (await client.get(API + "/sessions", headers=device_b)).json()["items"] == [
        {"id": sid, "title": "准备采访提纲", "model": MODEL, "updated_at": NOW, "message_count": 2}
    ]
    detail = (await client.get(f"{API}/sessions/{sid}", headers=device_b)).json()
    assert [m["content"] for m in detail["items"]] == ["准备采访提纲", "采访提纲已就绪。"]
    assert detail["tasks"][0]["status"] == "completed"
    follow = {
        "session_id": sid,
        "account_id": "same",
        "request_id": str(uuid4()),
        "message": "再加一个问题",
    }
    resumed = await client.post(API + "/turns", headers=device_b, json=follow)
    assert resumed.status_code == 202 and resumed.json()["session_id"] == sid
    assert "负责校对" in upstream.calls[-1][3]["message"]
    assert (
        await client.post(API + "/turns", headers=device_b, json={**follow, "bot_id": bot})
    ).status_code == 404
    assert (await client.get(API + "/sessions/web-other-app", headers=device_b)).status_code == 404
    await connect(client, device_b, "other")
    assert (
        await client.get(API + "/sessions", headers={**device_b, "X-Octop-Cloud-Account": "same"})
    ).status_code == 409
    assert (await client.get(API + "/sessions", headers=device_b)).json()["items"] == []
    assert (await client.get(f"{API}/sessions/{sid}", headers=device_b)).status_code == 404
    assert (await client.post(API + "/turns", headers=device_b, json=follow)).status_code == 403
    assert not upstream.accounts["other"].tasks


async def test_hosted_scheduler_result_and_uncertain_create(env_admin_alice, upstream):
    client, server, device_a, device_b = env_admin_alice
    await connect(client, device_a)
    await connect(client, device_b)
    bot = local_bot(server)
    body = {
        "account_id": "same",
        "name": "每周编辑简报",
        "instruction": "整理本周公开素材",
        "bot_id": bot,
        "rule": {
            "frequency": "weekly",
            "weekdays": [1, 4],
            "hour": 8,
            "minute": 15,
            "timezone": "Asia/Shanghai",
        },
    }
    upstream.lose_schedule_response = True
    assert (await client.post(API + "/schedules", headers=device_a, json=body)).status_code == 502
    # The cloud committed before the response was lost. A second POST would create another schedule.
    assert (
        len([call for call in upstream.calls if call[1:3] == ("POST", "/api/user/scheduled-tasks")])
        == 1
    )
    (await client.delete(API + "/account", headers=device_a)).raise_for_status()
    hosted = upstream.accounts["same"]
    tid = next(iter(hosted.schedules))
    row = hosted.schedules[tid]
    assert (
        "agentId" not in row and row["rule"]["weekdays"] == [1, 4] and row["rule"]["monthDay"] == 1
    )
    hosted.schedule_run(tid)
    foreign = str(uuid4())
    hosted.schedules[foreign] = {
        **row,
        "id": foreign,
        "sessionId": "sched-" + foreign,
        "name": "Unrelated task",
    }
    hosted.schedule_run(foreign)
    schedules = (await client.get(API + "/schedules", headers=device_b)).json()["items"]
    assert (
        len(schedules) == 1 and schedules[0]["id"] == tid and schedules[0]["name"] == body["name"]
    )
    assert schedules[0]["instruction"] == body["instruction"] and schedules[0]["bot_name"] == "编辑"
    sid = schedules[0]["session_id"]
    assert schedules[0]["last_result_preview"] == "Hosted digest"
    assert [
        s["id"] for s in (await client.get(API + "/sessions", headers=device_b)).json()["items"]
    ] == [sid]
    detail = (await client.get(f"{API}/sessions/{sid}", headers=device_b)).json()
    assert detail["items"][-1]["content"] == "Hosted digest"
    followed = await client.post(
        API + "/turns",
        headers=device_b,
        json={
            "account_id": "same",
            "request_id": str(uuid4()),
            "session_id": sid,
            "message": "展开第一点",
        },
    )
    assert followed.status_code == 202 and followed.json()["session_id"] == sid
    assert "负责校对" in upstream.calls[-1][3]["message"]
    for enabled in (False, True):
        toggled = await client.put(
            f"{API}/schedules/{tid}/enabled",
            headers=device_b,
            json={"account_id": "same", "enabled": enabled},
        )
        assert toggled.json()["enabled"] is enabled
        assert not toggled.json()["finished_once"]
    row.update(rule={**row["rule"], "frequency": "once"}, enabled=False)
    finished = (await client.get(API + "/schedules", headers=device_b)).json()["items"][0]
    assert finished["finished_once"] and finished["session_id"] == sid
    assert (
        await client.get(f"{API}/sessions/sched-{foreign}", headers=device_b)
    ).status_code == 404
    assert (
        await client.put(
            f"{API}/schedules/{foreign}/enabled",
            headers=device_b,
            json={"account_id": "same", "enabled": False},
        )
    ).status_code == 404
    assert hosted.schedules[foreign]["enabled"] is True
    await connect(client, device_b, "other")
    assert (await client.get(API + "/schedules", headers=device_b)).json()["items"] == []
    assert (
        await client.put(
            f"{API}/schedules/{tid}/enabled",
            headers=device_b,
            json={"account_id": "other", "enabled": False},
        )
    ).status_code == 404


async def test_only_answer_an_explicit_hosted_question(env, upstream):
    client, _, auth = env
    await connect(client, auth)
    turn = {"account_id": "same", "request_id": str(uuid4()), "message": "编辑一份摘要"}
    result = (await client.post(API + "/turns", headers=auth, json=turn)).json()
    row = upstream.accounts["same"].tasks[result["id"]]
    answer = {
        **turn,
        "request_id": str(uuid4()),
        "session_id": result["session_id"],
        "input_task_id": row["id"],
        "message": "使用上周数据",
    }
    for status, extra in [
        ("queued", {}),
        ("waiting_user", {"waitingFor": "media"}),
        ("waiting_user", {"waitingFor": {"kind": "approval"}}),
        ("waiting_user", {"takeoverAvailable": True}),
        ("waiting_user", {"executor": "computer"}),
    ]:
        row.update(
            status=status,
            question="选择一周",
            waitingFor=None,
            takeoverAvailable=False,
            executor="cloud",
        )
        row.update(extra)
        assert (await client.post(API + "/turns", headers=auth, json=answer)).status_code in {
            404,
            409,
        }
    assert not [call for call in upstream.calls if call[2].endswith("/actions")]
    row.update(
        status="waiting_user",
        question="选择一周",
        waitingFor=None,
        takeoverAvailable=False,
        executor="cloud",
    )
    response = await client.post(API + "/turns", headers=auth, json=answer)
    assert response.status_code == 202 and response.json()["status"] == "running"
    assert upstream.calls[-1][3] == {
        "requestId": answer["request_id"],
        "action": "input",
        "text": "使用上周数据",
    }
    for forbidden in ("workspace", "executor", "attachments", "agentId"):
        assert (
            await client.post(
                API + "/turns", headers=auth, json={**turn, forbidden: "should not leave the host"}
            )
        ).status_code == 422


async def test_continue_imported_web_history_without_a_prior_cloud_task(env_admin_alice, upstream):
    client, server, _, device_b = env_admin_alice
    await connect(client, device_b)
    sid = f"octop-bot-v1-{uuid4()}"
    hosted = upstream.accounts["same"]
    public_text = await role_instruction(
        server.services, server.user_manager.get("admin").id, local_bot(server), "编写初稿", 40000
    )
    hosted.append(sid, "初稿", "user", public_text)
    hosted.append(sid, "初稿", "assistant", "初稿内容。")
    hosted.sessions[sid]["model"] = "retired-model"
    detail = await client.get(f"{API}/sessions/{sid}", headers=device_b)
    assert detail.json()["tasks"] == [] and detail.json()["items"][0]["content"] == "编写初稿"
    response = await client.post(
        API + "/turns",
        headers=device_b,
        json={
            "request_id": str(uuid4()),
            "account_id": "same",
            "session_id": sid,
            "message": "继续修改",
        },
    )
    assert response.status_code == 202 and response.json()["model"] == MODEL
    payload = upstream.calls[-1][3]
    assert "负责校对" in payload["message"] and "初稿内容" not in payload["message"]


async def test_cancel_pins_the_task_session_and_platform_executor(env, upstream):
    client, _, auth = env
    await connect(client, auth)
    request = {"account_id": "same", "request_id": str(uuid4()), "message": "一份报告"}
    task = (await client.post(API + "/turns", headers=auth, json=request)).json()
    body = {"account_id": "same", "request_id": str(uuid4()), "session_id": task["session_id"]}
    path = f"{API}/tasks/{task['id']}/cancel"
    assert (
        await client.post(
            path, headers=auth, json={**body, "session_id": f"octop-bot-v1-{uuid4()}"}
        )
    ).status_code == 404
    record = upstream.accounts["same"].tasks[task["id"]]
    record["executor"] = "computer"
    assert (await client.post(path, headers=auth, json=body)).status_code == 404
    record.update(executor="cloud", status="waiting_user", takeoverAvailable=True)
    stopped = await client.post(path, headers=auth, json=body)
    assert stopped.status_code == 200 and stopped.json()["status"] == "cancelled"
    assert (await client.post(path, headers=auth, json=body)).json()["status"] == "cancelled"
    assert [call[3] for call in upstream.calls if call[2].endswith("/actions")] == [
        {"action": "cancel", "requestId": body["request_id"]}
    ]


async def test_private_shared_and_managed_bots_remain_local(env, upstream):
    client, server, auth = env
    await connect(client, auth)
    repo = server.services.agent_repo
    owner = server.user_manager.get("admin").id
    for kind, config, shared in [
        ("expert", '{"octop_bot":{"private":true}}', False),
        ("managed", None, False),
        ("expert", None, True),
    ]:
        bot_id = str(uuid4())
        repo.create(
            agent_id=bot_id, user_id=owner, name=f"Local {bot_id}", kind=kind, config_json=config
        )
        repo.set_shared(bot_id, shared)
        body = {
            "account_id": "same",
            "request_id": str(uuid4()),
            "message": "文本",
            "bot_id": bot_id,
        }
        assert (await client.post(API + "/turns", headers=auth, json=body)).status_code == 404
        assert (
            await client.post(
                API + "/schedules",
                headers=auth,
                json={
                    "account_id": "same",
                    "name": "简报",
                    "instruction": "文本",
                    "bot_id": bot_id,
                    "rule": {
                        "frequency": "daily",
                        "hour": 9,
                        "minute": 0,
                        "timezone": "Asia/Shanghai",
                    },
                },
            )
        ).status_code == 404
    assert not upstream.calls
