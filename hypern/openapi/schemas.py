# -*- coding: utf-8 -*-
from __future__ import annotations

from hypern.hypern import BaseSchemaGenerator, Route as InternalRoute
import typing
import orjson


from typing import Dict, Optional
from dataclasses import dataclass, field


@dataclass
class OAuth2Flow:
    authorizationUrl: Optional[str] = None
    tokenUrl: Optional[str] = None
    refreshUrl: Optional[str] = None
    scopes: Dict[str, str] = field(default_factory=dict)


@dataclass
class OAuth2Config:
    flows: Dict[str, OAuth2Flow]
    description: str = "OAuth2 authentication"


@dataclass
class SwaggerConfig:
    title: str = "Hypern API"
    version: str = "1.0.0"
    description: str = ""
    oauth2_config: Optional[OAuth2Config] = None

    def get_security_schemes(self) -> Dict:
        if not self.oauth2_config:
            return {}

        security_schemes = {"oauth2": {"type": "oauth2", "description": self.oauth2_config.description, "flows": {}}}

        for flow_name, flow in self.oauth2_config.flows.items():
            flow_config = {}
            if flow.authorizationUrl:
                flow_config["authorizationUrl"] = flow.authorizationUrl
            if flow.tokenUrl:
                flow_config["tokenUrl"] = flow.tokenUrl
            if flow.refreshUrl:
                flow_config["refreshUrl"] = flow.refreshUrl
            flow_config["scopes"] = flow.scopes
            security_schemes["oauth2"]["flows"][flow_name] = flow_config

        return security_schemes

    def get_openapi_schema(self) -> Dict:
        schema = {
            "openapi": "3.0.3",
            "info": {"title": self.title, "version": self.version, "description": self.description},
            "components": {"securitySchemes": self.get_security_schemes()},
            "security": [{"oauth2": []}] if self.oauth2_config else [],
        }
        return schema


class EndpointInfo(typing.NamedTuple):
    path: str
    http_method: str
    func: typing.Callable[..., typing.Any]


class SchemaGenerator(BaseSchemaGenerator):
    def __init__(self, base_schema: dict[str, typing.Any]) -> None:
        self.base_schema = base_schema

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
        schema = dict(self.base_schema)
        schema.setdefault("paths", {})
        for route in app.router.routes:
            parsed = self.parse_docstring(route.doc)

            if not parsed:
                continue

            if route.path not in schema["paths"]:
                schema["paths"][route.path] = {}

            schema["paths"][route.path][route.method.lower()] = orjson.loads(parsed)

        return schema
