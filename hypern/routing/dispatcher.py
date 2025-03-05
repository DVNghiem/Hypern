# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import functools
import inspect
import traceback
import typing

import orjson
from pydantic import BaseModel

from hypern.config import context_store
from hypern.exceptions import HTTPException
from hypern.hypern import Request, Response
from hypern.response import JSONResponse

from .parser import InputHandler


@functools.lru_cache(maxsize=128)
def is_async_callable(obj: typing.Any) -> bool:
    """check callable obj is asyncale with cache"""
    while isinstance(obj, functools.partial):
        obj = obj.func
    return asyncio.iscoroutinefunction(obj) or (
        callable(obj) and asyncio.iscoroutinefunction(obj.__call__)
    )


async def run_in_threadpool(func: typing.Callable, *args, **kwargs):
    """run sync funtion thread pool."""
    if kwargs:
        func = functools.partial(func, **kwargs)
    return await asyncio.to_thread(func, *args)


async def dispatch(
    handler, request: Request, inject: typing.Dict[str, typing.Any]
) -> Response:
    try:
        context_store.set_context(request.context_id)

        is_async = is_async_callable(handler)

        signature = inspect.signature(handler)
        input_handler = InputHandler(request)
        kwargs = await input_handler.get_input_handler(signature, inject)

        if is_async:
            response = await handler(**kwargs)
        else:
            response = await run_in_threadpool(handler, **kwargs)

        return_type = signature.return_annotation
        if not isinstance(response, Response):
            if isinstance(return_type, type) and issubclass(return_type, BaseModel):
                response = return_type.model_validate(response).model_dump(mode="json")
            response_content = orjson.dumps({"message": response, "error_code": None})
            response = JSONResponse(content=response_content, status_code=200)
        return response

    except Exception as e:
        response_data: typing.Dict[str, str] = {
            "message": "",
            "error_code": "UNKNOWN_ERROR",
        }
        status_code = 400

        if isinstance(e, HTTPException):
            response_data = e.to_dict()
            status_code = e.status_code
        else:
            traceback.print_exc()
            response_data["message"] = str(e)

        error_content = orjson.dumps(response_data)
        return JSONResponse(content=error_content, status_code=status_code)
