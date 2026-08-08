from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from hypern._hypern import Route as RustRoute
from hypern._hypern import Router as RustRouter
from hypern.middleware import normalize_middleware


@dataclass(slots=True)
class _RouteDefinition:
    """Raw route callable and the Python metadata used when it is mounted."""

    method: str
    path: str
    handler: Callable
    middleware: tuple[Callable, ...] = ()
    options: dict[str, Any] = field(default_factory=dict)


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
        self._routes: list[_RouteDefinition] = []
        self._middleware: list[Callable] = []
        self._error_handlers: dict[type, Callable] = {}
        self._registration_change_listeners: set[Callable[[], None]] = set()
        self._registration_frozen = False
        self._rust_router = RustRouter(path=prefix)

    def _assert_registration_open(self) -> None:
        """Reject router mutations after its mounted application listens."""
        if self._registration_frozen:
            raise RuntimeError("router registration is frozen after listen()")

    def _register_change_listener(self, listener: Callable[[], None]) -> None:
        """Notify a mounting app when setup changes affect its descriptors."""
        self._registration_change_listeners.add(listener)

    def _notify_registration_changed(self) -> None:
        for listener in self._registration_change_listeners:
            listener()

    def _freeze_registration(self) -> None:
        self._registration_frozen = True
    
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
    
    def route(self, path: str) -> RouteBuilder:
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
        middleware: list[Callable] | None = None,
        **options
    ):
        """Internal method to add a route."""
        self._assert_registration_open()
        full_path = self._normalize_path(path)
        converted_path = self._convert_express_path(full_path)
        
        method = method.upper()
        # Store the raw handler. Mounted routes are executed by the application's
        # canonical Python pipeline, which receives this middleware metadata.
        self._routes.append(
            _RouteDefinition(
                method=method,
                path=converted_path,
                handler=handler,
                middleware=tuple(middleware or ()),
                options=options,
            )
        )
        
        # The standalone Rust router also retains the raw Python handler. Python
        # middleware is applied only when this router is mounted on an app.
        route = RustRoute(
            path=converted_path,
            function=handler,
            method=method,
            doc=handler.__doc__
        )
        self._rust_router.add_route(route)
        self._notify_registration_changed()

    def get(self, path: str, middleware: list[Callable] | None = None, **options):
        """Register a GET route."""
        def decorator(handler: Callable) -> Callable:
            self._add_route("GET", path, handler, middleware, **options)
            return handler
        return decorator
    
    def post(self, path: str, middleware: list[Callable] | None = None, **options):
        """Register a POST route."""
        def decorator(handler: Callable) -> Callable:
            self._add_route("POST", path, handler, middleware, **options)
            return handler
        return decorator
    
    def put(self, path: str, middleware: list[Callable] | None = None, **options):
        """Register a PUT route."""
        def decorator(handler: Callable) -> Callable:
            self._add_route("PUT", path, handler, middleware, **options)
            return handler
        return decorator
    
    def delete(self, path: str, middleware: list[Callable] | None = None, **options):
        """Register a DELETE route."""
        def decorator(handler: Callable) -> Callable:
            self._add_route("DELETE", path, handler, middleware, **options)
            return handler
        return decorator
    
    def patch(self, path: str, middleware: list[Callable] | None = None, **options):
        """Register a PATCH route."""
        def decorator(handler: Callable) -> Callable:
            self._add_route("PATCH", path, handler, middleware, **options)
            return handler
        return decorator
    
    def options(self, path: str, middleware: list[Callable] | None = None, **options):
        """Register an OPTIONS route."""
        def decorator(handler: Callable) -> Callable:
            self._add_route("OPTIONS", path, handler, middleware, **options)
            return handler
        return decorator
    
    def head(self, path: str, middleware: list[Callable] | None = None, **options):
        """Register a HEAD route."""
        def decorator(handler: Callable) -> Callable:
            self._add_route("HEAD", path, handler, middleware, **options)
            return handler
        return decorator
    
    def all(self, path: str, middleware: list[Callable] | None = None, **options):
        """Register a route for all HTTP methods."""
        def decorator(handler: Callable) -> Callable:
            for method in ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]:
                self._add_route(method, path, handler, middleware, **options)
            return handler
        return decorator
    
    def use(self, middleware: Callable) -> Router:
        """
        Add middleware to this router.
        
        Example:
            router.use(auth_middleware)
            router.use(logging_middleware)
        """
        self._assert_registration_open()
        normalized = normalize_middleware(middleware)
        if normalized is None:
            raise TypeError("Router middleware must use (req, res, ctx, next)")
        self._middleware.append(normalized)
        self._notify_registration_changed()
        return self
    
    def error(self, exc_class: type) -> Callable:
        """
        Add an error handler for a specific exception type.
        
        Example:
            @router.error(ValueError)
            def handle_value_error(req, res, error):
                res.status(400).json({"error": str(error)})
        """
        def decorator(handler: Callable) -> Callable:
            self._assert_registration_open()
            self._error_handlers[exc_class] = handler
            self._notify_registration_changed()
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
            self._assert_registration_open()
            # Store param handler
            if not hasattr(self, '_param_handlers'):
                self._param_handlers = {}
            self._param_handlers[name] = handler
            self._notify_registration_changed()
            return handler
        return decorator
    
    def get_routes(self) -> list[tuple[str, str, Callable]]:
        """Get all registered routes."""
        return [(route.method, route.path, route.handler) for route in self._routes]
    
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
    
    def get(self, handler: Callable, **options) -> RouteBuilder:
        """Add GET handler."""
        self.router._add_route("GET", self.path, handler, **options)
        return self
    
    def post(self, handler: Callable, **options) -> RouteBuilder:
        """Add POST handler."""
        self.router._add_route("POST", self.path, handler, **options)
        return self
    
    def put(self, handler: Callable, **options) -> RouteBuilder:
        """Add PUT handler."""
        self.router._add_route("PUT", self.path, handler, **options)
        return self
    
    def delete(self, handler: Callable, **options) -> RouteBuilder:
        """Add DELETE handler."""
        self.router._add_route("DELETE", self.path, handler, **options)
        return self
    
    def patch(self, handler: Callable, **options) -> RouteBuilder:
        """Add PATCH handler."""
        self.router._add_route("PATCH", self.path, handler, **options)
        return self
    
    def options(self, handler: Callable, **options) -> RouteBuilder:
        """Add OPTIONS handler."""
        self.router._add_route("OPTIONS", self.path, handler, **options)
        return self
    
    def head(self, handler: Callable, **options) -> RouteBuilder:
        """Add HEAD handler."""
        self.router._add_route("HEAD", self.path, handler, **options)
        return self
    
    def all(self, handler: Callable, **options) -> RouteBuilder:
        """Add handler for all methods."""
        for method in ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]:
            self.router._add_route(method, self.path, handler, **options)
        return self


__all__ = [
    'RouteBuilder',
    'Router',
]
