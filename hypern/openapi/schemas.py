# -*- coding: utf-8 -*-
from __future__ import annotations

from hypern.hypern import BaseSchemaGenerator, Route as InternalRoute
from hypern.datastructures import SwaggerConfig
import typing
import orjson


class EndpointInfo(typing.NamedTuple):
    path: str
    http_method: str
    func: typing.Callable[..., typing.Any]


class SchemaGenerator(BaseSchemaGenerator):
    def __init__(self, config: SwaggerConfig) -> None:
        self.config = config

    def get_endpoints(self, routes: list[InternalRoute]) -> list[EndpointInfo]:
        """
        Given the routes, yields the following information:

        - path
            eg: /users/
        - http_method
            one of 'get', 'post', 'put', 'patch', 'delete', 'options'
        - func
            method ready to extract the docstring
        """
        endpoints_info: list[EndpointInfo] = []

        for route in routes:
            method = route.method.lower()
            endpoints_info.append(EndpointInfo(path=route.path, http_method=method, func=route.function.handler))
        return endpoints_info

    def get_schema(self, app) -> dict[str, typing.Any]:
        schema = self.config.get_openapi_schema()
        schema.setdefault("paths", {})
        for route in app.router.routes:
            parsed = self.parse_docstring(route.doc)

            if not parsed:
                continue

            if route.path not in schema["paths"]:
                schema["paths"][route.path] = {}

            schema["paths"][route.path][route.method.lower()] = orjson.loads(parsed)

        return schema
