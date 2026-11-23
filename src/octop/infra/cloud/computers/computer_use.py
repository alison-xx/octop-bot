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
import time
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Annotated, Any, Literal

from langchain_core.messages import HumanMessage, ToolMessage, add_notification_metadata
from langchain_core.tools import InjectedToolCallId, StructuredTool
from langgraph.types import Command, interrupt
from octop_harness.builtin.tools.ask_user import ASK_USER_TOOL_NAME

from octop.i18n import tr
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
        "pyautogui.hotkey('ctrl', 'v')\n"
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
        return f"pyautogui.hotkey({names})\n"
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


def _pair(value: str | None) -> tuple[float, float] | None:
    if not value:
        return None
    try:
        a, b = value.strip("() ").split(",")
        return float(a), float(b)
    except ValueError:
        return None


def summarize_elements(xml: str, limit: int = MAX_ELEMENTS) -> str:
    """The accessibility tree as one line per visible control, centres in model coordinates."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return "The accessibility tree could not be read; take a screenshot instead."
    lines: list[str] = []
    seen: set[str] = set()
    for node in root.iter():
        if node.get(f"{{{_NS_STATE}}}showing") != "true":
            continue
        role = node.tag.rsplit("}", 1)[-1]
        name = (node.get("name") or "").strip()
        label = name or (node.text or "").strip()
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


def computer_use_tool(manager: ComputerManager, agent_id: str, user_id: int) -> StructuredTool:
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
        if manager.taken_over(agent_id, user_id):
            return TAKEN_OVER

        def work(driver: ComputerDriver, instance: str) -> Command[Any] | str:
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
                script += f"time.sleep({SETTLE_SECONDS})\n"
                done = f"Did {action}."
            image = snapshot(driver, instance, script)
            return _with_image(
                tool_call_id,
                done + " The screen (1280x720) is attached in the next message.",
                image,
                f"Cloud computer screen after {action}",
            )

        try:
            return manager.use(agent_id, user_id, work)
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
        return f"The user handed the computer back ({answer}). Take a screenshot and continue."

    return StructuredTool.from_function(
        func=request_takeover, name="request_takeover", description=HANDOFF_DESCRIPTION
    )
