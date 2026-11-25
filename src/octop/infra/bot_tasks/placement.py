"""The locations an owner permits for the next computer operation."""

from __future__ import annotations

from typing import Any, Literal

from langchain_core.messages import HumanMessage

from octop.infra.db.repos.settings import SettingsRepo

PLACEMENT_KEY = "octop_bot_computer_placement"
Placement = Literal["auto", "cloud", "local"]
# These tools record task state or ask the user. A local-only turn may not
# delegate to another agent or invoke the Bot workspace's cloud file tools.
_LOCAL_TOOLS = frozenset(
    {
        "local_computer",
        "wait_for_local_device",
        "task_read_step",
        "task_extend_budget",
        "task_plan",
        "task_check",
        "task_finish",
        "ask_user_question",
        "request_approval",
    }
)


def bot_placement(settings: SettingsRepo, agent: str) -> Placement:
    value = settings.get(f"octop_bot:placement:{agent}")
    return value if value in ("cloud", "local") else "auto"  # type: ignore[return-value]


def set_bot_placement(settings: SettingsRepo, agent: str, placement: Placement) -> None:
    settings.set(f"octop_bot:placement:{agent}", placement)


def resolve_placement(default: Placement, turn: Any) -> Placement:
    if turn == "local":
        return "local"
    if turn == "cloud":
        return "cloud"
    return "auto" if turn == "auto" else default


def tool_at_location(name: str, mode: Placement) -> bool:
    if mode == "local":
        return name in _LOCAL_TOOLS
    return mode != "cloud" or name not in {"local_computer", "wait_for_local_device"}


def placement_for_turn(state: Any, owner: int) -> Placement | None:
    """Read the user message kept by the graph checkpoint, including after a pause."""
    from octop.infra.gateway.process.message_keys import AUTHOR_USER_ID_KEY

    messages = state.get("messages", []) if isinstance(state, dict) else []
    for message in reversed(messages):
        if isinstance(message, HumanMessage) and not message.additional_kwargs.get("lc_source"):
            fields = message.additional_kwargs
            if fields.get(AUTHOR_USER_ID_KEY) != owner:
                return None
            value = fields.get(PLACEMENT_KEY)
            return value if value in ("auto", "cloud", "local") else None
    return None
