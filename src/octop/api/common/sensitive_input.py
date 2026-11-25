"""Keep credential values out of HTTP validation errors."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from octop.infra.errors import ErrorCode, OctopError


class SensitiveInputRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handle = super().get_route_handler()

        async def sanitized(request: Request) -> Response:
            try:
                return await handle(request)
            except RequestValidationError:
                # Default validation errors echo the submitted input, including malformed passwords.
                raise OctopError.localized(ErrorCode.SLASH_BAD_ARGS, status=422) from None

        return sanitized
