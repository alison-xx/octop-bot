"""Computer use on a Bot's cloud computer: scripts, coordinates, the accessibility list, the tool."""

from __future__ import annotations

import base64
from typing import Any

import pytest

from octop.infra.cloud.computers import computer_use as cu


def test_model_coordinates_scale_to_the_screen_and_stay_on_it() -> None:
    assert cu.to_screen(640, 360) == (960, 540)
    assert cu.to_screen(-5, 9999) == (0, 1079)


def test_keys_and_actions_become_pyautogui_calls() -> None:
    assert cu.parse_keys("Ctrl+Shift+T") == ["ctrl", "shift", "T"]
    assert cu.parse_keys("cmd+l") == ["ctrl", "l"]
    assert cu.parse_keys("Return") == ["enter"]
    common: dict[str, Any] = {
        "x2": None,
        "y2": None,
        "text": None,
        "keys": None,
        "direction": None,
        "amount": 5,
        "button": "left",
    }
    script = cu.action_script("double_click", x=100, y=200, **common)
    assert "pyautogui.click(150, 300, clicks=2" in script
    script = cu.action_script("scroll", x=10, y=10, **{**common, "direction": "down"})
    assert "pyautogui.scroll(-5)" in script
    with pytest.raises(ValueError):
        cu.action_script("click", x=None, y=None, **common)


def test_non_ascii_text_is_pasted_and_ascii_is_typed() -> None:
    assert "pyautogui.write" in cu.type_script("hello")
    pasted = cu.type_script("你好，云电脑")
    assert "xclip" in pasted and "pyautogui.press('v')" in pasted
    assert "keyDown('ctrl')" in pasted
    # The text travels JSON-quoted, so quotes in it cannot break the script.
    assert 'pyautogui.write("say \\"hi\\""' in cu.type_script('say "hi"')


XML = """<desktop-frame xmlns:st="https://accessibility.ubuntu.example.org/ns/state"
 xmlns:cp="https://accessibility.ubuntu.example.org/ns/component">
 <application name="gedit"><frame name="note.txt - gedit" st:showing="true" cp:screencoord="(90, 120)" cp:size="(900, 720)">
  <push-button name="Save" st:showing="true" cp:screencoord="(760, 135)" cp:size="(56, 34)"/>
  <push-button name="Hidden" st:showing="false" cp:screencoord="(0, 0)" cp:size="(10, 10)"/>
  <panel name="" st:showing="true" cp:screencoord="(0, 0)" cp:size="(1920, 1080)"/>
 </frame></application></desktop-frame>"""


def test_the_accessibility_tree_becomes_a_list_of_visible_controls() -> None:
    lines = cu.summarize_elements(XML).splitlines()
    assert "[push-button] 'Save' at (525, 101)" in lines
    assert not any("Hidden" in line for line in lines)
    assert not any(line.startswith("[panel]") for line in lines)
    assert "could not be read" in cu.summarize_elements("<broken")


class FakeDriver:
    def __init__(self) -> None:
        self.scripts: list[str] = []
        self.blank = 0

    def run_python(self, instance: str, code: str) -> str:
        self.scripts.append(code)
        if self.blank:
            self.blank -= 1
            return ""
        return "SNAPSHOT:" + base64.b64encode(b"jpeg-bytes").decode()


class FakeManager:
    def __init__(self) -> None:
        self.driver = FakeDriver()
        self.taken = False

    def taken_over(self, agent_id: str, user_id: int) -> bool:
        return self.taken

    def note(self, agent_id: str, kind: str) -> None:
        self.noted = kind

    def claim_screen(self, agent_id: str, holder: str) -> bool:
        return not getattr(self, "elsewhere", False)

    def use(self, agent_id: str, user_id: int, work: Any) -> Any:
        return work(self.driver, "ins-1")


def _call(tool: Any, **args: Any) -> Any:
    return tool.invoke({"type": "tool_call", "id": "c1", "name": "cloud_computer", "args": args})


def test_each_action_returns_the_screen_it_left(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = FakeManager()
    tool = cu.computer_use_tool(manager, "bot1", 7)  # type: ignore[arg-type]
    result = _call(tool, action="click", x=640, y=360)
    tool_message, picture = result.update["messages"]
    assert tool_message.tool_call_id == "c1" and "Did click" in tool_message.content
    image = [b for b in picture.content_blocks if b.get("type") == "image"][0]
    assert base64.b64decode(image["base64"]) == b"jpeg-bytes"
    # One request: the click and the snapshot in the same script.
    assert len(manager.driver.scripts) == 1
    assert "pyautogui.click(960, 540" in manager.driver.scripts[0]
    assert "SNAPSHOT" in manager.driver.scripts[0]


def test_a_desktop_still_drawing_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cu, "SNAPSHOT_RETRY_SECONDS", 0)
    manager = FakeManager()
    manager.driver.blank = 2
    result = _call(cu.computer_use_tool(manager, "bot1", 7), action="screenshot")  # type: ignore[arg-type]
    assert len(manager.driver.scripts) == 3
    assert result.update["messages"][0].content.startswith("Screenshot taken")


def test_a_taken_over_computer_turns_the_bot_away_and_bad_calls_explain_themselves() -> None:
    manager = FakeManager()
    tool = cu.computer_use_tool(manager, "bot1", 7)  # type: ignore[arg-type]
    manager.taken = True
    assert "taken over" in _call(tool, action="click", x=1, y=1).content
    assert manager.driver.scripts == []
    manager.taken = False
    assert "needs x and y" in _call(tool, action="click").content


def test_asking_for_a_takeover_pauses_and_hands_the_computer_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[Any] = []

    def fake_interrupt(payload: Any) -> Any:
        sent.append(payload)
        return {"decisions": [{"type": "respond", "message": "我完成了"}]}

    monkeypatch.setattr(cu, "interrupt", fake_interrupt)

    class Users:
        def get(self, user_id: int) -> Any:
            return type("Row", (), {"locale": "zh"})()

    class Takeover(FakeManager):
        def __init__(self) -> None:
            super().__init__()
            self.taken = True
            self.handed_back = False

        def set_takeover(self, agent_id: str, user_id: int, active: bool) -> None:
            self.taken = active
            self.handed_back = not active

    manager = Takeover()
    tool = cu.request_takeover_tool(manager, Users(), "bot1", 7)  # type: ignore[arg-type]
    result = tool.invoke({"reason": "登录招商银行网银"})
    request = sent[0]["action_requests"][0]
    assert request["name"] == "ask_user_question"
    assert request["args"]["cloud_computer"] == "bot1"
    question = request["args"]["questions"][0]
    assert "登录招商银行网银" in question["question"]
    assert [o["label"] for o in question["options"]] == ["我完成了", "我做不了"]
    assert manager.handed_back and "check that the step is really done" in result


def _jpeg(shade: int, *, dot: bool = False) -> bytes:
    import io

    from PIL import Image

    picture = Image.new("RGB", cu.VIEW, (shade, shade, shade))
    if dot:  # a clock-sized change: must not count as "the screen changed"
        picture.paste((255, 0, 0), (1200, 4, 1230, 14))
    out = io.BytesIO()
    picture.save(out, "JPEG", quality=70)
    return out.getvalue()


def test_the_same_call_over_and_over_is_refused() -> None:
    watch = cu.ScreenWatch()
    for _ in range(cu.MAX_REPEATS - 1):
        assert watch.before('["click", 1, 1]') is None
    assert "identical cloud_computer call" in (watch.before('["click", 1, 1]') or "")
    # Anything different starts over.
    assert watch.before('["click", 2, 1]') is None


def test_actions_that_leave_the_screen_alone_are_flagged_then_sent_to_the_user() -> None:
    watch = cu.ScreenWatch()
    assert watch.after("screenshot", _jpeg(40)) is None
    notes = [watch.after("click", _jpeg(40, dot=i % 2 == 0)) for i in range(cu.STUCK_HANDOFF)]
    assert notes[: cu.STUCK_NOTICE - 1] == [None] * (cu.STUCK_NOTICE - 1)
    assert "has not changed after your last 3 actions" in (notes[cu.STUCK_NOTICE - 1] or "")
    assert "request_takeover" in (notes[-1] or "") and "Stop now" in (notes[-1] or "")
    # A screenshot or wait is not expected to change anything; a real change resets the count.
    assert watch.after("wait", _jpeg(40)) is None
    assert watch.after("click", _jpeg(200)) is None
    assert watch.after("click", _jpeg(200)) is None


def test_a_computer_busy_in_another_conversation_is_left_alone() -> None:
    manager = FakeManager()
    manager.elsewhere = True  # type: ignore[attr-defined]
    result = _call(cu.computer_use_tool(manager, "bot1", 7), action="click", x=1, y=1)  # type: ignore[arg-type]
    assert "another conversation" in result.content
    assert manager.driver.scripts == []


def test_a_bot_stuck_on_one_screen_reads_a_note_with_the_screenshot() -> None:
    manager = FakeManager()
    manager.driver.run_python = lambda instance, code: (  # type: ignore[method-assign]
        "SNAPSHOT:" + base64.b64encode(_jpeg(90)).decode()
    )
    tool = cu.computer_use_tool(manager, "bot1", 7)  # type: ignore[arg-type]
    texts = [
        _call(tool, action="click", x=10 + i, y=10).update["messages"][0].content
        for i in range(cu.STUCK_NOTICE + 1)
    ]
    assert "has not changed" not in texts[cu.STUCK_NOTICE - 1]
    assert "has not changed after your last 3 actions" in texts[cu.STUCK_NOTICE]


def test_the_briefing_tells_the_bot_where_its_files_are_and_when_to_hand_over() -> None:
    from langchain_core.messages import SystemMessage

    class _Request:
        def __init__(self, system_message: SystemMessage | None) -> None:
            self.system_message = system_message

        def override(self, *, system_message: SystemMessage) -> _Request:
            return _Request(system_message)

    def texts(middleware: cu.ComputerBriefing, base: SystemMessage | None) -> str:
        seen = middleware.wrap_model_call(_Request(base), lambda r: r)  # type: ignore[arg-type,return-value]
        return "".join(b["text"] for b in seen.system_message.content_blocks)  # type: ignore[attr-defined]

    private = texts(cu.ComputerBriefing(), SystemMessage(content="You are Analyst."))
    assert private.startswith("You are Analyst.\n\n## Your cloud computer")
    assert "file tools run on this computer" in private
    assert "request_takeover" in private and "CAPTCHA" in private
    room = texts(cu.ComputerBriefing(room=True), None)
    assert room.startswith("## Your cloud computer")
    assert "group's shared files" in room


_TREE = (
    '<desktop xmlns:st="https://accessibility.ubuntu.example.org/ns/state" '
    'xmlns:cp="https://accessibility.ubuntu.example.org/ns/component">'
    '<panel name="form" st:showing="true" cp:screencoord="(0, 0)" cp:size="(1920, 1080)">'
    '<push-button name="发送" st:showing="true" cp:screencoord="(900, 600)" cp:size="(120, 40)"/>'
    '<push-button name="立即支付" st:showing="true" cp:screencoord="(1200, 600)" cp:size="(120, 40)"/>'
    '<push-button name="上一页" st:showing="true" cp:screencoord="(300, 600)" cp:size="(120, 40)"/>'
    "</panel></desktop>"
)


class _TreeDriver(FakeDriver):
    def accessibility(self, instance: str) -> str:
        return _TREE


def test_the_control_under_a_click_is_found_by_its_box() -> None:
    # (900..1020, 600..640) on screen is (600..680, 400..426.7) in the model's view.
    assert cu.control_at(_TREE, 640, 410) == "发送"
    assert cu.control_at(_TREE, 50, 50) is None


def test_a_click_on_send_asks_first_and_a_pay_button_is_never_clicked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from octop.infra.bot_tasks import approvals as ap

    answers = ["拒绝", "允许一次"]
    monkeypatch.setattr(
        ap, "interrupt", lambda payload: {"decisions": [{"message": answers.pop(0)}]}
    )

    class Settings:
        def get(self, key: str) -> None:
            return None

    class Users:
        def get(self, user_id: int) -> Any:
            return type("Row", (), {"locale": "zh"})()

    manager = FakeManager()
    manager.driver = _TreeDriver()
    tool = cu.computer_use_tool(
        manager,
        "bot1",
        7,
        approvals=ap.ApprovalRules(Settings()),
        user_repo=Users(),  # type: ignore[arg-type]
    )
    pay = _call(tool, action="click", x=840, y=410).content
    assert "spends money" in pay and "request_takeover" in pay
    assert _call(tool, action="click", x=640, y=410).content.startswith("The user said no")
    assert manager.driver.scripts == []  # nothing clicked so far
    clicked = _call(tool, action="click", x=640, y=410)
    assert "Did click" in clicked.update["messages"][0].content
    # An ordinary button needs no confirmation.
    assert "Did click" in _call(tool, action="click", x=240, y=410).update["messages"][0].content
