"""Move explicitly approved files into or out of the running Bot's workspace."""

from __future__ import annotations

import base64
import hashlib
import secrets
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, Field

MAX_TRANSFER = 1024 * 1024


class FileBytes(BaseModel):
    content: str = Field(max_length=4 * ((MAX_TRANSFER + 2) // 3))
    size: int = Field(ge=0, le=MAX_TRANSFER)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def encode(cls, data: bytes) -> FileBytes:
        if len(data) > MAX_TRANSFER:
            raise ValueError("The file exceeds the 1 MiB transfer limit.")
        return cls(
            content=base64.b64encode(data).decode(),
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )

    def decode(self) -> bytes:
        data = base64.b64decode(self.content, validate=True)
        if len(data) != self.size or hashlib.sha256(data).hexdigest() != self.sha256:
            raise ValueError("The transfer did not match the selected file.")
        return data


def inbound_path(path: str) -> str:
    name = PurePosixPath(path.replace("\\", "/")).name
    if not name or name.startswith(".") or any(ord(c) < 32 for c in name):
        raise ValueError("Choose a named local file.")
    return f"inbound/{secrets.token_hex(8)}/{name}"


async def fetch_file(workspace: Any, path: str) -> FileBytes:
    parts = path.split("/")
    if not parts or any(
        not part or part.startswith(".") or "\\" in part or ":" in part for part in parts
    ):
        raise ValueError("Use a visible file relative to the Bot workspace.")
    bounded_read = getattr(workspace, "adownload_bytes_capped", None)
    if bounded_read is None:
        raise ValueError("Bounded workspace downloads are unavailable on this server.")
    data = await bounded_read(path, MAX_TRANSFER)
    if data is None:
        raise ValueError("The cloud file was not found.")
    return FileBytes.encode(data)
