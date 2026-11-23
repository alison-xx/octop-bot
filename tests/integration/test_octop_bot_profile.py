"""Bot profile: upcoming scheduled tasks and the files the Bot made for me."""

from __future__ import annotations

from typing import Any


def _bot(aid: str, tail: str) -> str:
    return f"/api/octop-bot/bots/{aid}/{tail}"


async def test_upcoming_lists_my_tasks_soonest_first_and_hides_them_from_others(
    env_alice_bob_agent: Any,
) -> None:
    client, _srv, alice, bob, aid = env_alice_bob_agent
    created = {}
    for name, trigger, enabled in [
        ("Evening digest", "cron:0 23 * * *", True),
        ("Paused", "cron:0 6 * * *", False),
        ("Inbox sweep", "interval:900", True),
    ]:
        r = await client.post(
            f"/api/agents/{aid}/cron",
            headers=alice,
            json={"name": name, "trigger": trigger, "prompt": name, "enabled": enabled},
        )
        assert r.status_code == 201, r.text
        created[name] = r.json()["id"]

    r = await client.get(_bot(aid, "upcoming"), headers={**alice, "Accept-Language": "zh-CN"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["timezone"]
    jobs = body["jobs"]
    assert [job["name"] for job in jobs][-1] == "Paused"
    by_name = {job["name"]: job for job in jobs}
    assert by_name["Evening digest"]["schedule"] == "每天 23:00"
    assert by_name["Inbox sweep"]["schedule"] == "每 15 分钟"
    assert by_name["Evening digest"]["next_run_at"] is not None
    assert by_name["Paused"]["next_run_at"] is None and by_name["Paused"]["can_toggle"]
    assert by_name["Paused"]["id"] == created["Paused"]

    en = (
        await client.get(_bot(aid, "upcoming"), headers={**alice, "Accept-Language": "en"})
    ).json()
    assert {job["schedule"] for job in en["jobs"]} >= {"Daily at 23:00", "Every 15 min"}

    assert (await client.get(_bot(aid, "upcoming"), headers=bob)).status_code == 404
    assert (await client.get(_bot("missing", "upcoming"), headers=alice)).status_code == 404


async def test_library_lists_existing_bot_files_newest_first(env_alice_bob_agent: Any) -> None:
    client, srv, alice, bob, aid = env_alice_bob_agent
    r = await client.post(f"/api/agents/{aid}/threads", headers=alice, json={})
    assert r.status_code in (200, 201), r.text
    thread_id = r.json()["thread_id"]

    workspace = srv.app_runtime.agent_registry.workspace_for_agent(aid)
    await workspace.aupload_bytes("outbound/report.pdf", b"%PDF-1.4 report")
    await workspace.aupload_bytes("notes.md", b"# notes")
    repo = srv.services.thread_repo
    repo.append_artifacts(
        thread_id,
        ["outbound/report.pdf", "notes.md", "outbound/deleted.txt", ".octop/plans/p.md"],
        agent_id=aid,
    )
    repo.append_artifacts(thread_id, ["outbound/other.txt"], agent_id="someone-else")

    r = await client.get(_bot(aid, "library"), headers=alice)
    assert r.status_code == 200, r.text
    files = r.json()["files"]
    by_name = {f["name"]: f for f in files}
    assert set(by_name) == {"report.pdf", "notes.md"}
    report = by_name["report.pdf"]
    assert report["path"] == "outbound/report.pdf"
    assert report["size"] == len(b"%PDF-1.4 report")
    assert report["mime"] == "application/pdf"
    assert report["thread_id"] == thread_id
    assert report["period"] == "today"
    assert report["url"] == f"/api/agents/{aid}/workspace/download?path=outbound%2Freport.pdf"
    assert [f["created_at"] for f in files] == sorted(
        (f["created_at"] for f in files), reverse=True
    )

    download = await client.get(report["url"], headers=alice)
    assert download.status_code == 200 and download.content == b"%PDF-1.4 report"

    assert (await client.get(_bot(aid, "library"), headers=bob)).status_code == 404
