"""Ask the user before an action with consequences outside the Bot's own work.

``request_approval`` pauses the turn with a card: allow once, always allow, deny. "Always
allow" is remembered per Bot for that kind of action on that target (sending to this address,
publishing to this account). Three observed approvals and an explicit review enable a new rule. The card is the
question card every client already shows; ``args.approval`` lets the web draw it as an
approval card.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal
from zoneinfo import ZoneInfo

from langchain_core.tools import StructuredTool
from langgraph.config import get_config
from langgraph.func import task
from langgraph.types import interrupt
from octop_harness.builtin.tools.ask_user import ASK_USER_TOOL_NAME

from octop.i18n import tr
from octop.infra.utils.locale import resolve_user_locale

if TYPE_CHECKING:
    from octop.infra.db.repos.settings import SettingsRepo

Category = Literal[
    "send", "publish", "submit", "delete", "permissions", "production", "terms", "upload", "other"
]
CATEGORIES: tuple[str, ...] = (
    "send",
    "publish",
    "submit",
    "delete",
    "permissions",
    "production",
    "terms",
    "upload",
    "other",
    # Raised by cloud_computer before it clicks a button that sends, submits or deletes.
    "click",
    "budget",
)
MAX_RULES = 20
OBSERVATIONS = 3

DESCRIPTION = """Ask the user to confirm before an action with consequences outside your own \
work: sending a message, email or invitation (send), publishing (publish), submitting a form \
(submit), deleting or overwriting their data elsewhere (delete), changing permissions or \
security settings (permissions), changing a live system (production), accepting terms \
(terms), uploading their files to another site (upload). Not for payments: those are \
request_takeover.

target: exactly what it acts on (the address, the account, the page). detail: what will \
happen, in the user's language, with the content when it is short. irreversible: true when \
it cannot be undone. Do the action only if the answer allows it."""

APPROVED = "Approved{why}. Go ahead with exactly this action."
ALWAYS = " (always, for {category} to {target!r})"
BY_RULE = " (the user always allows {category} to {target!r})"
DENIED = (
    "The user said no{answer}. Do not do it and do not try another way to do the same thing; "
    "tell them what is left undone."
)


class ApprovalRules:
    """ "Always allow" decisions per Bot, kept in settings: (category, target) pairs."""

    def __init__(self, settings: SettingsRepo, *, timezone: str = "UTC") -> None:
        self._settings = settings
        self.timezone = timezone

    @staticmethod
    def _key(agent_id: str) -> str:
        return f"octop_bot:approval_rules:{agent_id}"

    @staticmethod
    def _items(raw: str | None) -> list[dict[str, Any]]:
        try:
            items = json.loads(raw) if raw else []
        except ValueError:
            return []
        return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []

    def lookup(self, agent_id: str, category: str, target: str) -> dict[str, Any] | None:
        items = self._items(self._settings.get(self._key(agent_id)))
        return next(
            (r for r in items if r.get("category") == category and r.get("target") == target), None
        )

    def update(
        self,
        agent_id: str,
        category: str,
        target: str,
        expected: dict[str, Any] | None,
        replacement: dict[str, Any] | None,
    ) -> bool:
        """Only change the version of this rule that the user saw on the card."""
        key = self._key(agent_id)
        while True:
            raw = self._settings.get_or_insert(key, "[]")
            items = self._items(raw)
            current = next(
                (r for r in items if r.get("category") == category and r.get("target") == target),
                None,
            )
            if current != expected:
                return False
            if current is not None:
                items.remove(current)
            if replacement is not None:
                if current is None and len(items) >= MAX_RULES:
                    return False
                items.append({"category": category, "target": target, **replacement})
            if self._settings.replace_if_current(key, raw, json.dumps(items, ensure_ascii=False)):
                return True


def _presented_rule(
    rules: ApprovalRules, agent_id: str, category: str, target: str
) -> dict[str, Any] | None:
    def read_rule() -> dict[str, Any] | None:
        return rules.lookup(agent_id, category, target)

    # A pending card must still consume its own answer if another conversation activates
    # the same rule. LangGraph reuses this checkpointed read when replaying the tool.
    try:
        config = get_config()
    except RuntimeError:
        return read_rule()
    if (config.get("metadata") or {}).get("langgraph_node"):
        return task(read_rule)().result()
    return read_rule()


def ask(
    *,
    rules: ApprovalRules,
    user_repo: Any,
    agent_id: str,
    user_id: int,
    category: str,
    target: str,
    detail: str,
    irreversible: bool = False,
    offer_always: bool = True,
) -> tuple[bool, str]:
    """Pause for the user's decision (unless a standing rule allows it): (allowed, note)."""
    category = category if category in CATEGORIES else "other"
    target = target.strip()
    offer_always = offer_always and bool(target) and len(target) <= 300
    rule = _presented_rule(rules, agent_id, category, target) if offer_always else None
    # Existing records predate observation and represent explicitly granted standing rules.
    if rule is not None and rule.get("state", "active") == "active":
        return True, APPROVED.format(why=BY_RULE.format(category=category, target=target))
    locale = resolve_user_locale(user_repo=user_repo, user_id=user_id)
    once = tr("octop_bot.approval.once", locale)
    always = tr("octop_bot.approval.always", locale)
    deny = tr("octop_bot.approval.deny", locale)
    question = tr(
        "octop_bot.approval.question",
        locale,
        action=tr(f"octop_bot.approval.category.{category}", locale),
        target=target[:300] or "-",
        detail=detail.strip()[:600],
    )
    if irreversible:
        question = f"{question}\n{tr('octop_bot.approval.irreversible', locale)}"
    records = list(rule.get("observations", [])) if rule else []
    ready = len(records) >= OBSERVATIONS
    if offer_always:
        if rule is None:
            question += "\n" + tr("octop_bot.approval.start_observing", locale)
        elif ready:
            question += "\n" + tr("octop_bot.approval.review_records", locale)
            question += "\n" + "\n".join(
                f"{index}. {datetime.fromtimestamp(entry, ZoneInfo(rules.timezone)):%Y-%m-%d %H:%M:%S %Z} · {once}"
                for index, entry in enumerate(records, 1)
            )
            always = tr("octop_bot.approval.activate", locale)
        else:
            question += "\n" + tr("octop_bot.approval.observing", locale, count=len(records) + 1)
    header = tr("octop_bot.approval.header", locale)
    options = [
        {"label": once},
        *([{"label": always}] if offer_always and (rule is None or ready) else []),
        {"label": deny},
    ]
    resumed = interrupt(
        {
            "action_requests": [
                {
                    "name": ASK_USER_TOOL_NAME,
                    "description": tr("octop_bot.approval.title", locale),
                    "args": {
                        "questions": [
                            {
                                "question": question,
                                "header": header,
                                "options": options,
                                "multiSelect": False,
                            }
                        ],
                        # The web draws this as an approval card (no default button).
                        "approval": {
                            "category": category,
                            "target": target[:300],
                            "irreversible": irreversible,
                        },
                    },
                }
            ],
            "review_configs": [
                {"action_name": ASK_USER_TOOL_NAME, "allowed_decisions": ["respond"]}
            ],
        }
    )
    decisions = resumed.get("decisions", []) if isinstance(resumed, dict) else []
    decision = decisions[0] if len(decisions) == 1 and isinstance(decisions[0], dict) else {}
    answer = (
        str(decision.get("message") or "").strip()
        if decision.get("type", "respond") == "respond"
        else ""
    )
    prefix = tr("slash.ask.answered_prefix", locale)

    def selected(label: str) -> bool:
        # The web sends the label, mobile includes the header and IM may add a localized prefix.
        return answer in {
            label,
            f"{header}: {label}",
            f"{prefix}{label}",
            f"{prefix.rstrip()}\n- {header}: {label}",
        }

    if offer_always and selected(always):
        if rule is None:
            saved = rules.update(
                agent_id,
                category,
                target,
                None,
                {"state": "observing", "observations": [], "at": time.time()},
            )
            why = (
                " (observation started; future matches still require confirmation)"
                if saved
                else " (one time only; the standing rule could not be saved)"
            )
            return True, APPROVED.format(why=why)
        if ready and rules.update(
            agent_id, category, target, rule, {"state": "active", "at": time.time()}
        ):
            return True, APPROVED.format(why=ALWAYS.format(category=category, target=target))
        if ready:
            return True, APPROVED.format(why="")
    if selected(once):
        if rule and not ready:
            updated = {**rule, "observations": [*records, time.time()]}
            rules.update(agent_id, category, target, rule, updated)
        return True, APPROVED.format(why="")
    if rule:
        rules.update(agent_id, category, target, rule, None)
    said = "" if (not answer or selected(deny)) else f" ({answer[:300]})"
    return False, DENIED.format(answer=said)


def request_approval_tool(
    rules: ApprovalRules, user_repo: Any, agent_id: str, user_id: int
) -> StructuredTool:
    def request_approval(
        category: Category,
        target: str,
        detail: str,
        irreversible: bool = False,
    ) -> str:
        _allowed, note = ask(
            rules=rules,
            user_repo=user_repo,
            agent_id=agent_id,
            user_id=user_id,
            category=category,
            target=target,
            detail=detail,
            irreversible=irreversible,
        )
        return note

    return StructuredTool.from_function(
        func=request_approval, name="request_approval", description=DESCRIPTION
    )
