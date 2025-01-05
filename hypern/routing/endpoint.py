# -*- coding: utf-8 -*-
from __future__ import annotations

import typing
from typing import Any, Dict

import orjson

from hypern.hypern import Request, Response
from hypern.response import JSONResponse

from .dispatcher import dispatch


class HTTPEndpoint:
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    def method_not_allowed(self, request: Request) -> Response:
        return JSONResponse(
            description=orjson.dumps({"message": "Method Not Allowed", "error_code": "METHOD_NOT_ALLOW"}),
            status_code=405,
        )

    async def dispatch(self, request: Request, inject: Dict[str, Any]) -> Response:
        handler_name = "get" if request.method == "HEAD" and not hasattr(self, "head") else request.method.lower()
        handler: typing.Callable[[Request], typing.Any] = getattr(  # type: ignore
            self, handler_name, self.method_not_allowed
        )
        return await dispatch(handler, request, inject)
