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
