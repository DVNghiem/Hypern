
from __future__ import annotations

from typing import Callable, List

from hypern._hypern import (
    CorsMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    TimeoutMiddleware,
    CompressionMiddleware,
    RequestIdMiddleware,
    LogMiddleware,
    BasicAuthMiddleware,
)

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
        self._middleware: List[object] = []
    
    def use(self, middleware: object) -> 'MiddlewareStack':
        """Add middleware to the stack."""
        self._middleware.append(middleware)
        return self
    
    def get_middleware(self) -> List[object]:
        """Get the list of middleware."""
        return self._middleware.copy()
    
    def __iter__(self):
        return iter(self._middleware)
    
    def __len__(self):
        return len(self._middleware)


def middleware(func: Callable) -> Callable:
    """
    Decorator to mark a function as middleware (for route-specific use).
    
    Note: For high-performance middleware, use the built-in Rust middleware.
    This decorator is for simple route-specific logic only.
    
    Example:
        @middleware
        async def check_feature_flag(req, res, next):
            if not feature_enabled("new_feature"):
                res.status(404).json({"error": "Not found"})
                return
            await next()
    """
    func._is_middleware = True
    return func


def before_request(func: Callable) -> Callable:
    """
    Decorator to mark a function as a before-request hook.
    
    Example:
        @app.before_request
        async def log_request(req, res):
            print(f"Incoming: {req.method} {req.path}")
    """
    func._before_request = True
    return func


def after_request(func: Callable) -> Callable:
    """
    Decorator to mark a function as an after-request hook.
    
    Example:
        @app.after_request
        async def add_headers(req, res):
            res.header("X-Server", "Hypern")
    """
    func._after_request = True
    return func


__all__ = [
    # Rust Middleware
    'CorsMiddleware',
    'RateLimitMiddleware',
    'SecurityHeadersMiddleware',
    'TimeoutMiddleware',
    'CompressionMiddleware',
    'RequestIdMiddleware',
    'LogMiddleware',
    'BasicAuthMiddleware',
    
    # Utilities
    'MiddlewareStack',
    'middleware',
    'before_request',
    'after_request',
]
