"""Browser routers — env/install, octop-browser, record/replay, WS screencast."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from octop.api.common.bot_cloud import no_cloud_tenant_http
from octop.api.routers.browser.env import router as env_router
from octop.api.routers.browser.harness import router as harness_router
from octop.api.routers.browser.record_replay import router as record_replay_router
from octop.api.routers.browser.stream import router as stream_router
from octop.api.routers.browser.uninstall import router as uninstall_router

# Host-level operator features: not for cloud tenants.
router = APIRouter(dependencies=[Depends(no_cloud_tenant_http)])
router.include_router(env_router)
router.include_router(harness_router)
router.include_router(record_replay_router)
router.include_router(stream_router)
router.include_router(uninstall_router)

__all__ = ["router"]
