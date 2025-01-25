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


def get_field_type(field):
    return field.outer_type_


def join_url_paths(*parts):
    first = parts[0]
    parts = [part.strip("/") for part in parts]
    starts_with_slash = first.startswith("/") if first else False
    joined = "/".join(part for part in parts if part)
    if starts_with_slash:
        joined = "/" + joined
    return joined


def pydantic_to_swagger(model: type[BaseModel] | dict):
    if isinstance(model, dict):
        # Handle the case when a dict is passed instead of a Pydantic model
        schema = {}
        for name, field_type in model.items():
            schema[name] = _process_field(name, field_type)
        return schema

    schema = {
        model.__name__: {
            "type": "object",
            "properties": {},
        }
    }

    for name, field in model.model_fields.items():
        schema[model.__name__]["properties"][name] = _process_field(name, field)

    return schema


class SchemaProcessor:
    @staticmethod
    def process_union(args: tuple) -> Dict[str, Any]:
        """Process Union types"""
        if type(None) in args:
            inner_type = next(arg for arg in args if arg is not type(None))
            schema = SchemaProcessor._process_field("", inner_type)
            schema["nullable"] = True
            return schema
        return {"oneOf": [SchemaProcessor._process_field("", arg) for arg in args]}

    @staticmethod
    def process_enum(annotation: Type[Enum]) -> Dict[str, Any]:
        """Process Enum types"""
        return {"type": "string", "enum": [e.value for e in annotation.__members__.values()]}

    @staticmethod
    def process_primitive(annotation: type) -> Dict[str, str]:
        """Process primitive types"""
        type_mapping = {int: "integer", float: "number", str: "string", bool: "boolean"}
        return {"type": type_mapping.get(annotation, "object")}

    @staticmethod
    def process_list(annotation: type) -> Dict[str, Any]:
        """Process list types"""
        schema = {"type": "array"}

        args = get_args(annotation)
        if args:
            item_type = args[0]
            schema["items"] = SchemaProcessor._process_field("item", item_type)
        else:
            schema["items"] = {}
        return schema

    @staticmethod
    def process_dict(annotation: type) -> Dict[str, Any]:
        """Process dict types"""
        schema = {"type": "object"}

        args = get_args(annotation)
        if args:
            key_type, value_type = args
            if key_type == str:  # noqa: E721
                schema["additionalProperties"] = SchemaProcessor._process_field("value", value_type)
        return schema

    @classmethod
    def _process_field(cls, name: str, field: Any) -> Dict[str, Any]:
        """Process a single field"""
        if isinstance(field, FieldInfo):
            annotation = field.annotation
        else:
            annotation = field

        # Process Union types
        origin = get_origin(annotation)
        if origin is Union:
            return cls.process_union(get_args(annotation))

        # Process Enum types
        if isinstance(annotation, type) and issubclass(annotation, Enum):
            return cls.process_enum(annotation)

        # Process primitive types
        if annotation in {int, float, str, bool}:
            return cls.process_primitive(annotation)

        # Process list types
        if annotation == list or origin is list:  # noqa: E721
            return cls.process_list(annotation)

        # Process dict types
        if annotation == dict or origin is dict:  # noqa: E721
            return cls.process_dict(annotation)

        # Process Pydantic models
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return pydantic_to_swagger(annotation)

        # Fallback for complex types
        return {"type": "object"}


def _process_field(name: str, field: Any) -> Dict[str, Any]:
    """
    Process a field and return its schema representation

    Args:
        name: Field name
        field: Field type or FieldInfo object

    Returns:
        Dictionary representing the JSON schema for the field
    """
    return SchemaProcessor._process_field(name, field)


class Route:
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
        self.functional_handlers = []

    def _process_model_params(self, key: str, item: type, docs: Dict) -> None:
        if not (isinstance(item, type) and issubclass(item, BaseModel)):
            return

        if key == "form_data":
            docs["requestBody"] = {"content": {"application/json": {"schema": pydantic_to_swagger(item).get(item.__name__)}}}
        elif key == "query_params":
            docs["parameters"] = [{"name": param, "in": "query", "schema": _process_field(param, field)} for param, field in item.model_fields.items()]
        elif key == "path_params":
            path_params = [
                {"name": param, "in": "path", "required": True, "schema": _process_field(param, field)} for param, field in item.model_fields.items()
            ]
            docs.setdefault("parameters", []).extend(path_params)

    def _process_response(self, response_type: type, docs: Dict) -> None:
        if isinstance(response_type, type) and issubclass(response_type, BaseModel):
            docs["responses"] = {
                "200": {
                    "description": "Successful response",
                    "content": {"application/json": {"schema": pydantic_to_swagger(response_type).get(response_type.__name__)}},
                }
            }

    def swagger_generate(self, signature: inspect.Signature, summary: str = "Document API") -> str:
        _inputs = signature.parameters.values()
        _inputs_dict = {_input.name: _input.annotation for _input in _inputs}
        _docs: Dict = {"summary": summary, "tags": self.tags, "responses": [], "name": self.name}

        for key, item in _inputs_dict.items():
            self._process_model_params(key, item, _docs)

        self._process_response(signature.return_annotation, _docs)
        return yaml.dump(_docs)

    def _combine_path(self, path1: str, path2: str) -> str:
        if path1.endswith("/") and path2.startswith("/"):
            return path1 + path2[1:]
        if not path1.endswith("/") and not path2.startswith("/"):
            return path1 + "/" + path2
        return path1 + path2

    def make_internal_route(self, path, handler, method) -> InternalRoute:
        is_async = asyncio.iscoroutinefunction(handler)
        func_info = FunctionInfo(handler=handler, is_async=is_async)
        return InternalRoute(path=path, function=func_info, method=method)

    def __call__(self, *args: Any, **kwds: Any) -> Any:
        routes = []

        # Validate handlers
        if not self.endpoint and not self.functional_handlers:
            raise ValueError(f"No handler found for route: {self.path}")

        # Handle functional routes
        if not self.endpoint:
            return self.functional_handlers

        # Handle class-based routes
        for name, func in self.endpoint.__dict__.items():
            if name.upper() in self.http_methods:
                sig = inspect.signature(func)
                doc = self.swagger_generate(sig, func.__doc__)
                endpoint_obj = self.endpoint()
                route = self.make_internal_route(path=self.path, handler=endpoint_obj.dispatch, method=name.upper())
                route.doc = doc
                routes.append(route)
                del endpoint_obj  # free up memory
        return routes

    def add_route(
        self,
        func_path: str,
        method: str,
    ) -> Callable:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            async def functional_wrapper(request: Request, inject: Dict[str, Any]) -> Any:
                return await dispatch(func, request, inject)

            sig = inspect.signature(func)
            route = self.make_internal_route(path=join_url_paths(self.path, func_path), handler=functional_wrapper, method=method.upper())
            route.doc = self.swagger_generate(sig, func.__doc__)

            self.functional_handlers.append(route)

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
