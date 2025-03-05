# -*- coding: utf-8 -*-
import asyncio
import inspect
from enum import Enum
from typing import Any, Callable, Dict, List, Type, Union, get_args, get_origin

import yaml  # type: ignore
from pydantic import BaseModel
from pydantic.fields import FieldInfo

from hypern.enum import HTTPMethod
from hypern.hypern import FunctionInfo, Request
from hypern.hypern import Route as InternalRoute

from .dispatcher import dispatch


def get_field_type(field: FieldInfo) -> Any:
    """Return type outer of field"""
    return field.outer_type_


def join_url_paths(*parts: str) -> str:
    """Join multiple parts of a URL path."""
    if not parts:
        return ""
    first_part = parts[0]
    cleaned_parts = [part.strip("/") for part in parts if part]
    starts_with_slash = first_part.startswith("/")
    joined_path = "/".join(cleaned_parts)
    return f"/{joined_path}" if starts_with_slash else joined_path


def pydantic_to_swagger(model: Type[BaseModel] | Dict[str, Any]) -> Dict[str, Any]:
    """convert pydantic model to swagger schema"""
    if isinstance(model, dict):
        schema = {}
        for name, field_type in model.items():
            schema[name] = _process_field(name, field_type)
        return schema

    schema = {model.__name__: {"type": "object", "properties": {}}}
    for field_name, field in model.model_fields.items():
        schema[model.__name__]["properties"][field_name] = _process_field(
            field_name, field
        )
    return schema


class SchemaProcessor:
    """process schema from pydantic model"""

    @staticmethod
    def process_union(type_args: tuple) -> Dict[str, Any]:
        """process union type"""
        if type(None) in type_args:
            non_none_type = next(arg for arg in type_args if arg is not type(None))
            schema = SchemaProcessor._process_field("", non_none_type)
            schema["nullable"] = True
            return schema
        return {"oneOf": [SchemaProcessor._process_field("", arg) for arg in type_args]}

    @staticmethod
    def process_enum(enum_type: Type[Enum]) -> Dict[str, Any]:
        """process enum type"""
        return {
            "type": "string",
            "enum": [e.value for e in enum_type.__members__.values()],
        }

    @staticmethod
    def process_primitive(field_type: type) -> Dict[str, str]:
        """process primitive type"""
        type_mapping = {int: "integer", float: "number", str: "string", bool: "boolean"}
        return {"type": type_mapping.get(field_type, "object")}

    @staticmethod
    def process_list(list_type: type) -> Dict[str, Any]:
        """Pricess list type"""
        schema = {"type": "array"}
        type_args = get_args(list_type)
        schema["items"] = (
            SchemaProcessor._process_field("item", type_args[0]) if type_args else {}
        )
        return schema

    @staticmethod
    def process_dict(dict_type: type) -> Dict[str, Any]:
        """process dict type"""
        schema = {"type": "object"}
        type_args = get_args(dict_type)
        if type_args and type_args[0] == str:
            schema["additionalProperties"] = SchemaProcessor._process_field(
                "value", type_args[1]
            )
        return schema

    @classmethod
    def _process_field(cls, field_name: str, field: Any) -> Dict[str, Any]:
        """process field"""
        field_annotation = field.annotation if isinstance(field, FieldInfo) else field
        origin_type = get_origin(field_annotation)

        if origin_type is Union:
            return cls.process_union(get_args(field_annotation))
        if isinstance(field_annotation, type) and issubclass(field_annotation, Enum):
            return cls.process_enum(field_annotation)
        if field_annotation in {int, float, str, bool}:
            return cls.process_primitive(field_annotation)
        if field_annotation == list or origin_type is list:
            return cls.process_list(field_annotation)
        if field_annotation == dict or origin_type is dict:
            return cls.process_dict(field_annotation)
        if isinstance(field_annotation, type) and issubclass(
            field_annotation, BaseModel
        ):
            return pydantic_to_swagger(field_annotation)
        return {"type": "object"}


def _process_field(field_name: str, field: Any) -> Dict[str, Any]:
    """process field"""
    return SchemaProcessor._process_field(field_name, field)


class Route:
    """process http route"""

    def __init__(
        self,
        path: str,
        endpoint: Callable[..., Any] | None = None,
        *,
        name: str | None = None,
        tags: List[str] | None = None,
    ) -> None:
        self.path = path
        self.endpoint = endpoint
        self.tags = tags or ["Default"]
        self.name = name
        self.http_methods = {
            "GET": HTTPMethod.GET,
            "POST": HTTPMethod.POST,
            "PUT": HTTPMethod.PUT,
            "DELETE": HTTPMethod.DELETE,
            "PATCH": HTTPMethod.PATCH,
            "HEAD": HTTPMethod.HEAD,
            "OPTIONS": HTTPMethod.OPTIONS,
        }
        self.functional_handlers: List[InternalRoute] = []

    def _process_model_params(
        self, param_name: str, param_type: type, swagger_doc: Dict
    ) -> None:
        """process parameters of model for Swagger."""
        if not (isinstance(param_type, type) and issubclass(param_type, BaseModel)):
            return
        if param_name == "form_data":
            swagger_doc["requestBody"] = {
                "content": {
                    "application/json": {
                        "schema": pydantic_to_swagger(param_type).get(
                            param_type.__name__
                        )
                    }
                }
            }
        elif param_name == "query_params":
            swagger_doc["parameters"] = [
                {"name": name, "in": "query", "schema": _process_field(name, field)}
                for name, field in param_type.model_fields.items()
            ]
        elif param_name == "path_params":
            path_params = [
                {
                    "name": name,
                    "in": "path",
                    "required": True,
                    "schema": _process_field(name, field),
                }
                for name, field in param_type.model_fields.items()
            ]
            swagger_doc.setdefault("parameters", []).extend(path_params)

    def _process_response(self, return_type: type, swagger_doc: Dict) -> None:
        """process return type for swagger"""
        if isinstance(return_type, type) and issubclass(return_type, BaseModel):
            swagger_doc["responses"] = {
                "200": {
                    "description": "Successful response",
                    "content": {
                        "application/json": {
                            "schema": pydantic_to_swagger(return_type).get(
                                return_type.__name__
                            )
                        }
                    },
                }
            }

    def swagger_generate(
        self, signature: inspect.Signature, summary: str = "Document API"
    ) -> str:
        """create document from function signature"""
        parameters = signature.parameters.values()
        param_types = {param.name: param.annotation for param in parameters}
        swagger_doc: Dict = {
            "summary": summary,
            "tags": self.tags,
            "responses": [],
            "name": self.name,
        }

        for param_name, param_type in param_types.items():
            self._process_model_params(param_name, param_type, swagger_doc)
        self._process_response(signature.return_annotation, swagger_doc)
        return yaml.dump(swagger_doc)

    def _combine_path(self, base_path: str, sub_path: str) -> str:
        if base_path.endswith("/") and sub_path.startswith("/"):
            return base_path + sub_path[1:]
        if not base_path.endswith("/") and not sub_path.startswith("/"):
            return f"{base_path}/{sub_path}"
        return base_path + sub_path

    def make_internal_route(
        self, path: str, handler: Callable, method: str
    ) -> InternalRoute:
        is_async_handler = asyncio.iscoroutinefunction(handler)
        function_info = FunctionInfo(handler=handler, is_async=is_async_handler)
        return InternalRoute(path=path, function=function_info, method=method)

    def __call__(self, *args: Any, **kwargs: Any) -> List[InternalRoute]:
        """process route from endpoint or functional handlers."""
        routes: List[InternalRoute] = []

        if not self.endpoint and not self.functional_handlers:
            raise ValueError(f"Not found handler for path: {self.path}")

        if not self.endpoint:
            return self.functional_handlers

        for method_name, func in self.endpoint.__dict__.items():
            if method_name.upper() in self.http_methods:
                signature = inspect.signature(func)
                swagger_doc = self.swagger_generate(
                    signature, func.__doc__ or "No description"
                )
                endpoint_instance = self.endpoint()
                route = self.make_internal_route(
                    path=self.path,
                    handler=endpoint_instance.dispatch,
                    method=method_name.upper(),
                )
                route.doc = swagger_doc
                routes.append(route)
                del endpoint_instance  # Free memory
        return routes

    def add_route(self, route_path: str, method: str) -> Callable:
        def decorator(handler: Callable[..., Any]) -> Callable[..., Any]:
            async def route_wrapper(request: Request, inject: Dict[str, Any]) -> Any:
                return await dispatch(handler, request, inject)

            signature = inspect.signature(handler)
            route = self.make_internal_route(
                path=join_url_paths(self.path, route_path),
                handler=route_wrapper,
                method=method.upper(),
            )
            route.doc = self.swagger_generate(
                signature, handler.__doc__ or "No description"
            )
            self.functional_handlers.append(route)
            return handler

        return decorator

    def get(self, path: str) -> Callable:
        return self.add_route(path, "GET")

    def post(self, path: str) -> Callable:
        return self.add_route(path, "POST")

    def put(self, path: str) -> Callable:
        return self.add_route(path, "PUT")

    def delete(self, path: str) -> Callable:
        return self.add_route(path, "DELETE")

    def patch(self, path: str) -> Callable:
        return self.add_route(path, "PATCH")

    def head(self, path: str) -> Callable:
        return self.add_route(path, "HEAD")

    def options(self, path: str) -> Callable:
        return self.add_route(path, "OPTIONS")
