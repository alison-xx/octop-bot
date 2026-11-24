"""Restricted operational projections of cloud accounts and computers."""

from __future__ import annotations

import base64
import json
import time
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from octop.infra.auth.lynxce_cloud import cloud_accounts
from octop.infra.cloud.computers.manager import (
    DISK_DAILY_CREDITS_PER_GB,
    ComputerRecord,
    beijing_day,
    computer_manager,
)
from octop.infra.cloud.computers.mixed import is_cvm_instance
from octop.infra.users.preferences import get_onboarding_completed_from_json

if TYPE_CHECKING:
    from octop.infra.db.services import SharedServices


def iso(value: float | int | None) -> str | None:
    return datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z") if value else None


class OpsService:
    def __init__(self, services: SharedServices) -> None:
        self.services = services
        self.manager = computer_manager(services)

    def accounts(self) -> dict[int, str]:
        return cloud_accounts(self.services)

    def records(self) -> list[ComputerRecord]:
        return [
            ComputerRecord.load(raw)
            for raw in self.services.settings_repo.with_prefix("octop_bot:computer:").values()
        ]

    def item(self, record: ComputerRecord, accounts: dict[int, str]) -> dict[str, Any]:
        manager = self.manager
        size, _ = manager.disk_status(record) if manager else (0, 0)
        _, state, deadline = manager.reclaim_status(record) if manager else (0, None, None)
        last = max(record.active_at or 0, record.started_at or 0, record.reclaim_seen_at or 0)
        idle = (
            (
                date.fromisoformat(beijing_day(time.time())) - date.fromisoformat(beijing_day(last))
            ).days
            if last
            else None
        )
        instance = record.instance_id
        provider = "cvm" if instance and is_cvm_instance(instance) else "ags"
        driver: Any = manager._driver if manager else None
        if driver and hasattr(type(driver), "_for") and instance:
            driver = driver._for(instance)
        config = getattr(driver, "_cvm_config", None) or getattr(driver, "_config", None)
        agent = self.services.agent_repo.get(record.agent_id)
        return {
            "computerId": record.agent_id,
            "botId": record.agent_id,
            "lynxceUserId": accounts.get(record.user_id),
            "spec": record.spec,
            "status": "running" if record.running else "stopped",
            "provider": provider,
            "instanceId": instance,
            "region": getattr(config, "region", None),
            "diskGb": size,
            "createdAt": iso(agent.created_at) if agent else None,
            "lastUsedAt": iso(last),
            "todaySeconds": None,
            "idleDays": max(0, idle) if idle is not None else None,
            "dailyDiskCredits": round(size * DISK_DAILY_CREDITS_PER_GB, 2),
            "reclaimState": state,
            "reclaimAt": iso(deadline),
        }

    def user(
        self, user_id: int, account: str, records: list[ComputerRecord], accounts: dict[int, str]
    ) -> dict[str, Any]:
        user = self.services.user_repo.get(user_id)
        assert user is not None
        agents = [a for a in self.services.agent_repo.list_by_user(user_id) if a.kind != "team"]
        own = [r for r in records if r.user_id == user_id and r.instance_id]
        market = self.services.settings_repo.with_prefix(f"octop_bot:market:{user_id}:")
        active = self.services.thread_repo.latest_activity_by_agent(
            user_id, [a.agent_id for a in agents]
        )
        latest = max([user.last_login_at or 0, *active.values()], default=0)
        return {
            "lynxceUserId": account,
            "lastActiveAt": iso(latest),
            "onboardingCompleted": get_onboarding_completed_from_json(user.preferences_json),
            "bots": [
                {
                    "botId": a.agent_id,
                    "name": a.name,
                    "marketTemplateId": json.loads(
                        market.get(f"octop_bot:market:{user_id}:{a.agent_id}", "{}")
                    ).get("slug"),
                    "createdAt": iso(a.created_at),
                    "hasComputer": any(r.agent_id == a.agent_id for r in own),
                }
                for a in agents
            ],
            "groups": len(self.services.repos.bot_group_repo.list_by_owner(user_id)),
            "computers": [self.item(r, accounts) for r in own],
        }

    def summary(self) -> dict[str, Any]:
        accounts = self.accounts()
        records = self.records()
        users = [self.user(uid, account, records, accounts) for uid, account in accounts.items()]
        computers = [c for u in users for c in u["computers"]]
        return {
            "generatedAt": iso(time.time()),
            "users": len(users),
            "bots": sum(len(u["bots"]) for u in users),
            "groups": sum(u["groups"] for u in users),
            "computers": {
                "total": len(computers),
                "running": sum(c["status"] == "running" for c in computers),
                "stopped": sum(c["status"] == "stopped" for c in computers),
                "pendingReclaim": sum(c["reclaimState"] == "pending_reclaim" for c in computers),
            },
        }

    def listing(
        self,
        status: str | None,
        reclaim: str | None,
        account: str | None,
        cursor: str | None,
        limit: int,
    ) -> dict[str, Any]:
        accounts = self.accounts()
        items = [
            self.item(r, accounts)
            for r in self.records()
            if r.instance_id and r.user_id in accounts
        ]
        items = [
            i
            for i in items
            if (not status or i["status"] == status)
            and (not reclaim or i["reclaimState"] == reclaim)
            and (not account or i["lynxceUserId"] == account)
        ]
        items.sort(key=lambda i: (i["lastUsedAt"] or "", i["computerId"]), reverse=True)
        if cursor:
            try:
                key = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
                if (
                    not isinstance(key, list)
                    or len(key) != 2
                    or not all(isinstance(v, str) for v in key)
                ):
                    raise ValueError
            except (ValueError, UnicodeError, TypeError) as exc:
                raise ValueError("Invalid cursor") from exc
            items = [i for i in items if (i["lastUsedAt"] or "", i["computerId"]) < tuple(key)]
        page = items[:limit]
        next_cursor = None
        if len(items) > limit:
            last = page[-1]
            next_cursor = base64.urlsafe_b64encode(
                json.dumps([last["lastUsedAt"] or "", last["computerId"]]).encode()
            ).decode()
        return {"items": page, "nextCursor": next_cursor}

    def write(
        self, computer_id: str, operator: dict[str, str], *, delete: bool
    ) -> dict[str, Any] | None:
        manager = self.manager
        if manager is None:
            return None
        tombstone = "octop_bot:ops:reclaimed:" + computer_id
        with manager._lock(computer_id):
            raw = self.services.settings_repo.get(manager._key(computer_id))
            record = ComputerRecord.load(raw) if raw else None
            saved = self.services.settings_repo.get(tombstone)
            if (record is None or not record.instance_id) and saved:
                item: dict[str, Any] = json.loads(saved)
            elif record is None or not record.instance_id:
                return None
            else:
                item = self.item(record, self.accounts())
                if delete:
                    manager._release(computer_id, record.user_id)
                    item.update(
                        status="stopped", reclaimState="reclaimed", reclaimAt=iso(time.time())
                    )
                    self.services.settings_repo.set(tombstone, json.dumps(item))
                else:
                    manager.pause(computer_id, record.user_id)
                    item = self.item(manager.record(computer_id, record.user_id), self.accounts())
            self.services.audit_repo.write(
                actor=operator["operatorId"],
                action="ops.delete_disk" if delete else "ops.stop",
                target=computer_id,
                payload=json.dumps(operator),
            )
            return item
