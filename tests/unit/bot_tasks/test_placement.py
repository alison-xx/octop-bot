from octop.infra.bot_tasks.placement import resolve_placement, tool_at_location


def test_turn_choice_overrides_only_the_bot_default() -> None:
    assert resolve_placement("local", None) == "local"
    assert resolve_placement("local", "auto") == "auto"
    assert resolve_placement("cloud", "local") == "local"
    assert not tool_at_location("cloud_computer", "local")
    assert not tool_at_location("execute", "local")
    assert not tool_at_location("task", "local")
    assert tool_at_location("ask_user_question", "local")
    assert tool_at_location("local_computer", "local")
    assert tool_at_location("wait_for_local_device", "local")
    assert not tool_at_location("wait_for_local_device", "cloud")
    assert tool_at_location("task_read_step", "local")
    assert tool_at_location("task_extend_budget", "local")
    assert not tool_at_location("local_computer", "cloud")
    assert tool_at_location("cloud_computer", "auto")


def test_only_the_current_owners_bot_message_carries_location_through_resume() -> None:
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    from octop.infra.bot_tasks.placement import PLACEMENT_KEY, placement_for_turn
    from octop.infra.gateway.process.message_keys import AUTHOR_USER_ID_KEY

    user = HumanMessage(
        content="read my notes", additional_kwargs={AUTHOR_USER_ID_KEY: 17, PLACEMENT_KEY: "local"}
    )
    messages = [
        user,
        AIMessage(content="waiting"),
        ToolMessage(content="answered", tool_call_id="p"),
    ]
    assert placement_for_turn({"messages": messages}, 17) == "local"
    assert placement_for_turn({"messages": messages}, 18) is None
    messages.append(
        HumanMessage(content="scheduled check", additional_kwargs={AUTHOR_USER_ID_KEY: 17})
    )
    assert placement_for_turn({"messages": messages}, 17) is None
