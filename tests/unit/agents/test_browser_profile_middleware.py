from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from langgraph.prebuilt.tool_node import ToolCallRequest

from octop.infra.agents.middleware import browser_profile
from octop.infra.control.browser.handoff import set_control_owner


@pytest.mark.asyncio
async def test_bot_controls_are_isolated_and_respect_manual_handoff(monkeypatch) -> None:
    monkeypatch.setattr(browser_profile, "browser_enabled", lambda: True)
    monkeypatch.setattr(
        browser_profile,
        "get_config",
        lambda: {"configurable": {"user": "42", "octop_bot_browser": True}},
    )
    handler = AsyncMock(return_value=object())
    request = _request("browser_use", {"action": "navigate", "profile": "user-42"})
    first = browser_profile.BrowserProfileMiddleware("A")
    second = browser_profile.BrowserProfileMiddleware("a")
    set_control_owner("user-42-bot-41", "user")
    try:
        result = await first.awrap_tool_call(request, handler)
        assert getattr(result, "status", None) == "error"
        handler.assert_not_awaited()
        await second.awrap_tool_call(request, handler)
        assert handler.await_args.args[0].tool_call["args"]["profile"] == "user-42-bot-61"
    finally:
        set_control_owner("user-42-bot-41", "agent")
    await first.awrap_tool_call(request, handler)
    assert handler.await_args.args[0].tool_call["args"]["profile"] == "user-42-bot-41"


def _request(name: str, args: dict[str, object]) -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"name": name, "args": args, "id": "call-1"},
        tool=None,
        state={},
        runtime=None,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_browser_profile_is_forced_from_current_user(monkeypatch) -> None:
    monkeypatch.setattr(
        browser_profile,
        "get_config",
        lambda: {"configurable": {"user": "42"}},
    )
    handler = AsyncMock(return_value=object())
    request = _request("browser_use", {"action": "navigate", "profile": "default"})

    await browser_profile.BrowserProfileMiddleware().awrap_tool_call(request, handler)

    forwarded = handler.await_args.args[0]
    assert forwarded.tool_call["args"] == {
        "action": "navigate",
        "profile": "user-42",
    }


@pytest.mark.asyncio
async def test_non_browser_tool_is_unchanged(monkeypatch) -> None:
    monkeypatch.setattr(
        browser_profile,
        "get_config",
        lambda: {"configurable": {"user": "42"}},
    )
    handler = AsyncMock(return_value=object())
    request = _request("read_file", {"path": "notes.txt"})

    await browser_profile.BrowserProfileMiddleware().awrap_tool_call(request, handler)

    assert handler.await_args.args[0] is request


@pytest.mark.asyncio
async def test_browser_profile_blocks_until_bundled_browser_is_enabled(monkeypatch) -> None:
    monkeypatch.setattr(browser_profile, "browser_enabled", lambda: False)
    monkeypatch.setattr(
        browser_profile,
        "get_config",
        lambda: {"configurable": {"user": "42"}},
    )
    handler = AsyncMock(return_value=object())
    request = _request("browser_use", {"action": "navigate", "profile": "default"})

    result = await browser_profile.BrowserProfileMiddleware().awrap_tool_call(request, handler)

    handler.assert_not_awaited()
    assert getattr(result, "status", None) == "error"
    assert "not enabled" in str(result.content)


@pytest.mark.asyncio
async def test_browser_profile_blocks_when_user_missing(monkeypatch) -> None:
    monkeypatch.setattr(browser_profile, "get_config", lambda: {"configurable": {}})
    handler = AsyncMock(return_value=object())
    request = _request("browser_use", {"action": "navigate", "profile": "default"})

    result = await browser_profile.BrowserProfileMiddleware().awrap_tool_call(request, handler)

    handler.assert_not_awaited()
    assert getattr(result, "status", None) == "error"
    assert "no Octop user id" in str(result.content)


@pytest.mark.asyncio
async def test_browser_profile_blocks_placeholder_user_zero(monkeypatch) -> None:
    monkeypatch.setattr(
        browser_profile,
        "get_config",
        lambda: {"configurable": {"user": "0"}},
    )
    handler = AsyncMock(return_value=object())
    request = _request("browser_use", {"action": "navigate"})

    result = await browser_profile.BrowserProfileMiddleware().awrap_tool_call(request, handler)

    handler.assert_not_awaited()
    assert getattr(result, "status", None) == "error"


@pytest.mark.asyncio
async def test_screenshots_land_in_the_agents_workspace(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        browser_profile,
        "get_config",
        lambda: {"configurable": {"user": "42"}},
    )
    handler = AsyncMock(return_value=object())
    middleware = browser_profile.BrowserProfileMiddleware("A", tmp_path)

    async def forwarded_args(args: dict[str, object]) -> dict[str, object]:
        await middleware.awrap_tool_call(_request("browser_use", args), handler)
        return handler.await_args.args[0].tool_call["args"]

    shot = await forwarded_args({"action": "screenshot"})
    path = Path(str(shot["path"]))
    assert path.parent == tmp_path
    assert path.name.startswith("octop-") and path.suffix == ".png"
    # A chosen name is kept, never its directory.
    outside = tmp_path.parent / "elsewhere" / "login.png"
    assert (await forwarded_args({"action": "snapshot", "path": str(outside)}))["path"] == str(
        tmp_path / "login.png"
    )
    assert (
        Path(
            str((await forwarded_args({"action": "screenshot", "path": "notes.txt"}))["path"])
        ).parent
        == tmp_path
    )
    # Other actions keep their arguments.
    assert "path" not in await forwarded_args({"action": "navigate", "url": "https://x.test"})


@pytest.mark.asyncio
async def test_screenshot_path_is_left_alone_without_a_host_workspace(monkeypatch) -> None:
    monkeypatch.setattr(
        browser_profile,
        "get_config",
        lambda: {"configurable": {"user": "42"}},
    )
    handler = AsyncMock(return_value=object())
    request = _request("browser_use", {"action": "screenshot"})

    await browser_profile.BrowserProfileMiddleware("A").awrap_tool_call(request, handler)

    assert "path" not in handler.await_args.args[0].tool_call["args"]
