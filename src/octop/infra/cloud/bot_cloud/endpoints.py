"""Octop Bot cloud: addresses a tenant gives a connector or a channel.

On a cloud server the server itself connects to them, so a tenant's addresses must be public:
a URL is https and resolves to globally routable addresses only, a host name resolves to such
addresses only, and settings naming a file or program on the server are not accepted.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Iterator, Mapping
from typing import Any

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.ssrf_guard import (
    UnsafeOutboundUrl,
    is_public_ip,
    validate_https_url_resolved,
)

_URL_SUFFIXES = ("url", "endpoint", "proxy")
_HOST_SUFFIXES = ("host", "hostname", "server")
_LOCAL_NAMES = ("path", "binary", "binary_path")
_LOCAL_SUFFIXES = ("_path", "_dir", "_directory", "_file")


def _walk(values: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(values, Mapping):
        for key, value in values.items():
            yield from _walk(value, str(key))
    elif isinstance(values, (list, tuple)):
        for value in values:
            yield from _walk(value, prefix)
    else:
        yield prefix, values


def _refused(field: str) -> OctopError:
    return OctopError.localized(ErrorCode.ENDPOINT_NOT_ALLOWED, details={"field": field})


async def _host_is_public(host: str) -> bool:
    name = host.strip().strip("[]").rstrip(".")
    if not name:
        return False
    if is_public_ip(name):
        return True
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(name, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        return False
    return bool(infos) and all(is_public_ip(str(info[4][0])) for info in infos)


async def check_public_endpoints(values: Mapping[str, Any] | None) -> None:
    """Raise ``ENDPOINT_NOT_ALLOWED`` unless every address in ``values`` is public."""
    for field, value in _walk(values or {}):
        if not isinstance(value, str) or not value.strip():
            continue
        name = field.lower()
        if name in _LOCAL_NAMES or name.endswith(_LOCAL_SUFFIXES):
            raise _refused(field)
        if name.endswith(_URL_SUFFIXES):
            try:
                await validate_https_url_resolved(value.strip(), field=field)
            except UnsafeOutboundUrl:
                raise _refused(field) from None
        elif name.endswith(_HOST_SUFFIXES):
            host = value.strip().rsplit(":", 1)[0] if value.count(":") == 1 else value.strip()
            if not await _host_is_public(host):
                raise _refused(field)
