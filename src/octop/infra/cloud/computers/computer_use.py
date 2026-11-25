"""Computer use on a Bot's cloud computer: look at the screen, point, click and type.

The model sees the desktop at 1280x720 (screenshots are scaled down to save tokens) and gives
coordinates in that space; they are scaled to the real 1920x1080 screen here. Each action runs a
short pyautogui script on the desktop and comes back with a fresh screenshot, attached as an
image the way ``read_file`` attaches one, so the model always sees what its action did. Older
screenshots are offloaded by the harness, so only the latest stays in context.

Text that is not plain ASCII is pasted through the desktop clipboard, so Chinese types
correctly whatever the keyboard layout. ``elements`` reads the accessibility tree instead of a
picture: cheaper, and exact about names and positions.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import math
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Annotated, Any, Literal

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
    ToolMessage,
    add_notification_metadata,
)
from langchain_core.tools import InjectedToolCallId, StructuredTool
from langgraph.config import get_config
from langgraph.errors import GraphBubbleUp
from langgraph.types import Command, interrupt
from octop_harness.builtin.tools.ask_user import ASK_USER_TOOL_NAME

from octop.i18n import tr
from octop.infra.bot_tasks.approvals import ApprovalRules, ask
from octop.infra.cloud.computers.backend import TAKEN_OVER
from octop.infra.utils.locale import resolve_user_locale

if TYPE_CHECKING:
    from octop.infra.cloud.computers.driver import ComputerDriver
    from octop.infra.cloud.computers.manager import ComputerManager

logger = logging.getLogger(__name__)

SCREEN = (1920, 1080)
VIEW = (1280, 720)
SCALE = SCREEN[0] / VIEW[0]
# Let the desktop catch up (menus open, pages paint) before the screenshot after an action.
SETTLE_SECONDS = 0.8
# Clicks and Enter often start a navigation: give the page time to change before the screenshot,
# or the model concludes its action "did not work" and repeats it.
NAVIGATION_SETTLE_SECONDS = 2.0
MAX_ELEMENTS = 150

Action = Literal[
    "screenshot",
    "click",
    "double_click",
    "right_click",
    "move",
    "drag",
    "scroll",
    "type",
    "key",
    "wait",
    "elements",
    "zoom",
]

_KEY_ALIASES = {
    "return": "enter",
    "esc": "escape",
    "control": "ctrl",
    "cmd": "ctrl",
    "command": "ctrl",
    "meta": "win",
    "super": "win",
    "option": "alt",
    "del": "delete",
    "pgup": "pageup",
    "pgdn": "pagedown",
    "arrowup": "up",
    "arrowdown": "down",
    "arrowleft": "left",
    "arrowright": "right",
    "spacebar": "space",
}

_INTERACTIVE = {
    "push-button",
    "toggle-button",
    "radio-button",
    "check-box",
    "combo-box",
    "entry",
    "password-text",
    "text",
    "link",
    "menu-item",
    "menu",
    "page-tab",
    "list-item",
    "table-cell",
    "tree-item",
    "icon",
    "spin-button",
    "slider",
}
_NS_STATE = "https://accessibility.ubuntu.example.org/ns/state"
_NS_COMPONENT = "https://accessibility.ubuntu.example.org/ns/component"

PRELUDE = "import pyautogui, subprocess, time\npyautogui.FAILSAFE = False\n"
# Appended to every action: the screen as the model sees it, made on the computer and printed
# as base64, so one request does the action and brings back a ~100 KB picture instead of the
# 1.7 MB PNG from /screenshot.
SNAPSHOT = (
    "import base64, io\n"
    f"_shot = pyautogui.screenshot().convert('RGB').resize(({VIEW[0]}, {VIEW[1]}))\n"
    "_buf = io.BytesIO()\n"
    "_shot.save(_buf, 'JPEG', quality=70)\n"
    "print('SNAPSHOT:' + base64.b64encode(_buf.getvalue()).decode())\n"
)
# A desktop that just started or resumed can take a few seconds to draw its first screen.
SNAPSHOT_RETRIES = 10
SNAPSHOT_RETRY_SECONDS = 2.0


def to_screen(x: float, y: float) -> tuple[int, int]:
    """Model coordinates (1280x720) → screen pixels, kept on the screen."""
    sx = min(max(round(x * SCALE), 0), SCREEN[0] - 1)
    sy = min(max(round(y * SCALE), 0), SCREEN[1] - 1)
    return sx, sy


def parse_keys(keys: str) -> list[str]:
    """``"ctrl+shift+t"`` → pyautogui key names."""
    out: list[str] = []
    for raw in keys.replace(" ", "").split("+"):
        if not raw:
            continue
        name = raw if len(raw) == 1 else raw.lower()
        out.append(_KEY_ALIASES.get(name, name))
    if not out:
        raise ValueError("keys is empty")
    return out


def type_script(text: str) -> str:
    """Type ASCII with the keyboard; paste anything else through the clipboard."""
    if text.isascii():
        return f"pyautogui.write({json.dumps(text)}, interval=0.01)\n"
    return (
        "subprocess.run(['xclip', '-selection', 'clipboard'], "
        f"input={json.dumps(text)}.encode(), stdout=subprocess.DEVNULL, "
        "stderr=subprocess.DEVNULL, check=True)\n"
        "time.sleep(0.2)\n"
        # Chrome misses a Ctrl+V pressed in one go (gedit does not): hold Ctrl a moment.
        "pyautogui.keyDown('ctrl'); time.sleep(0.1); pyautogui.press('v'); "
        "time.sleep(0.1); pyautogui.keyUp('ctrl')\n"
    )


def action_script(  # noqa: PLR0911 - one branch per action
    action: str,
    *,
    x: float | None,
    y: float | None,
    x2: float | None,
    y2: float | None,
    text: str | None,
    keys: str | None,
    direction: str | None,
    amount: int,
    button: str,
) -> str:
    """The pyautogui script for one input action (coordinates already in model space)."""

    def point(px: float | None, py: float | None, what: str) -> tuple[int, int]:
        if px is None or py is None:
            raise ValueError(f"{action} needs {what}")
        return to_screen(px, py)

    if action in ("click", "double_click", "right_click"):
        sx, sy = point(x, y, "x and y")
        clicks = 2 if action == "double_click" else 1
        which = "right" if action == "right_click" else button
        return f"pyautogui.click({sx}, {sy}, clicks={clicks}, button={json.dumps(which)})\n"
    if action == "move":
        sx, sy = point(x, y, "x and y")
        return f"pyautogui.moveTo({sx}, {sy})\n"
    if action == "drag":
        sx, sy = point(x, y, "x and y (start)")
        ex, ey = point(x2, y2, "x2 and y2 (end)")
        return (
            f"pyautogui.moveTo({sx}, {sy})\n"
            f"pyautogui.dragTo({ex}, {ey}, duration=0.6, button={json.dumps(button)})\n"
        )
    if action == "scroll":
        sx, sy = point(x, y, "x and y")
        step = max(1, min(int(amount), 30))
        move = f"pyautogui.moveTo({sx}, {sy})\n"
        if direction in ("left", "right"):
            return move + f"pyautogui.hscroll({step if direction == 'right' else -step})\n"
        return move + f"pyautogui.scroll({-step if direction == 'down' else step})\n"
    if action == "type":
        if not text:
            raise ValueError("type needs text")
        return type_script(text)
    if action == "key":
        if not keys:
            raise ValueError("key needs keys, e.g. 'enter' or 'ctrl+l'")
        names = ", ".join(json.dumps(k) for k in parse_keys(keys))
        return f"pyautogui.hotkey({names}, interval=0.05)\n"
    raise ValueError(f"unknown action {action!r}")


def view_image(png: bytes) -> bytes:
    """The screenshot as the model sees it: 1280x720 JPEG."""
    from PIL import Image  # noqa: PLC0415

    with Image.open(io.BytesIO(png)) as image:
        small = image.convert("RGB").resize(VIEW, Image.Resampling.LANCZOS)
    out = io.BytesIO()
    small.save(out, "JPEG", quality=70)
    return out.getvalue()


def zoom_image(png: bytes, region: tuple[float, float, float, float]) -> bytes:
    """A region (model coordinates) at full resolution, at most 1280 wide."""
    from PIL import Image  # noqa: PLC0415

    left, top = to_screen(min(region[0], region[2]), min(region[1], region[3]))
    right, bottom = to_screen(max(region[0], region[2]), max(region[1], region[3]))
    if right - left < 4 or bottom - top < 4:
        raise ValueError("zoom region is too small")
    with Image.open(io.BytesIO(png)) as image:
        crop = image.convert("RGB").crop((left, top, right + 1, bottom + 1))
    if crop.width > VIEW[0]:
        crop = crop.resize((VIEW[0], round(crop.height * VIEW[0] / crop.width)))
    out = io.BytesIO()
    crop.save(out, "JPEG", quality=80)
    return out.getvalue()


def snapshot(driver: ComputerDriver, instance: str, script: str = "") -> bytes:
    """Run ``script`` (an action, maybe none) and return the screen as the model sees it."""
    output = driver.run_python(instance, PRELUDE + script + SNAPSHOT)
    for attempt in range(SNAPSHOT_RETRIES):
        for line in output.splitlines():
            if line.startswith("SNAPSHOT:"):
                return base64.b64decode(line[len("SNAPSHOT:") :])
        if attempt + 1 < SNAPSHOT_RETRIES:
            time.sleep(SNAPSHOT_RETRY_SECONDS)
            try:
                output = driver.run_python(instance, PRELUDE + SNAPSHOT)
            except RuntimeError:
                output = ""
    # No picture from the desktop side (e.g. no Pillow there): fall back to the full PNG.
    return view_image(driver.screenshot(instance))


# Actions meant to change the screen; a screenshot, wait or zoom is not expected to.
_CHANGING = frozenset({"click", "double_click", "right_click", "drag", "scroll", "type", "key"})
# The same call this many times in a row is refused: the model is going round in circles.
MAX_REPEATS = 5
# After this many changing actions that left the screen as it was, tell the model it is stuck;
# after STUCK_HANDOFF of them, tell it to stop and ask the user.
STUCK_NOTICE = 3
STUCK_HANDOFF = 5
# Mean per-pixel difference (0-255) of a 32x18 grey thumbnail below which two screens are the
# same picture; the clock in the top bar alone stays well under it.
SAME_SCREEN = 2.0

REPEATED = (
    "Refused: this is the {count}th identical cloud_computer call in a row. It is not working; "
    "do something different (read `elements`, use the keyboard or a shell command), or call "
    "`request_takeover` if a person is needed."
)
STUCK = (
    "Note: the screen has not changed after your last {count} actions. Stop repeating them: "
    "read `elements`, try another way (keyboard, a shell command), or call `request_takeover` "
    "if a person is needed."
)
STUCK_STOP = (
    "Note: the screen has not changed after your last {count} actions. Stop now: call "
    "`request_takeover` with what is blocking you, or tell the user you are stuck and why."
)


def screen_signature(image: bytes) -> bytes:
    """A 32x18 grey thumbnail: cheap to compare, blind to tiny changes like the clock."""
    from PIL import Image  # noqa: PLC0415

    with Image.open(io.BytesIO(image)) as picture:
        return picture.convert("L").resize((32, 18), Image.Resampling.BOX).tobytes()


def same_screen(a: bytes, b: bytes) -> bool:
    return len(a) == len(b) and sum(abs(x - y) for x, y in zip(a, b, strict=True)) / len(a) < (
        SAME_SCREEN
    )


class ScreenWatch:
    """Notices a Bot going round in circles on its screen, without calling a model.

    Same call over and over: refused at the MAX_REPEATS-th. Actions that should change the
    screen but leave it as it was: a note on the result after STUCK_NOTICE of them, and a
    firmer one (ask the user) from STUCK_HANDOFF.
    """

    def __init__(self) -> None:
        self._last_call: str | None = None
        self._repeats = 0
        self._screen: bytes | None = None
        self._unchanged = 0

    def before(self, call: str) -> str | None:
        """Refusal text when ``call`` repeats the previous one too often, else None."""
        self._repeats = self._repeats + 1 if call == self._last_call else 1
        self._last_call = call
        if self._repeats >= MAX_REPEATS:
            return REPEATED.format(count=self._repeats)
        return None

    def after(self, action: str, image: bytes) -> str | None:
        """A note for the model when its actions stopped changing the screen."""
        try:
            signature = screen_signature(image)
        except Exception:  # noqa: BLE001 - an odd picture is no reason to fail the action
            return None
        previous, self._screen = self._screen, signature
        if action not in _CHANGING:
            return None
        if previous is None or not same_screen(previous, signature):
            self._unchanged = 0
            return None
        self._unchanged += 1
        if self._unchanged >= STUCK_HANDOFF:
            return STUCK_STOP.format(count=self._unchanged)
        if self._unchanged >= STUCK_NOTICE:
            return STUCK.format(count=self._unchanged)
        return None


def _thread_id() -> str:
    try:
        return str((get_config().get("configurable") or {}).get("thread_id") or "")
    except RuntimeError:  # called outside a graph run (tests, scripts)
        return ""


# Buttons whose click has consequences outside the computer: asked first.
CONSEQUENTIAL = re.compile(
    r"^\s*(发送|回复|提交|确认提交|发布|分享到|删除|永久删除|清空|"
    r"send\b|reply\b|submit\b|publish\b|post\b|share\b|delete\b|remove\b)",
    re.IGNORECASE,
)
# Buttons that spend money: never clicked by the Bot.
PAYS = re.compile(
    r"^\s*(支付|付款|立即支付|确认支付|购买|立即购买|下单|提交订单|结算|"
    r"pay\b|buy\b|purchase\b|place order\b|checkout\b|check out\b)",
    re.IGNORECASE,
)
PAY_REFUSED = (
    "Not clicked: {name!r} spends money. Leave the screen on this step and call "
    "request_takeover so the user confirms the payment themselves."
)


def control_at(xml: str, x: float, y: float) -> str | None:
    """Name of the smallest visible control under (x, y) in model coordinates, if any."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    sx, sy = x * SCALE, y * SCALE
    best: tuple[float, str] | None = None
    for node in root.iter():
        if node.get(f"{{{_NS_STATE}}}showing") != "true":
            continue
        role = node.tag.rsplit("}", 1)[-1]
        name = (node.get("name") or node.text or "").strip()
        if role == "password-text" or role not in _INTERACTIVE or not name:
            continue
        origin = _pair(node.get(f"{{{_NS_COMPONENT}}}screencoord"))
        size = _pair(node.get(f"{{{_NS_COMPONENT}}}size"))
        if origin is None or size is None or size[0] <= 0 or size[1] <= 0:
            continue
        if origin[0] <= sx <= origin[0] + size[0] and origin[1] <= sy <= origin[1] + size[1]:
            area = size[0] * size[1]
            if best is None or area < best[0]:
                best = (area, name)
    return best[1] if best else None


BUSY_ELSEWHERE = (
    "This cloud computer is being used by another conversation of this Bot right now. Do not "
    "use its screen here; wait a couple of minutes and try again, or tell the user."
)


def _pair(value: str | None) -> tuple[float, float] | None:
    if not value:
        return None
    try:
        a, b = value.strip("() ").split(",")
        return float(a), float(b)
    except ValueError:
        return None


def _control_attr(node: ET.Element, key: str) -> str | None:
    # AGS images use different namespace URIs for the same AT-SPI attributes.
    return next((v for k, v in node.attrib.items() if k.rsplit("}", 1)[-1] == key), None)


def _screen_bounds(node: ET.Element) -> tuple[float, float, float, float] | None:
    origin = _pair(_control_attr(node, "screencoord"))
    size = _pair(_control_attr(node, "size"))
    if not origin or not size or min(size) <= 0 or not all(map(math.isfinite, (*origin, *size))):
        return None
    x, y = origin
    right, bottom = x + size[0], y + size[1]
    if not math.isfinite(right) or not math.isfinite(bottom):
        return None
    if right <= 0 or bottom <= 0 or x >= SCREEN[0] or y >= SCREEN[1]:
        return None
    return x, y, right, bottom


def _password_boxes(xml: str) -> list[tuple[float, float, float, float]]:
    root = ET.fromstring(xml)
    containers = {
        "alert",
        "dialog",
        "application",
        "desktop",
        "desktop-frame",
        "frame",
        "panel",
        "root-pane",
        "window",
    }
    windows = [
        node
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1] in {"frame", "dialog", "window", "alert"}
        and _control_attr(node, "showing") == "true"
    ]
    foreground_verified = False
    for window in windows:
        controls = [
            node
            for node in window.iter()
            if node is not window
            and not len(node)
            and node.tag.rsplit("}", 1)[-1] not in containers
            and _control_attr(node, "showing") == "true"
            and _screen_bounds(node) is not None
        ]
        if not controls:
            raise ValueError("A visible window has no verifiable controls.")
        if _control_attr(window, "active") == "true" or any(
            _control_attr(node, "focused") == "true" for node in controls
        ):
            foreground_verified = True
    if not foreground_verified:
        raise ValueError("The foreground window could not be verified.")
    boxes = []
    for node in root.iter():
        if (
            node.tag.rsplit("}", 1)[-1] != "password-text"
            or _control_attr(node, "showing") == "false"
        ):
            continue
        bounds = _screen_bounds(node)
        if bounds is None:
            raise ValueError("Password control has no usable bounds.")
        boxes.append(bounds)
    return boxes


def handback_view(driver: ComputerDriver, instance: str) -> tuple[bytes, bool]:
    """Withhold unstable frames; mask a verified, stable layout before resizing."""
    from PIL import Image, ImageDraw

    before = driver.accessibility(instance)
    boxes = _password_boxes(before)
    picture = driver.screenshot(instance)
    if driver.accessibility(instance) != before:
        raise ValueError("The desktop tree changed during capture.")

    with Image.open(io.BytesIO(picture)) as source:
        image = source.convert("RGB")
    if image.size != SCREEN:
        raise ValueError("Unknown handback screen geometry.")
    draw = ImageDraw.Draw(image)
    for x, y, right, bottom in boxes:
        draw.rectangle(
            (math.floor(x) - 2, math.floor(y) - 2, math.ceil(right) + 2, math.ceil(bottom) + 2),
            fill="black",
        )
    out = io.BytesIO()
    image.resize(VIEW, Image.Resampling.LANCZOS).save(out, "JPEG", quality=70)
    return out.getvalue(), not boxes


def summarize_elements(xml: str, limit: int = MAX_ELEMENTS) -> str:
    """The accessibility tree as one line per visible control, centres in model coordinates."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return "The accessibility tree could not be read; take a screenshot instead."
    lines: list[str] = []
    seen: set[str] = set()
    for field in root.iter():
        if field.tag.rsplit("}", 1)[-1] == "password-text":
            field[:] = []
    for node in root.iter():
        if node.get(f"{{{_NS_STATE}}}showing") != "true":
            continue
        role = node.tag.rsplit("}", 1)[-1]
        name = (node.get("name") or "").strip()
        label = "[redacted]" if role == "password-text" else name or (node.text or "").strip()
        if not label and role not in _INTERACTIVE:
            continue
        if not label and role in ("text", "panel"):
            continue
        origin = _pair(node.get(f"{{{_NS_COMPONENT}}}screencoord"))
        size = _pair(node.get(f"{{{_NS_COMPONENT}}}size"))
        if origin is None or size is None or size[0] <= 0 or size[1] <= 0:
            continue
        cx, cy = (origin[0] + size[0] / 2) / SCALE, (origin[1] + size[1] / 2) / SCALE
        if not (0 <= cx < VIEW[0] and 0 <= cy < VIEW[1]):
            continue
        line = f"[{role}] {label[:80]!r} at ({round(cx)}, {round(cy)})"
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
        if len(lines) >= limit:
            lines.append(f"… more controls not shown (first {limit}).")
            break
    return "\n".join(lines) if lines else "No visible controls found; take a screenshot."


def _with_image(tool_call_id: str, text: str, image: bytes, caption: str) -> Command[Any]:
    """Tool result plus the picture in a follow-up message (tool messages carry no images)."""
    block = {
        "type": "image",
        "base64": base64.b64encode(image).decode("ascii"),
        "mime_type": "image/jpeg",
    }
    picture = add_notification_metadata(
        HumanMessage(content_blocks=[{"type": "text", "text": caption}, block]),  # type: ignore[list-item]
        source="cloud_computer",
    )
    return Command(
        update={
            "messages": [
                ToolMessage(content=text, name="cloud_computer", tool_call_id=tool_call_id),
                picture,
            ]
        }
    )


DESCRIPTION = """Use this Bot's own cloud computer (Ubuntu desktop with Chrome, terminal, \
LibreOffice) by looking at its screen and using the mouse and keyboard.

Coordinates are in a 1280x720 view of the screen. Start with `screenshot` (or `elements` for a \
cheap list of visible controls with their centre points), then act; every action returns a new \
screenshot so you can check the result before the next step.

Actions: screenshot; click / double_click / right_click / move (x, y); drag (x, y → x2, y2); \
scroll (x, y, direction up|down|left|right, amount); type (text; any language, including \
Chinese); key (keys, e.g. "enter", "ctrl+l", "ctrl+shift+t"); wait (seconds, up to 10); \
elements; zoom (x, y, x2, y2: a region at full resolution, to read small text).

Prefer shell commands and file tools on this computer when they can do the job: they are \
faster and cheaper than clicking. Never type passwords, verification codes or payment details \
yourself: when a site asks for them, leave the screen on that step and call \
`request_takeover`."""


def computer_use_tool(
    manager: ComputerManager,
    agent_id: str,
    user_id: int,
    *,
    approvals: ApprovalRules | None = None,
    user_repo: Any = None,
    remote_action: Callable[[str, dict[str, Any]], tuple[str, str, bytes | None]] | None = None,
) -> StructuredTool:
    watches: dict[str, ScreenWatch] = {}

    def guard_click(driver: ComputerDriver, instance: str, x: float, y: float) -> str | None:
        """Refusal text when the click would pay, or the user said no to a consequential one."""
        try:
            xml = driver.accessibility(instance)
        except Exception:  # noqa: BLE001 - no tree, no check: the click goes ahead as before
            logger.debug("accessibility read before click failed for %s", agent_id, exc_info=True)
            return None
        name = control_at(xml, x, y)
        if not name:
            return None
        if PAYS.match(name):
            return PAY_REFUSED.format(name=name)
        if approvals is None or not CONSEQUENTIAL.match(name):
            return None
        allowed, note = ask(
            rules=approvals,
            user_repo=user_repo,
            agent_id=agent_id,
            user_id=user_id,
            category="click",
            target=name[:80],
            detail="",
            offer_always=False,
        )
        return None if allowed else note

    def act(
        action: Action,
        tool_call_id: Annotated[str, InjectedToolCallId],
        x: float | None = None,
        y: float | None = None,
        x2: float | None = None,
        y2: float | None = None,
        text: str | None = None,
        keys: str | None = None,
        direction: Literal["up", "down", "left", "right"] | None = None,
        amount: int = 5,
        button: Literal["left", "middle", "right"] = "left",
        seconds: float = 1.0,
    ) -> Command[Any] | str:
        if remote_action is None and manager.taken_over(agent_id, user_id):
            return TAKEN_OVER
        # One conversation at a time drives the screen (a private chat and a group can both
        # reach this Bot's computer).
        thread = _thread_id()
        if not manager.claim_screen(agent_id, thread):
            return BUSY_ELSEWHERE
        if thread not in watches and len(watches) >= 64:
            watches.clear()
        watch = watches.setdefault(thread, ScreenWatch())
        refused = watch.before(
            json.dumps(
                [action, x, y, x2, y2, text, keys, direction, amount, button, seconds],
                ensure_ascii=False,
            )
        )
        if refused:
            return refused

        if remote_action is not None:
            # A desktop Bot sends one structured action. Only the cloud can inspect the
            # handback frame and execute the action under the same device lock.
            params = {
                "action": action,
                "x": x,
                "y": y,
                "x2": x2,
                "y2": y2,
                "text": text,
                "keys": keys,
                "direction": direction,
                "amount": amount,
                "button": button,
                "seconds": seconds,
            }
            status, note, image = remote_action(
                thread, {k: v for k, v in params.items() if v is not None}
            )
            if status == "handback":
                note = f"Requested action was not performed. {note}"
                if image is None:
                    return note
                return _with_image(
                    tool_call_id,
                    note,
                    image,
                    "Screen after handback",
                )
            if image is None:
                return note
            stuck = watch.after(action, image)
            return _with_image(
                tool_call_id,
                f"{note} {stuck}" if stuck else note,
                image,
                f"Cloud computer screen after {action}",
            )

        def work(driver: ComputerDriver, instance: str) -> Command[Any] | str:
            if action in ("click", "double_click") and x is not None and y is not None:
                refused = guard_click(driver, instance, float(x), float(y))
                if refused:
                    return refused
            manager.note(agent_id, action)
            if action == "elements":
                return summarize_elements(driver.accessibility(instance))
            if action == "zoom":
                if None in (x, y, x2, y2):
                    raise ValueError("zoom needs x, y, x2 and y2")
                region = (float(x or 0), float(y or 0), float(x2 or 0), float(y2 or 0))
                image = zoom_image(driver.screenshot(instance), region)
                return _with_image(tool_call_id, "Zoomed region attached.", image, "Zoomed region")
            script = ""
            if action == "wait":
                time.sleep(max(0.0, min(float(seconds), 10.0)))
                done = f"Waited {min(float(seconds), 10.0):g}s."
            elif action == "screenshot":
                done = "Screenshot taken."
            else:
                script = action_script(
                    action,
                    x=x,
                    y=y,
                    x2=x2,
                    y2=y2,
                    text=text,
                    keys=keys,
                    direction=direction,
                    amount=amount,
                    button=button,
                )
                navigates = action in ("click", "double_click") or (
                    action == "key" and "enter" in parse_keys(keys or "x")
                )
                settle = NAVIGATION_SETTLE_SECONDS if navigates else SETTLE_SECONDS
                script += f"time.sleep({settle})\n"
                done = f"Did {action}."
            image = snapshot(driver, instance, script)
            stuck = watch.after(action, image)
            if stuck:
                done = f"{done} {stuck}"
            return _with_image(
                tool_call_id,
                done + " The screen (1280x720) is attached in the next message.",
                image,
                f"Cloud computer screen after {action}",
            )

        def review(driver: ComputerDriver, instance: str) -> tuple[Command[Any] | str, bool]:
            try:
                image, clear = handback_view(driver, instance)
            except Exception:  # the driver may include sensitive text in errors
                return (
                    "The handback screen could not be checked privately. Ask the user to verify the desktop before continuing.",
                    False,
                )
            note = "Handback screenshot checked. Inspect the attached screen before continuing."
            if not clear:
                note = "Password fields are covered. Ask the user to finish or dismiss the form."
            return _with_image(tool_call_id, note, image, "Screen after handback"), clear

        try:
            return manager.model_screen(agent_id, user_id, TAKEN_OVER, work, review)
        except GraphBubbleUp:
            raise
        except ValueError as exc:
            return f"Invalid cloud_computer call: {exc}"
        except Exception as exc:  # noqa: BLE001 - the model reads the failure and adapts
            logger.warning(
                "cloud computer action %s failed for %s", action, agent_id, exc_info=True
            )
            return f"The cloud computer action failed: {exc}"

    return StructuredTool.from_function(func=act, name="cloud_computer", description=DESCRIPTION)


HANDOFF_DESCRIPTION = """Ask the user to take over this Bot's cloud computer for a step only a person may do: signing in, a password or verification code, a CAPTCHA, a QR scan, a payment or a confirmation that needs their judgement. Leave the screen on that step first. The turn waits until the user hands the computer back; then take a screenshot and continue."""


def request_takeover_tool(
    manager: ComputerManager, user_repo: Any, agent_id: str, user_id: int
) -> StructuredTool:
    def request_takeover(reason: str) -> str:
        """``reason``: what the user needs to do, in their language, e.g. 'Sign in to the bank'."""
        locale = resolve_user_locale(user_repo=user_repo, user_id=user_id)
        done = tr("octop_bot.computer_handoff.done", locale)
        cannot = tr("octop_bot.computer_handoff.cannot", locale)
        resumed = interrupt(
            {
                "action_requests": [
                    {
                        "name": ASK_USER_TOOL_NAME,
                        "description": tr("octop_bot.computer_handoff.title", locale),
                        "args": {
                            "questions": [
                                {
                                    "question": tr(
                                        "octop_bot.computer_handoff.question",
                                        locale,
                                        reason=reason.strip()[:300],
                                    ),
                                    "header": tr("octop_bot.computer_handoff.header", locale),
                                    "options": [{"label": done}, {"label": cannot}],
                                    "multiSelect": False,
                                }
                            ],
                            # Clients show a button that opens this computer, taken over.
                            "cloud_computer": agent_id,
                        },
                    }
                ],
                "review_configs": [
                    {"action_name": ASK_USER_TOOL_NAME, "allowed_decisions": ["respond"]}
                ],
            }
        )
        decisions = resumed.get("decisions", []) if isinstance(resumed, dict) else []
        answer = str(decisions[0].get("message") or "") if decisions else ""
        # Answering hands the computer back, even if the screen was left open.
        if manager.taken_over(agent_id, user_id):
            manager.set_takeover(agent_id, user_id, False)
        if cannot in answer:
            return (
                f"The user could not do it ({answer}). Do not retry the same step; find "
                "another way or tell the user what is blocked."
            )
        return (
            f"The user handed the computer back ({answer}). Take a screenshot and check that "
            "the step is really done (for example, you are signed in) before going on. If it is "
            "not, say what you see and call request_takeover again; after two more tries, stop "
            "and tell the user what is blocking."
        )

    return StructuredTool.from_function(
        func=request_takeover, name="request_takeover", description=HANDOFF_DESCRIPTION
    )


BRIEFING = """## Your cloud computer
You have your own cloud computer: an Ubuntu desktop with Chrome, a terminal and LibreOffice. \
It starts the first time you use it (a few seconds) and pauses when idle. The user pays for \
its running time, so use it only when the task needs a machine.
- {files}
- Pick the cheapest way that works: answer directly or use connected apps and web tools; then \
shell commands and files; then the screen (`cloud_computer`: `elements` first, then click and \
type); last, the user.
- Never type passwords, verification codes, payment details or ID numbers, and do not try to \
get past a CAPTCHA. For a sign-in, two-factor code, QR scan, CAPTCHA, payment or identity check, \
leave the screen on that step and call `request_takeover` saying what the user must do. When \
they hand the computer back, take a screenshot and check that step is done before going on.
- Before anything with consequences outside the computer (sending a message or email, \
publishing, submitting, deleting or changing the user's data elsewhere, accepting terms), call \
`request_approval`. Buttons that send, submit, publish or delete are checked again when you \
click them; buttons that pay are never yours to click.
- This is not the user's own computer: it cannot see their local files or apps. If the task \
needs those, say so."""
_PRIVATE_FILES = "Your shell commands and file tools run on this computer."
_ROOM_FILES = (
    "In this group your file tools work on the group's shared files, not on the computer; "
    "reach the computer only through `cloud_computer`."
)


class ComputerBriefing(AgentMiddleware[Any, Any]):
    """Tells a cloud tenant's Bot what its computer is and when to hand over to the user.

    The text is fixed per agent, so it never breaks the prompt cache between turns.
    """

    def __init__(self, *, room: bool = False, desktop: bool = False) -> None:
        files = _ROOM_FILES if room else _PRIVATE_FILES
        if desktop:
            files = (
                "Your normal execute and file tools work in the local Bot workspace. "
                "Use cloud_computer_workspace for cloud commands and explicit file transfers."
            )
        self._text = BRIEFING.format(files=files)

    def _brief(self, request: ModelRequest[Any]) -> ModelRequest[Any]:
        blocks: list[Any] = (
            list(request.system_message.content_blocks) if request.system_message else []
        )
        blocks.append({"type": "text", "text": f"\n\n{self._text}" if blocks else self._text})
        return request.override(system_message=SystemMessage(content_blocks=blocks))

    def wrap_model_call(
        self, request: ModelRequest[Any], handler: Callable[[ModelRequest[Any]], ModelResponse[Any]]
    ) -> ModelResponse[Any]:
        return handler(self._brief(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        return await handler(self._brief(request))
