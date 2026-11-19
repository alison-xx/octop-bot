"""Coordinate manual control of a running browser across the UI and bot tools."""

_manual: set[str] = set()


def control_owner_for(profile: str) -> str:
    return "user" if profile in _manual else "agent"


def set_control_owner(profile: str, target: str) -> None:
    if target == "user":
        _manual.add(profile)
    else:
        _manual.discard(profile)
