import asyncio

from hypern.hypern import FunctionInfo
from hypern.middleware import Middleware


class MiddlewareManager:
    def __init__(self):
        self.before_request = []
        self.after_request = []

    def add_middleware(self, middleware: Middleware):
        setattr(middleware, "app", self)
        before_request = getattr(middleware, "before_request", None)
        after_request = getattr(middleware, "after_request", None)
        if before_request:
            is_async = asyncio.iscoroutinefunction(before_request)
            func_info = FunctionInfo(handler=before_request, is_async=is_async)
            self.before_request.append((func_info, middleware.config))
        if after_request:
            is_async = asyncio.iscoroutinefunction(after_request)
            func_info = FunctionInfo(handler=after_request, is_async=is_async)
            self.after_request.append((func_info, middleware.config))
