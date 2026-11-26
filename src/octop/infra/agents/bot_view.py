"""Render structured results in Octop chat, using its native approval channel for forms."""

from __future__ import annotations

import json
from typing import Annotated, Literal, Self

from langchain_core.tools import tool
from langgraph.config import get_config
from langgraph.types import interrupt
from octop_harness.builtin.tools.ask_user import ASK_USER_TOOL_NAME, AskQuestion
from pydantic import BaseModel, Field, FiniteFloat, StringConstraints, model_validator

Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
Cell = str | int | float | bool | None


class Metric(BaseModel):
    label: Label
    value: str | int | FiniteFloat
    unit: str = ""


class Metrics(BaseModel):
    kind: Literal["metrics"]
    title: Label
    metrics: list[Metric] = Field(min_length=1, max_length=30)


class Table(BaseModel):
    kind: Literal["table"]
    title: Label
    columns: list[Label] = Field(min_length=1, max_length=40)
    rows: list[list[Cell]] = Field(max_length=300)

    @model_validator(mode="after")
    def check_rows(self) -> Self:
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("Each table row needs one value per column.")
        return self


class Series(BaseModel):
    name: Label
    values: list[FiniteFloat] = Field(max_length=200)


class Chart(BaseModel):
    kind: Literal["chart"]
    title: Label
    chart_type: Literal["bar", "line"]
    labels: list[Label] = Field(min_length=1, max_length=200)
    series: list[Series] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def check_series(self) -> Self:
        if any(len(line.values) != len(self.labels) for line in self.series):
            raise ValueError("Each chart series needs one value per label.")
        return self


class Form(BaseModel):
    kind: Literal["form"]
    title: Label
    questions: list[AskQuestion] = Field(min_length=1, max_length=4)


class HtmlView(BaseModel):
    kind: Literal["html"]
    title: Label
    html: str = Field(
        max_length=100_000,
        description="Static sandboxed HTML. Scripts and external requests are disabled.",
    )


class Choice(BaseModel):
    label: Label
    value: str | int | FiniteFloat | bool


class Control(BaseModel):
    type: Literal["number", "slider", "choice", "toggle"]
    id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")]
    label: Label
    value: str | int | FiniteFloat | bool
    min: FiniteFloat | None = None
    max: FiniteFloat | None = None
    step: Annotated[FiniteFloat, Field(gt=0)] | None = None
    options: list[Choice] = Field(default_factory=list, max_length=60)


class Expression(BaseModel):
    expression: str = Field(alias="=", min_length=1, max_length=1000)


class ComputedMetric(BaseModel):
    label: Label
    value: Expression
    unit: str = ""


class Calculator(BaseModel):
    kind: Literal["calculator"]
    title: Label
    inputs: list[Control] = Field(min_length=1, max_length=32)
    let: dict[str, str] = Field(default_factory=dict, max_length=60)
    metrics: list[ComputedMetric] = Field(min_length=1, max_length=32)


@tool
def show_view(
    view: Annotated[
        Metrics | Table | Chart | Form | HtmlView | Calculator, Field(discriminator="kind")
    ],
) -> str:
    """Display metrics, tables, charts, forms, static HTML or an interactive calculator in Octop Bot chat.

    To preview a generated website, send the actual HTML file with send_file_to_user. Its
    attachment opens in the workspace HTML viewer with inline CSS and scripts. Do not replace
    the file with a preview description or a shortened recreation in this static view.
    Form questions collect actual answers from the user before the turn continues.
    """
    data = view.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(view, Form):
        config = get_config().get("configurable") or {}
        if not config.get("octop_bot_browser"):
            raise ValueError("Interactive forms require an Octop Bot chat.")
        resumed = interrupt(
            {
                "action_requests": [
                    {
                        "name": ASK_USER_TOOL_NAME,
                        "description": view.title,
                        "args": {"questions": data["questions"]},
                    }
                ],
                "review_configs": [
                    {"action_name": ASK_USER_TOOL_NAME, "allowed_decisions": ["respond"]}
                ],
            }
        )
        decisions = resumed.get("decisions", [])
        if not decisions or decisions[0].get("type") != "respond":
            raise ValueError("The form has no submitted response.")
        response = str(decisions[0].get("message") or "")
        # The native form labels each submitted answer; free-text replies are also supported.
        lines = response.splitlines()
        prefixes = [f"{q.header or q.question}: " for q in view.questions]
        if len(lines) == len(prefixes) and all(
            line.startswith(p) for line, p in zip(lines, prefixes, strict=True)
        ):
            data["answers"] = [
                line.removeprefix(p) for line, p in zip(lines, prefixes, strict=True)
            ]
        else:
            data["answers"] = [response]
    return json.dumps(
        {
            "octop_ui": {"renderer": "octop-bot-view", "version": 1},
            "data": data,
            "text": view.title,
        },
        ensure_ascii=False,
    )
