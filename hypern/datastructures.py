from typing import Optional
from enum import Enum
from pydantic import BaseModel, AnyUrl


class BaseModelWithConfig(BaseModel):
    model_config = {"extra": "allow"}


class Contact(BaseModelWithConfig):
    name: Optional[str] = None
    url: Optional[AnyUrl] = None
    email: Optional[str] = None


class License(BaseModelWithConfig):
    name: str
    identifier: Optional[str] = None
    url: Optional[AnyUrl] = None


class Info(BaseModelWithConfig):
    title: str
    summary: Optional[str] = None
    description: Optional[str] = None
    contact: Optional[Contact] = None
    license: Optional[License] = None
    version: str


class HTTPMethod(Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    OPTIONS = "OPTIONS"
    HEAD = "HEAD"
    TRACE = "TRACE"
    CONNECT = "CONNECT"
