"""Exercise the room bridge with the real session DB and a network-free IM transport."""

import pytest
from octop_gateway.models import ChannelSubject, InboundMessage, MessageEvent, TextContent

from octop.infra.bot_groups.im import GroupImRouter
from octop.infra.gateway.process.message_keys import session_key_from_message


@pytest.mark.asyncio
async def test_room_link_routes_one_conversation_and_deduplicates_replies(
    env_alice_bob_agent, monkeypatch
):
    client, server, alice, bob, bot = env_alice_bob_agent
    services = server.services
    runtime = server.app_runtime
    owner = services.agent_repo.get(bot).user_id
    root = "/api/octop-bot/groups"
    group = {"name": "Editorial", "admin_id": bot}
    created = await client.post(root, headers=alice, json=group)
    created.raise_for_status()
    path = root + "/" + created.json()["group_id"] + "/im-sessions"
    second = await client.post(root, headers=alice, json={**group, "name": "Other"})
    second.raise_for_status()
    other = root + "/" + second.json()["group_id"] + "/im-sessions"

    channel_id = services.channel_repo.create(
        channel_id="local-transport",
        agent_id=bot,
        user_id=owner,
        name="Local Telegram",
        kind="telegram",
        config_json="{}",
    )
    observed = InboundMessage(
        channel_id=channel_id,
        channel_type="telegram",
        tenant_id=bot,
        channel_subject=ChannelSubject("audience"),
        content=[TextContent(text="Plan the post")],
        metadata={"message_id": 123, "chat_type": "group"},
    )
    key = session_key_from_message(observed, agent_id=bot)
    services.session_repo.upsert(
        session_key=key,
        agent_id=bot,
        user_id=owner,
        channel_id=channel_id,
        channel_type="telegram",
        chat_type="group",
        thread_id="prior-thread",
        channel_chat_type="group",
        channel_subject_id="audience",
    )
    params = {"channel_id": channel_id, "session_key": key, "linked": True}
    assert (await client.get(path, headers=bob)).status_code == 404
    assert (await client.get(path, headers=alice)).json()[0]["linked"] is False
    assert (
        await client.put(path, headers=alice, json={**params, "session_key": "unseen"})
    ).status_code == 404
    linked = await client.put(path, headers=alice, json=params)
    linked.raise_for_status()
    assert linked.json()[0]["linked"] is True
    assert (await client.get(other, headers=alice)).json()[0]["linked_elsewhere"] is True
    assert (await client.put(other, headers=alice, json=params)).status_code == 409

    model_calls = []

    async def controlled_model(msg):
        model_calls.append((msg.tenant_id, msg.channel_type))
        yield {"type": "token", "content": "Ready for review"}

    monkeypatch.setattr(runtime.gateway.processor, "iter_turn_chunks", controlled_model)
    direct_calls = []

    async def direct(msg):
        direct_calls.append(msg.channel_subject.subject_id)
        yield MessageEvent.text("Direct")

    processor = GroupImRouter(lambda: services, lambda: runtime).wrap(
        services.channel_repo.get(channel_id), direct
    )

    async def receive(msg):
        return [
            part.text
            async for event in processor(msg)
            for part in event.content
            if isinstance(part, TextContent)
        ]

    spoof = observed.model_copy(
        update={
            "channel_subject": ChannelSubject("other-contact"),
            "metadata": {**observed.metadata, "session_key": key},
        }
    )
    assert await receive(spoof) == ["Direct"]
    assert await receive(observed.model_copy(update={"tenant_id": "foreign-bot"})) == []
    assert (
        await receive(
            observed.model_copy(update={"metadata": {**observed.metadata, "from_self": True}})
        )
        == []
    )
    assert await receive(observed.model_copy(update={"allowed_tools": []})) != []
    assert not model_calls
    assert await receive(observed) == ["alice-channels-bot\nReady for review"]
    assert await receive(observed) == []
    assert len(model_calls) == 1
    assert direct_calls == ["other-contact"]
    history = (await client.get(path.rsplit("/", 1)[0] + "/messages", headers=alice)).json()
    assert [message["text"] for message in history] == ["Plan the post", "Ready for review"]

    assert (await client.put(path, headers=alice, json={**params, "linked": False})).json()[0][
        "linked"
    ] is False
    assert await receive(observed) == ["Direct"]
    assert (await client.put(other, headers=alice, json=params)).status_code == 200
    assert (await client.delete(other.rsplit("/", 1)[0], headers=alice)).status_code == 204
    assert await receive(observed) == ["Direct"]


@pytest.mark.parametrize("chat_type", ["group", "dm"])
async def test_logged_in_owner_reviews_im_handoff(env_alice_bob_agent, monkeypatch, chat_type):
    client, server, alice, _, bot = env_alice_bob_agent
    rt = server.app_runtime
    monkeypatch.setenv("OCTOP_BOT_CLOUD", "1")
    calls = []
    sample = "Review sample sheet 17"
    policies = rt.gateway.processor.hitl_coordinator.session_policies

    async def model(_agent, request):
        # A saved generic preference belongs to the signed-in owner.
        thread = request["thread_id"]
        policies.set(thread, {"mode": "allow_all"})
        assert not policies.allows(thread, "sample_review")
        yield {
            "type": "hitl_required",
            "request": {
                "action_requests": [{"name": "sample_review", "description": sample, "args": {}}],
                "review_configs": [
                    {"action_name": "sample_review", "allowed_decisions": ["approve", "reject"]}
                ],
            },
        }

    async def resume(agent_id, thread_id, decisions):
        calls.append((agent_id, thread_id, decisions))
        yield {"type": "token", "content": "Sample reviewed."}

    monkeypatch.setattr(rt.agent_registry, "stream", model)
    monkeypatch.setattr(rt.agent_registry, "resume_hitl", resume)
    owner = server.services.agent_repo.get(bot).user_id
    channel = server.services.channel_repo.create(
        channel_id="sample-inbox",
        agent_id=bot,
        user_id=owner,
        name="Sample IM",
        kind="telegram",
        config_json="{}",
    )
    msg = InboundMessage(
        channel_id=channel,
        channel_type="telegram",
        tenant_id=bot,
        channel_subject=ChannelSubject("sample-conversation", chat_type=chat_type),
        content=[TextContent(text="Please prepare the fictional sample for review.")],
        metadata={"chat_type": chat_type},
    )
    events = [event async for event in rt.gateway.processor(msg)]
    inbox = await client.get("/api/octop-bot/inbox", headers=alice)
    inbox.raise_for_status()
    (card,) = [item for item in inbox.json()["items"] if item["agent_id"] == bot]
    assert card["text"] == sample
    assert all(not event.metadata.get("octop_hitl_pending_id") for event in events)
    assert all(
        sample not in str(event.content) and card["pending_id"] not in str(event)
        for event in events
    )
    assert any(
        "inbox" in str(event.content).lower() or "待办" in str(event.content) for event in events
    )
    decisions = [{"type": "approve"}]
    response = await client.post(
        f"/api/agents/{bot}/chat/hitl/resume",
        headers=alice,
        json={
            "thread_id": card["thread_id"],
            "pending_id": card["pending_id"],
            "decisions": decisions,
        },
    )
    response.raise_for_status()
    assert calls == [(bot, card["thread_id"], decisions)]
    assert "Sample reviewed." in response.text
    assert (await client.get("/api/octop-bot/inbox", headers=alice)).json()["items"] == []


async def test_hosted_dm_contact_can_answer_an_ordinary_question(env_alice_bob_agent, monkeypatch):
    client, server, alice, _, bot = env_alice_bob_agent
    monkeypatch.setenv("OCTOP_BOT_CLOUD", "1")
    rt = server.app_runtime
    owner = server.services.agent_repo.get(bot).user_id
    question = "Which sample color should I use?"
    decisions = []

    async def model(*_args):
        yield {
            "type": "hitl_required",
            "request": {
                "action_requests": [
                    {
                        "name": "ask_user_question",
                        "args": {
                            "questions": [
                                {
                                    "header": "Sample color",
                                    "question": question,
                                    "options": [{"label": "Blue"}, {"label": "Green"}],
                                }
                            ]
                        },
                    }
                ],
                "review_configs": [
                    {"action_name": "ask_user_question", "allowed_decisions": ["respond"]}
                ],
            },
        }

    async def resume(_agent, _thread, answer):
        decisions.extend(answer)
        yield {"type": "token", "content": "The sample is blue."}

    monkeypatch.setattr(rt.agent_registry, "stream", model)
    monkeypatch.setattr(rt.agent_registry, "resume_hitl", resume)
    channel = server.services.channel_repo.create(
        channel_id="sample-dm",
        agent_id=bot,
        user_id=owner,
        name="Sample direct chat",
        kind="telegram",
        config_json="{}",
    )

    def message(text):
        return InboundMessage(
            channel_id=channel,
            channel_type="telegram",
            tenant_id=bot,
            channel_subject=ChannelSubject("sample-contact", chat_type="direct"),
            content=[TextContent(text=text)],
            metadata={"chat_type": "dm"},
        )

    prompt = [e async for e in rt.gateway.processor(message("Help me choose a sample color."))]
    assert any(question in str(e.content) for e in prompt)
    reply = [e async for e in rt.gateway.processor(message("Blue"))]
    assert (
        len(decisions) == 1
        and decisions[0]["type"] == "respond"
        and "Blue" in decisions[0]["message"]
    )
    assert any("The sample is blue." in str(e.content) for e in reply)
    assert (await client.get("/api/octop-bot/inbox", headers=alice)).json()["items"] == []
