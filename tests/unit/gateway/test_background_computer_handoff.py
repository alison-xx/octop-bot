"""Scheduled and IM handoffs use the real control database and an isolated provider."""

from __future__ import annotations

import asyncio
from contextvars import Context
from unittest.mock import MagicMock

import pytest
from tests.unit.cloud.test_cloud_computers import sole_computer as sole_computer
from tests.unit.cron.test_cron_delivery import _agent_delivery, _command, _policy_store

from octop.infra.cloud.computers.handoff import background_computer_turn, current_background_turn
from octop.infra.cron.delivery import CronWaitingForUser
from octop.infra.db.services import RepoBundle
from octop.infra.gateway.hitl.coordinator import HitlChannelCoordinator, HitlStreamContext
from octop.infra.gateway.hitl.store import HitlPendingStore
from octop.infra.gateway.process.stream_project import project_resume_stream, project_stream

REQUEST = {
    "action_requests": [
        {"name": "ask_user_question", "args": {"questions": [{"question": "Continue?"}]}}
    ]
}


@pytest.mark.parametrize("entry", ["cron", "im", "resume"])
@pytest.mark.parametrize(
    "case", ["exclusive", "shared", "foreground", "observer", "write_failure", "no_computer"]
)
async def test_pause_follows_durable_card(sole_computer, monkeypatch, entry, case):
    manager, driver, billing, _, owner, db = sole_computer
    repo = RepoBundle.from_pool(db).handoff_repo
    hitl = HitlChannelCoordinator(HitlPendingStore(repo=repo))
    ctx = HitlStreamContext("thr1", "bot", owner, "sk", "feishu")

    async def model(*_args):
        turn = current_background_turn(owner, "bot")
        assert turn is not None and turn.thread_id == "thr1"
        if case != "no_computer":
            await asyncio.to_thread(manager.ensure_running, "bot", owner)
        if case == "shared":
            with background_computer_turn(owner, "bot", "second chat"):
                await asyncio.to_thread(manager.ensure_running, "bot", owner)
        if case == "foreground":
            await asyncio.to_thread(Context().run, manager.ensure_running, "bot", owner)
        if case == "observer":
            await asyncio.to_thread(Context().run, manager.viewing, "bot", owner)
        yield {"type": "hitl_required", "request": REQUEST}

    if case == "write_failure":

        def fail(*_args, **_kwargs):
            raise RuntimeError("pending card write failed")

        monkeypatch.setattr(repo, "save", fail)

    actual_pause = driver.pause

    def pause_after_commit(instance):
        assert len(HitlPendingStore(repo=repo).pending_for_user(owner)) == 1
        actual_pause(instance)

    monkeypatch.setattr(driver, "pause", pause_after_commit)

    async def run():
        if entry == "cron":
            service, gateway = _agent_delivery(model, store=_policy_store()[0])
            gateway.processor.hitl_coordinator = hitl
            session = gateway.require_session.return_value
            session.agent_id = "bot"
            session.user_id = owner
            with pytest.raises(CronWaitingForUser):
                await service.deliver(_command(agent_id="bot", user_id=owner, task_type="agent"))
            gateway.push_session_text.assert_awaited_once()
        else:
            agents = MagicMock()
            agents.stream = agents.resume_hitl = model
            kwargs = {"hitl_coordinator": hitl, "hitl_ctx": ctx}
            stream = (
                project_stream(agents, "bot", {}, **kwargs)
                if entry == "im"
                else project_resume_stream(agents, "bot", "thr1", [], **kwargs)
            )
            card = await asyncio.create_task(anext(stream))
            assert card.metadata["octop_hitl_pending_id"]
            assert current_background_turn(owner, "bot") is None
            with pytest.raises(StopAsyncIteration):
                await asyncio.create_task(anext(stream))

    if case == "write_failure":
        with pytest.raises(RuntimeError, match="pending card write failed"):
            await run()
    else:
        await run()
    cards = HitlPendingStore(repo=repo).pending_for_user(owner)
    assert len(cards) == int(case != "write_failure")
    if cards:
        # A second projection can resolve the same card without claiming another wake.
        with background_computer_turn(owner, "bot", "thr1") as retry:
            same = await hitl.register_waiting_turn(
                REQUEST, ctx=ctx, turn=retry, origin=cards[0].origin
            )
        assert same.pending_id == cards[0].pending_id
    assert [op for op, _ in driver.calls] == {
        "exclusive": ["start", "pause"],
        "shared": ["start"],
        "foreground": ["start"],
        "observer": ["start"],
        "write_failure": ["start"],
        "no_computer": [],
    }[case]
    assert len(billing.settled) == int(case == "exclusive")


@pytest.mark.parametrize("channel", ["dashboard", "cli", "mcp", "octop_bot_group", "unknown"])
async def test_virtual_foreground_never_claims_background_computer(sole_computer, channel):
    _, _, _, _, owner, db = sole_computer
    hitl = HitlChannelCoordinator(HitlPendingStore(repo=RepoBundle.from_pool(db).handoff_repo))
    ctx = HitlStreamContext("thr1", "bot", owner, "sk", channel)

    async def model(*_args):
        assert current_background_turn(owner, "bot") is None
        yield {"type": "token", "content": "ready"}

    agents = MagicMock()
    agents.stream = model
    events = [
        event
        async for event in project_stream(agents, "bot", {}, hitl_coordinator=hitl, hitl_ctx=ctx)
    ]
    assert events


async def test_cancelling_im_delivery_drops_handle_and_closes_model(sole_computer):
    manager, driver, _, _, owner, db = sole_computer
    hitl = HitlChannelCoordinator(HitlPendingStore(repo=RepoBundle.from_pool(db).handoff_repo))
    ctx = HitlStreamContext("thr1", "bot", owner, "sk", "feishu")
    observed = []
    closed = asyncio.Event()

    async def model(*_args):
        turn = current_background_turn(owner, "bot")
        assert turn is not None
        observed.append(turn)
        try:
            await asyncio.to_thread(manager.ensure_running, "bot", owner)
            yield {"type": "token", "content": "ready"}
            await asyncio.Event().wait()
        finally:
            closed.set()

    agents = MagicMock()
    agents.stream = model
    stream = project_stream(agents, "bot", {}, hitl_coordinator=hitl, hitl_ctx=ctx)
    await asyncio.wait_for(anext(stream), 5)
    await asyncio.wait_for(stream.aclose(), 5)
    assert closed.is_set() and not observed[0].active
    assert hitl.store.pending_for_user(owner) == []
    assert [op for op, _ in driver.calls] == ["start"]
