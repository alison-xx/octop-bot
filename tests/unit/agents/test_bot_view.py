import json
from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from octop.infra.agents.bot_view import show_view


def test_form_only_returns_data_after_real_human_response():
    class State(TypedDict):
        display: str

    def present(state: State) -> State:
        result = show_view.invoke(
            {
                "view": {
                    "kind": "form",
                    "title": "选题投票",
                    "questions": [{"question": "本周报道哪个领域？", "header": "领域"}],
                }
            }
        )
        return {"display": result}

    graph = StateGraph(State)
    graph.add_node("form", present)
    graph.add_edge(START, "form")
    graph.add_edge("form", END)
    app = graph.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "form", "octop_bot_browser": True}}
    paused = app.invoke({"display": ""}, config)
    assert paused["display"] == ""
    action = paused["__interrupt__"][0].value["action_requests"][0]
    assert action["name"] == "ask_user_question"
    assert action["args"]["questions"][0]["header"] == "领域"
    final = app.invoke(
        Command(resume={"decisions": [{"type": "respond", "message": "领域: 体育"}]}), config
    )
    result = json.loads(final["display"])
    assert result["octop_ui"]["renderer"] == "octop-bot-view"
    assert result["data"]["answers"] == ["体育"]
