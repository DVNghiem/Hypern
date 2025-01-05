# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import functools
import inspect
import traceback
import typing

import orjson
from pydantic import BaseModel

from hypern.exceptions import HTTPException
from hypern.hypern import Request, Response
from hypern.response import JSONResponse

from .parser import InputHandler
from hypern.config import context_store


def is_async_callable(obj: typing.Any) -> bool:
    while isinstance(obj, functools.partial):
        obj = obj.funcz
    return asyncio.iscoroutinefunction(obj) or (callable(obj) and asyncio.iscoroutinefunction(obj.__call__))


async def run_in_threadpool(func: typing.Callable, *args, **kwargs):
    if kwargs:  # pragma: no cover
        # run_sync doesn't accept 'kwargs', so bind them in here
        func = functools.partial(func, **kwargs)
    return await asyncio.to_thread(func, *args)


async def dispatch(handler, request: Request, inject: typing.Dict[str, typing.Any]) -> Response:
    try:
        # set context for global handler
        context_store.set_context(request.context_id)

        is_async = is_async_callable(handler)
        signature = inspect.signature(handler)
        input_handler = InputHandler(request)
        _response_type = signature.return_annotation
        _kwargs = await input_handler.get_input_handler(signature, inject)

        if is_async:
            response = await handler(**_kwargs)  # type: ignore
        else:
            response = await run_in_threadpool(handler, **_kwargs)
        if not isinstance(response, Response):
            if isinstance(_response_type, type) and issubclass(_response_type, BaseModel):
                response = _response_type.model_validate(response).model_dump(mode="json")  # type: ignore
            response = JSONResponse(
                content=orjson.dumps({"message": response, "error_code": None}),
                status_code=200,
            )

    except Exception as e:
        _res: typing.Dict = {"message": "", "error_code": "UNKNOWN_ERROR"}
        if isinstance(e, HTTPException):
            _res = e.to_dict()
            _status = e.status_code
        else:
            traceback.print_exc()
            _res["message"] = str(e)
            _status = 400
        response = JSONResponse(
            content=orjson.dumps(_res),
            status_code=_status,
        )
    return response
