"""Ask the user before an action with consequences outside the Bot's own work.

``request_approval`` pauses the turn with a card: allow once, always allow, deny. "Always
allow" is remembered per Bot for that kind of action on that target (sending to this address,
publishing to this account), so the next time it goes ahead without asking. The card is the
question card every client already shows; ``args.approval`` lets the web draw it as an
approval card.
"""

from __future__ import annotations

import json
import threading
import time
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.tools import StructuredTool
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
)
MAX_RULES = 40

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

    def __init__(self, settings: SettingsRepo) -> None:
        self._settings = settings
        self._guard = threading.Lock()

    @staticmethod
    def _key(agent_id: str) -> str:
        return f"octop_bot:approval_rules:{agent_id}"

    def rules(self, agent_id: str) -> list[dict[str, Any]]:
        raw = self._settings.get(self._key(agent_id))
        try:
            items = json.loads(raw) if raw else []
        except ValueError:
            return []
        return [item for item in items if isinstance(item, dict)]

    def allows(self, agent_id: str, category: str, target: str) -> bool:
        wanted = target.strip().lower()
        return any(
            r.get("category") == category and str(r.get("target", "")).lower() == wanted
            for r in self.rules(agent_id)
        )

    def remember(self, agent_id: str, category: str, target: str) -> None:
        with self._guard:
            items = [
                r
                for r in self.rules(agent_id)
                if not (r.get("category") == category and r.get("target") == target.strip())
            ]
            items.append({"category": category, "target": target.strip()[:300], "at": time.time()})
            self._settings.set(
                self._key(agent_id), json.dumps(items[-MAX_RULES:], ensure_ascii=False)
            )


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
    target = target.strip()[:300]
    if offer_always and target and rules.allows(agent_id, category, target):
        return True, APPROVED.format(why=BY_RULE.format(category=category, target=target))
    locale = resolve_user_locale(user_repo=user_repo, user_id=user_id)
    once = tr("octop_bot.approval.once", locale)
    always = tr("octop_bot.approval.always", locale)
    deny = tr("octop_bot.approval.deny", locale)
    question = tr(
        "octop_bot.approval.question",
        locale,
        action=tr(f"octop_bot.approval.category.{category}", locale),
        target=target or "-",
        detail=detail.strip()[:600],
    )
    if irreversible:
        question = f"{question}\n{tr('octop_bot.approval.irreversible', locale)}"
    options = [
        {"label": once},
        *([{"label": always}] if offer_always and target else []),
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
                                "header": tr("octop_bot.approval.header", locale),
                                "options": options,
                                "multiSelect": False,
                            }
                        ],
                        # The web draws this as an approval card (no default button).
                        "approval": {
                            "category": category,
                            "target": target,
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
    answer = str(decisions[0].get("message") or "") if decisions else ""
    if always in answer:
        rules.remember(agent_id, category, target)
        return True, APPROVED.format(why=ALWAYS.format(category=category, target=target))
    if once in answer:
        return True, APPROVED.format(why="")
    # Anything else the user wrote (including "deny") is a no, with their words passed on.
    said = "" if (not answer or deny in answer) else f" ({answer.strip()[:300]})"
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
