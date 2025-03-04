
from hypern.hypern import Route, Router, FunctionInfo
from typing import Callable, Any
from hypern.enum import HTTPMethod
import asyncio


class RouterManager:
    def __init__(self):
        self.router = Router(path="/")
    
    def add_route(self, method: HTTPMethod, endpoint: str, handler: Callable[..., Any]):
        is_async = asyncio.iscoroutinefunction(handler)
        func_info = FunctionInfo(handler=handler, is_async=is_async)
        route = Route(path=endpoint, function=func_info, method=method.name)
        self.router.add_route(route=route)

    def extend_route(self, routes):
        self.router.extend_route(routes=routes)
