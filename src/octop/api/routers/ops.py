"""Cloud operations API, authenticated separately from user sessions."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import os
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from octop.api.common.client_ip import resolve_client_ip
from octop.api.deps import get_server
from octop.infra.cloud.ops import OpsLimitReached, OpsService
from octop.infra.desktop import bot_cloud_enabled


class OpsError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status, self.code, self.message = status, code, message


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _check_source(request: Request) -> None:
    allowed = os.environ.get("OCTOP_OPS_ALLOWED_IPS", "").strip()
    if allowed:
        try:
            address = ipaddress.ip_address(resolve_client_ip(request))
            networks = [
                ipaddress.ip_network(part.strip(), strict=False) for part in allowed.split(",")
            ]
            permitted = any(address in network for network in networks)
        except ValueError:
            permitted = False
        if not permitted:
            raise OpsError(403, "ops_ip_forbidden", "Client IP is not allowed")


def authenticate(request: Request) -> None:
    if not bot_cloud_enabled():
        raise OpsError(404, "ops_not_found", "Not found")
    # The source address first: callers outside the allowlist never get to try a key.
    _check_source(request)
    expected = os.environ.get("OCTOP_OPS_KEY_SHA256", "").strip().lower()
    if not expected:
        raise OpsError(503, "ops_unconfigured", "Operations API is not configured")
    key = request.headers.get("X-Octop-Ops-Key", "")
    if (
        len(expected) != 64
        or any(c not in "0123456789abcdef" for c in expected)
        or not key
        or not hmac.compare_digest(hashlib.sha256(key.encode()).hexdigest(), expected)
    ):
        raise OpsError(401, "ops_key_invalid", "Invalid operations key")


router = APIRouter(dependencies=[Depends(authenticate)])


class Operator(BaseModel):
    operatorId: str = Field(min_length=1, max_length=128)
    operatorName: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1000)


class DeleteRequest(Operator):
    confirm: str = Field(max_length=128)


def service(server: Any = Depends(get_server)) -> OpsService:
    return OpsService(server.services)


@router.get("/summary", summary="Summarize cloud operations")
async def summary(ops: OpsService = Depends(service)) -> dict[str, Any]:
    return await asyncio.to_thread(ops.summary)


@router.get("/users", summary="Read account statistics")
async def users(lynxceUserIds: str, ops: OpsService = Depends(service)) -> dict[str, Any]:
    ids = list(dict.fromkeys(lynxceUserIds.split(",")))
    if len(ids) > 100 or any(not value for value in ids):
        raise OpsError(400, "ops_invalid_request", "Provide between 1 and 100 user IDs")

    def collect() -> dict[str, Any]:
        accounts, records = ops.accounts(), ops.records()
        items = []
        for uid, account in accounts.items():
            if account in ids:
                item = ops.user(uid, account, records, accounts)
                item["bots"] = len(item["bots"])
                item["computers"] = len(item["computers"])
                items.append(item)
        return {"items": items}

    return await asyncio.to_thread(collect)


@router.get("/users/{lynxce_user_id}", summary="Read account details")
async def user(lynxce_user_id: str, ops: OpsService = Depends(service)) -> dict[str, Any]:
    def collect() -> dict[str, Any]:
        accounts = ops.accounts()
        for uid, account in accounts.items():
            if account == lynxce_user_id:
                return ops.user(uid, account, ops.records(), accounts)
        raise OpsError(404, "ops_user_not_found", "User not found")

    return await asyncio.to_thread(collect)


@router.get("/computers", summary="List cloud computers")
async def computers(
    status: str | None = None,
    reclaimState: str | None = None,
    lynxceUserId: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    ops: OpsService = Depends(service),
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            ops.listing, status, reclaimState, lynxceUserId, cursor, limit
        )
    except ValueError as exc:
        raise OpsError(400, "ops_invalid_request", "Invalid cursor") from exc


@router.post("/computers/{computer_id}/stop", summary="Stop a cloud computer")
async def stop(
    computer_id: str, body: Operator, ops: OpsService = Depends(service)
) -> dict[str, Any]:
    result = await asyncio.to_thread(ops.write, computer_id, body.model_dump(), delete=False)
    if result is None:
        raise OpsError(404, "ops_computer_not_found", "Computer not found")
    return result


@router.post("/computers/{computer_id}/delete-disk", summary="Reclaim a cloud computer")
async def delete_disk(
    computer_id: str, body: DeleteRequest, ops: OpsService = Depends(service)
) -> dict[str, Any]:
    if body.confirm != computer_id:
        raise OpsError(400, "ops_invalid_confirmation", "Confirmation does not match computer ID")
    try:
        result = await asyncio.to_thread(
            ops.write, computer_id, body.model_dump(exclude={"confirm"}), delete=True
        )
    except OpsLimitReached:
        raise OpsError(429, "ops_delete_limit", "Daily disk deletion limit reached") from None
    if result is None:
        raise OpsError(404, "ops_computer_not_found", "Computer not found")
    return result
