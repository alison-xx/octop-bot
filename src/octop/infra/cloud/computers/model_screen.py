"""Structured desktop-model actions. The cloud decides what may leave the device lock."""

from __future__ import annotations

import base64
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from octop.infra.cloud.computers import computer_use as cu
from octop.infra.cloud.computers.backend import TAKEN_OVER
from octop.infra.cloud.computers.driver import ComputerDriver
from octop.infra.cloud.computers.manager import ComputerManager


class ModelScreenAction(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    thread_id: str = Field(
        min_length=1, max_length=256, description="Desktop conversation holding this screen."
    )
    action: cu.Action
    x: float | None = Field(None, ge=0, lt=1280)
    y: float | None = Field(None, ge=0, lt=720)
    x2: float | None = Field(None, ge=0, lt=1280)
    y2: float | None = Field(None, ge=0, lt=720)
    text: str | None = Field(None, min_length=1, max_length=4096)
    keys: str | None = Field(None, min_length=1, max_length=128)
    direction: Literal["up", "down", "left", "right"] | None = None
    amount: int = Field(5, ge=1, le=30)
    button: Literal["left", "middle", "right"] = "left"
    seconds: float = Field(1.0, ge=0, le=10)

    @model_validator(mode="after")
    def check_arguments(self) -> Self:
        if self.action in {
            "click",
            "double_click",
            "right_click",
            "move",
            "drag",
            "scroll",
            "zoom",
        } and (self.x is None or self.y is None):
            raise ValueError("The action requires x and y.")
        if self.action in {"drag", "zoom"} and (self.x2 is None or self.y2 is None):
            raise ValueError("The action requires x2 and y2.")
        if self.action == "type" and not self.text or self.action == "key" and not self.keys:
            raise ValueError("Typing requires text and a key action requires keys.")
        if self.action == "scroll" and not self.direction:
            raise ValueError("Scrolling requires a direction.")
        return self


class ModelScreenResult(BaseModel):
    status: Literal["ok", "taken_over", "busy", "handback", "withheld", "needs_human"]
    text: str
    image_base64: str | None = Field(
        default=None, description="Optional JPEG. A handback image replaces the requested action."
    )


def _image(status: Literal["ok", "handback"], note: str, data: bytes) -> ModelScreenResult:
    return ModelScreenResult(
        status=status, text=note, image_base64=base64.b64encode(data).decode("ascii")
    )


def perform_model_screen(
    manager: ComputerManager, agent_id: str, user_id: int, req: ModelScreenAction
) -> ModelScreenResult:
    busy = ModelScreenResult(status="busy", text=cu.BUSY_ELSEWHERE)
    taken = ModelScreenResult(status="taken_over", text=TAKEN_OVER)
    holder = "desktop:" + req.thread_id
    if manager.taken_over(agent_id, user_id):
        return taken
    if not manager.claim_screen(agent_id, holder):
        return busy

    def work(driver: ComputerDriver, instance: str) -> ModelScreenResult:
        if not manager.claim_screen(agent_id, holder):
            return busy
        if req.action in {"click", "double_click", "right_click"}:
            assert req.x is not None and req.y is not None
            try:
                target = cu.control_at(driver.accessibility(instance), req.x, req.y)
            except Exception:
                target = None
            if not target or cu.PAYS.match(target) or cu.CONSEQUENTIAL.match(target):
                return ModelScreenResult(
                    status="needs_human", text="Ask the user to take over and perform this click."
                )
        manager.note(agent_id, req.action)
        if req.action == "elements":
            return ModelScreenResult(
                status="ok", text=cu.summarize_elements(driver.accessibility(instance))
            )
        if req.action == "zoom":
            assert (
                req.x is not None
                and req.y is not None
                and req.x2 is not None
                and req.y2 is not None
            )
            image = cu.zoom_image(driver.screenshot(instance), (req.x, req.y, req.x2, req.y2))
            return _image("ok", "Zoomed region attached.", image)
        note, image = cu.capture_after_action(
            driver,
            instance,
            req.action,
            x=req.x,
            y=req.y,
            x2=req.x2,
            y2=req.y2,
            text=req.text,
            keys=req.keys,
            direction=req.direction,
            amount=req.amount,
            button=req.button,
            seconds=req.seconds,
        )
        return _image("ok", note, image)

    def review(driver: ComputerDriver, instance: str) -> tuple[ModelScreenResult, bool]:
        if not manager.claim_screen(agent_id, holder):
            return busy, False
        try:
            image, clear = cu.handback_view(driver, instance)
        except Exception:
            return ModelScreenResult(
                status="withheld",
                text="The handback screen could not be checked. Ask the user to verify the desktop.",
            ), False
        note = (
            "Handback checked. Inspect the image before continuing."
            if clear
            else "Password fields are covered. Ask the user to finish or dismiss the form."
        )
        return _image("handback", note, image), clear

    result = manager.model_screen(agent_id, user_id, TAKEN_OVER, work, review)
    return taken if isinstance(result, str) else result
