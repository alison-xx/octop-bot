"""Bounded pages of newline-delimited LangChain messages for desktop chat imports."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel, Field

from octop.infra.db.repos.settings import SettingsRepo
from octop.infra.errors import ErrorCode, OctopError

# The entire JSON envelope, including base64 overhead, fits the 10 MiB HTTP limit.
PAGE_BYTES = 2 * 1024 * 1024
MAX_MESSAGES = 5000
MAX_BYTES = 1024 * 1024 * 1024  # The existing per-account daily byte budget.


class WirePart(BaseModel):
    offset: int = Field(ge=0, description="UTF-8 byte offset in the source snapshot.")
    total: int = Field(ge=1, le=MAX_BYTES, description="Size of the complete snapshot in bytes.")
    snapshot: str = Field(
        pattern=r"^[0-9a-f]{64}$", description="SHA-256 of the complete NDJSON transcript."
    )
    data: str = Field(
        min_length=1,
        max_length=4 * ((PAGE_BYTES + 2) // 3),
        description="Base64 of this bounded byte page, which may cross message boundaries.",
    )


def message_wire(message: dict[str, Any]) -> bytes:
    return json.dumps(message, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def pages(messages: list[dict[str, Any]]) -> Iterator[bytes]:
    pending = bytearray()
    for msg in messages:
        wire = memoryview(message_wire(msg) + b"\n")
        while wire:
            segment = wire[: PAGE_BYTES - len(pending)]
            pending.extend(segment)
            wire = wire[len(segment) :]
            if len(pending) == PAGE_BYTES:
                yield bytes(pending)
                pending.clear()
    if pending:
        yield bytes(pending)


class InvalidUpload(ValueError):
    """The staged snapshot is incomplete or its contents no longer match its receipt."""


def read_batches(
    settings: SettingsRepo, prefix: str, page_count: int, snapshot: str, expected: int
) -> Iterator[list[dict[str, Any]]]:
    """Decode only complete UTF-8 records. The final digest covers every original byte."""
    digest = hashlib.sha256()
    pending = bytearray()
    count = 0
    batch: list[dict[str, Any]] = []
    batch_size = 0
    for index in range(page_count):
        value = settings.get(f"{prefix}:{index}")
        if value is None:
            raise InvalidUpload
        try:
            data = base64.b64decode(value, validate=True)
        except ValueError as exc:
            raise InvalidUpload from exc
        digest.update(data)
        segments = data.split(b"\n")
        for segment in segments[:-1]:
            pending.extend(segment)
            try:
                item = json.loads(pending)
            except (UnicodeError, ValueError):
                raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS, status=422) from None
            if not isinstance(item, dict) or count >= expected:
                raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS, status=422)
            count += 1
            if batch and (len(batch) >= 32 or batch_size + len(pending) > PAGE_BYTES):
                yield batch
                batch, batch_size = [], 0
            batch.append(item)
            batch_size += len(pending)
            pending.clear()
        pending.extend(segments[-1])
    if pending or count != expected or digest.hexdigest() != snapshot:
        raise InvalidUpload
    if batch:
        yield batch


def discard_upload(settings: SettingsRepo, key: str) -> None:
    prefix = key + ":parts"
    raw = settings.get(prefix)
    if raw:
        count = json.loads(raw)["pages"]
        settings.set_many({}, delete=[prefix, *(f"{prefix}:{i}" for i in range(count))])


def stage_page(settings: SettingsRepo, key: str, body: WirePart) -> tuple[int, int]:
    prefix = key + ":parts"
    header = body.model_dump(exclude={"data", "offset"})
    state = json.loads(settings.get(prefix) or "{}")
    previous_pages = 0
    if state.get("header") != header:
        if body.offset:
            raise OctopError.localized(ErrorCode.BOT_CLOUD_REQUEST_REJECTED, status=409)
        previous_pages = state.get("pages", 0)
        state = {"header": header, "next": 0, "pages": 0}
    if body.offset < state["next"]:
        return state["next"], state["pages"]
    if body.offset != state["next"]:
        raise OctopError.localized(ErrorCode.BOT_CLOUD_REQUEST_REJECTED, status=409)
    try:
        size = len(base64.b64decode(body.data, validate=True))
    except ValueError:
        raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS, status=422) from None
    end = body.offset + size
    if size != min(PAGE_BYTES, body.total - body.offset) or size < 1:
        raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS, status=422)
    page = f"{prefix}:{state['pages']}"
    state.update(next=end, pages=state["pages"] + 1)
    settings.set_many(
        {page: body.data, prefix: json.dumps(state)},
        delete=[f"{prefix}:{i}" for i in range(previous_pages)],
    )
    return end, state["pages"]
