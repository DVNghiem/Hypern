from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, Dict, List, Optional, Tuple

from hypern._hypern import Route as RustRoute
from hypern._hypern import Router as RustRouter


class Router:
    """
    Router class.
    
    Example:
        # Create a router
        api = Router(prefix="/api/v1")
        
        @api.get("/users")
        async def get_users(req, res):
            res.json([{"id": 1, "name": "John"}])
        
        @api.get("/users/:id")
        async def get_user(req, res):
            user_id = req.param("id")
            res.json({"id": user_id})
        
        @api.post("/users")
        async def create_user(req, res):
            body = req.json()
            res.status(201).json(body)
        
        # Mount router on app
        app.use("/api/v1", api)
    """
    
    def __init__(self, prefix: str = ""):
        self.prefix = prefix.rstrip("/")
        self._routes: List[Tuple[str, str, Callable, Dict[str, Any]]] = []
        self._middleware: List[Callable] = []
        self._before_handlers: List[Callable] = []
        self._after_handlers: List[Callable] = []
        self._error_handlers: Dict[type, Callable] = {}
        self._rust_router = RustRouter(path=prefix)
    
    def _normalize_path(self, path: str) -> str:
        """Normalize path by ensuring it starts with /."""
        if not path.startswith("/"):
            path = "/" + path
        return path
    
    def _convert_express_path(self, path: str) -> str:
        """
        Convert params to Hypern format.
        Express: /users/:id -> Hypern: /users/:id (same format)
        """
        return path
    
    def route(self, path: str) -> 'RouteBuilder':
        """
        Create a route builder for chaining HTTP methods.
        
        Example:
            router.route("/users")
                .get(get_users)
                .post(create_user)
        """
        return RouteBuilder(self, path)
    
    def _add_route(
        self,
        method: str,
        path: str,
        handler: Callable,
        middleware: Optional[List[Callable]] = None,
        **options
    ):
        """Internal method to add a route."""
        full_path = self._normalize_path(path)
        converted_path = self._convert_express_path(full_path)
        
        # Wrap handler with middleware if provided
        wrapped_handler = handler
        if middleware:
            wrapped_handler = self._wrap_with_middleware(handler, middleware)
        
        # Store route info
        self._routes.append((method.upper(), converted_path, wrapped_handler, options))
        
        # Add to Rust router
        route = RustRoute(
            path=converted_path,
            function=wrapped_handler,
            method=method.upper(),
            doc=handler.__doc__
        )
        self._rust_router.add_route(route)
    
    def _wrap_with_middleware(self, handler: Callable, middleware: List[Callable]) -> Callable:
        """Wrap a handler with middleware chain."""
        @functools.wraps(handler)
        async def wrapped(req, res):
            index = 0
            
            async def next_middleware():
                nonlocal index
                if index < len(middleware):
                    mw = middleware[index]
                    index += 1
                    if inspect.iscoroutinefunction(mw):
                        await mw(req, res, next_middleware)
                    else:
                        mw(req, res, next_middleware)
                else:
                    if inspect.iscoroutinefunction(handler):
                        await handler(req, res)
                    else:
                        handler(req, res)
            
            await next_middleware()
        
        return wrapped
    
    def get(self, path: str, middleware: Optional[List[Callable]] = None, **options):
        """Register a GET route."""
        def decorator(handler: Callable) -> Callable:
            self._add_route("GET", path, handler, middleware, **options)
            return handler
        return decorator
    
    def post(self, path: str, middleware: Optional[List[Callable]] = None, **options):
        """Register a POST route."""
        def decorator(handler: Callable) -> Callable:
            self._add_route("POST", path, handler, middleware, **options)
            return handler
        return decorator
    
    def put(self, path: str, middleware: Optional[List[Callable]] = None, **options):
        """Register a PUT route."""
        def decorator(handler: Callable) -> Callable:
            self._add_route("PUT", path, handler, middleware, **options)
            return handler
        return decorator
    
    def delete(self, path: str, middleware: Optional[List[Callable]] = None, **options):
        """Register a DELETE route."""
        def decorator(handler: Callable) -> Callable:
            self._add_route("DELETE", path, handler, middleware, **options)
            return handler
        return decorator
    
    def patch(self, path: str, middleware: Optional[List[Callable]] = None, **options):
        """Register a PATCH route."""
        def decorator(handler: Callable) -> Callable:
            self._add_route("PATCH", path, handler, middleware, **options)
            return handler
        return decorator
    
    def options(self, path: str, middleware: Optional[List[Callable]] = None, **options):
        """Register an OPTIONS route."""
        def decorator(handler: Callable) -> Callable:
            self._add_route("OPTIONS", path, handler, middleware, **options)
            return handler
        return decorator
    
    def head(self, path: str, middleware: Optional[List[Callable]] = None, **options):
        """Register a HEAD route."""
        def decorator(handler: Callable) -> Callable:
            self._add_route("HEAD", path, handler, middleware, **options)
            return handler
        return decorator
    
    def all(self, path: str, middleware: Optional[List[Callable]] = None, **options):
        """Register a route for all HTTP methods."""
        def decorator(handler: Callable) -> Callable:
            for method in ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]:
                self._add_route(method, path, handler, middleware, **options)
            return handler
        return decorator
    
    def use(self, middleware: Callable) -> 'Router':
        """
        Add middleware to this router.
        
        Example:
            router.use(auth_middleware)
            router.use(logging_middleware)
        """
        self._middleware.append(middleware)
        return self
    
    def before(self, handler: Callable) -> Callable:
        """
        Add a before-request handler.
        
        Example:
            @router.before
            async def log_request(req, res):
                print(f"Request: {req.method} {req.path}")
        """
        self._before_handlers.append(handler)
        return handler
    
    def after(self, handler: Callable) -> Callable:
        """
        Add an after-request handler.
        
        Example:
            @router.after
            async def add_headers(req, res):
                res.header("X-Response-Time", "123ms")
        """
        self._after_handlers.append(handler)
        return handler
    
    def error(self, exc_class: type) -> Callable:
        """
        Add an error handler for a specific exception type.
        
        Example:
            @router.error(ValueError)
            def handle_value_error(req, res, error):
                res.status(400).json({"error": str(error)})
        """
        def decorator(handler: Callable) -> Callable:
            self._error_handlers[exc_class] = handler
            return handler
        return decorator
    
    def param(self, name: str) -> Callable:
        """
        Add a parameter middleware for processing path parameters.
        
        Example:
            @router.param("id")
            async def process_id(req, res, next, id):
                req.user = await get_user(id)
                await next()
        """
        def decorator(handler: Callable) -> Callable:
            # Store param handler
            if not hasattr(self, '_param_handlers'):
                self._param_handlers = {}
            self._param_handlers[name] = handler
            return handler
        return decorator
    
    def get_routes(self) -> List[Tuple[str, str, Callable]]:
        """Get all registered routes."""
        return [(method, path, handler) for method, path, handler, _ in self._routes]
    
    def get_rust_router(self) -> RustRouter:
        """Get the underlying Rust router."""
        return self._rust_router


class RouteBuilder:
    """
    Route builder for chaining multiple handlers on the same path.
    
    Example:
        router.route("/users")
            .get(get_users)
            .post(create_user)
            .put(update_user)
            .delete(delete_user)
    """
    
    def __init__(self, router: Router, path: str):
        self.router = router
        self.path = path
    
    def get(self, handler: Callable, **options) -> 'RouteBuilder':
        """Add GET handler."""
        self.router._add_route("GET", self.path, handler, **options)
        return self
    
    def post(self, handler: Callable, **options) -> 'RouteBuilder':
        """Add POST handler."""
        self.router._add_route("POST", self.path, handler, **options)
        return self
    
    def put(self, handler: Callable, **options) -> 'RouteBuilder':
        """Add PUT handler."""
        self.router._add_route("PUT", self.path, handler, **options)
        return self
    
    def delete(self, handler: Callable, **options) -> 'RouteBuilder':
        """Add DELETE handler."""
        self.router._add_route("DELETE", self.path, handler, **options)
        return self
    
    def patch(self, handler: Callable, **options) -> 'RouteBuilder':
        """Add PATCH handler."""
        self.router._add_route("PATCH", self.path, handler, **options)
        return self
    
    def options(self, handler: Callable, **options) -> 'RouteBuilder':
        """Add OPTIONS handler."""
        self.router._add_route("OPTIONS", self.path, handler, **options)
        return self
    
    def head(self, handler: Callable, **options) -> 'RouteBuilder':
        """Add HEAD handler."""
        self.router._add_route("HEAD", self.path, handler, **options)
        return self
    
    def all(self, handler: Callable, **options) -> 'RouteBuilder':
        """Add handler for all methods."""
        for method in ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]:
            self.router._add_route(method, self.path, handler, **options)
        return self


__all__ = [
    'Router',
    'RouteBuilder',
]
