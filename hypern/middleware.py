
from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any

from hypern._hypern import (
    BasicAuthMiddleware,
    CacheMiddleware,
    CircuitBreakerMiddleware,
    CompressionMiddleware,
    CorsMiddleware,
    RateLimitMiddleware,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
    TimeoutMiddleware,
)


class Middleware:
    """A validated middleware callable."""

    def __init__(self, handler: Callable) -> None:
        _validate_middleware(handler)
        self.handler = handler
        functools.update_wrapper(self, handler)

    def __call__(self, req: Any, res: Any, ctx: Any, next_fn: Callable) -> Any:
        return self.handler(req, res, ctx, next_fn)


def _validate_middleware(handler: Callable) -> None:
    """Validate the public middleware calling convention."""
    if not callable(handler):
        raise TypeError("Middleware must be callable")

    try:
        parameters = tuple(inspect.signature(handler).parameters.values())
    except (TypeError, ValueError) as error:
        raise TypeError(
            "Middleware must use (req, res, ctx, next)"
        ) from error

    valid_kinds = {
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    }
    if len(parameters) != 4 or any(parameter.kind not in valid_kinds for parameter in parameters):
        raise TypeError("Middleware must use (req, res, ctx, next)")


def normalize_middleware(value: object) -> Middleware | None:
    """Return a validated descriptor for a middleware callable."""
    if isinstance(value, Middleware):
        return value
    if callable(value):
        return Middleware(value)
    return None


class MiddlewareStack:
    """
    Stack of middleware that can be applied to routes.
    
    Example:
        from hypern.middleware import MiddlewareStack, CorsMiddleware, RateLimitMiddleware
        
        stack = MiddlewareStack()
        stack.use(CorsMiddleware.permissive())
        stack.use(RateLimitMiddleware(max_requests=100))
        
        @app.get("/protected", middleware=stack)
        async def protected_route(req, res):
            res.json({"message": "Secret data"})
    """
    
    def __init__(self):
        self._middleware: list[object] = []
    
    def use(self, middleware: object) -> MiddlewareStack:
        """Add middleware to the stack."""
        self._middleware.append(middleware)
        return self
    
    def get_middleware(self) -> list[object]:
        """Get the list of middleware."""
        return self._middleware.copy()
    
    def __iter__(self):
        return iter(self._middleware)
    
    def __len__(self):
        return len(self._middleware)


def middleware(func: Callable) -> Middleware:
    """
    Decorator that validates a middleware callable.
    
    Example:
        @middleware
        async def check_feature_flag(req, res, ctx, next):
            if not feature_enabled("new_feature"):
                res.status(404).json({"error": "Not found"})
                return
            await next()
    """
    return Middleware(func)


__all__ = [
    'BasicAuthMiddleware',
    'CacheMiddleware',
    'CircuitBreakerMiddleware',
    'CompressionMiddleware',
    # Rust Middleware
    'CorsMiddleware',
    'Middleware',
    # Utilities
    'MiddlewareStack',
    'RateLimitMiddleware',
    'RequestIdMiddleware',
    'SecurityHeadersMiddleware',
    'TimeoutMiddleware',
    'middleware',
]
