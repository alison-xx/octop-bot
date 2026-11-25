"""Bind a Bot web instance to the Lynxce account that first signed in.

The Bot web/NAS build has no local account to type: whoever proves a Lynxce
account first becomes the instance owner, and later sign-ins must prove the same
account. The binding keeps the verified account id and its public portrait, without a session token.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from octop.infra.db.repos.settings import SettingsRepo

OWNER_KEY = "octop_bot:lynxce_owner"
OWNER_USERNAME = "owner"


@dataclass(frozen=True)
class OwnerBinding:
    account_id: str
    user_id: int
    avatar_url: str | None = None


def owner_binding(settings: SettingsRepo) -> OwnerBinding | None:
    raw = settings.get(OWNER_KEY)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return OwnerBinding(str(data["account_id"]), int(data["user_id"]), data.get("avatar_url"))
    except (ValueError, KeyError, TypeError):
        return None


def bind_owner(
    settings: SettingsRepo, account_id: str, user_id: int, avatar_url: str | None = None
) -> None:
    # Existing releases match the final user_id field when deleting the owner.
    settings.set(
        OWNER_KEY,
        json.dumps({"account_id": account_id, "avatar_url": avatar_url, "user_id": user_id}),
    )


def forget_owner_for_user(settings: SettingsRepo, user_id: int) -> None:
    current = owner_binding(settings)
    if current is not None and current.user_id == user_id:
        settings.delete(OWNER_KEY)
