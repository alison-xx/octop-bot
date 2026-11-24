"""Which Lynxce account calls the desktop may make with its signed-in session."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from octop.infra.auth import lynxce_cloud
from octop.infra.errors import ErrorCode, OctopError


async def test_the_desktop_may_lift_its_own_keys_cap_but_not_bill_computers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lynxce_cloud, "bot_desktop_enabled", lambda: True)
    monkeypatch.setattr(lynxce_cloud, "bot_cloud_enabled", lambda: False)
    services = SimpleNamespace(
        paths=SimpleNamespace(root=tmp_path), secret_repo=SimpleNamespace(get=lambda key: None)
    )

    async def call(method: str, path: str) -> ErrorCode:
        with pytest.raises(OctopError) as refused:
            await lynxce_cloud.tenant_call(services, 1, method, path, {})  # type: ignore[arg-type]
        return refused.value.code

    # Allowed through to the session (none is stored here).
    assert (
        await call("PATCH", "/api/user/personal-api-keys/key-1")
        == ErrorCode.BOT_CLOUD_ACCOUNT_REQUIRED
    )
    assert await call("POST", "/api/billing/octop-bot/compute/reserve") == ErrorCode.FORBIDDEN
