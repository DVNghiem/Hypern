from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Self, TypeVar

import msgspec
from typing_extensions import Doc

from hypern._hypern import Context, HealthCheck, ReloadConfig, ReloadManager, Server, SSEStream, StreamingResponse, TaskExecutor, TaskResult
from hypern._hypern import Route as RustRoute
from hypern._hypern import Router as RustRouter
from hypern.exceptions import ExceptionHandler
from hypern.injection import (
    HandlerPlan,
    ProviderRegistry,
    RequestScope,
    Scope,
    compile_handler,
)
from hypern.logfmt import config_basic_logging
from hypern.middleware import normalize_middleware
from hypern.router import Router
from hypern.tasks import set_task_executor

if TYPE_CHECKING:
    from hypern.openapi import OpenAPIGenerator
    from hypern.scheduler import TaskScheduler
    from hypern.websocket import WebSocketRouter

AppType = TypeVar("AppType", bound="Hypern")
HandlerType = Callable[..., None | Awaitable[None]]

# Type alias for middleware (can be Rust middleware object or Python callable)
Middleware = Callable | object

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _PipelineScope:
    """One immutable scope in a compiled Python request pipeline."""

    name: str
    middleware: tuple[Callable, ...]


class Hypern:
    """
    Example:
        app = Hypern()
        
        # Define routes using decorators
        @app.get("/")
        def home(req, res, ctx):
            res.send("Hello World")
        
        @app.get("/users/:id")
        async def get_user(req, res, ctx):
            res.json({"id": req.param("id")})
        
        # Use middleware
        app.use(cors_middleware)
        
        # Mount routers
        api = Router(prefix="/api")
        app.use("/api", api)
        
        # Start server
        app.listen(3000)
    """
    
    def __init__(
        self: Self,
        routes: Annotated[
            list[RustRoute] | None,
            Doc("A list of routes to serve incoming HTTP and WebSocket requests.")
        ] = None,
        debug: bool = False,
        task_workers: int = 4,
        task_queue_size: int = 1000,
        log_level: str = "info",
    ) -> None:
        # set default logging level to INFO if not already set
        config_basic_logging(level=getattr(logging, log_level.upper(), logging.INFO))
        
        # Core routing
        self._router = RustRouter(path="/")
        self._routers: list[tuple[str, Router]] = []

        # Pipeline descriptors are rebuilt only while registration is open,
        # then finalized and frozen when listen() begins.
        self._pipeline_compilers: list[Callable[[], None]] = []
        self._registration_frozen = False
        
        # Middleware (Rust middleware instances or callables)
        self._middleware: list[Callable | object | tuple] = []
        
        # Request lifecycle handlers
        
        # Exception handling
        self._exception_handler = ExceptionHandler()
        self._exception_handler.add_handler(
            msgspec.ValidationError,
            self._handle_validation_error,
        )
        
        # Lifecycle handlers
        self._startup_handlers: list[Callable] = []
        self._shutdown_handlers: list[Callable] = []
        
        # Settings
        self._settings: dict[str, Any] = {}
        self.debug = debug
        
        self._providers = ProviderRegistry()
        
        self._tasks = TaskExecutor(task_workers, task_queue_size)
        
        # Register this app's task executor as the global default
        
        set_task_executor(self._tasks)
        
        # OpenAPI (lazy-loaded)
        self._openapi: OpenAPIGenerator | None = None
        self._openapi_enabled = False
        
        # Graceful shutdown
        self._shutdown_event: asyncio.Event | None = None
        self._running = False
        
        # Backwards compatibility
        self.router = self._router
        self.response_headers: dict[str, str] = {}
        self.start_up_handler = None
        self.shutdown_handler = None
        
        # WebSocket router
        from hypern.websocket import WebSocketRouter as _WSRouter
        self._ws_router: _WSRouter = _WSRouter()
        
        # Task scheduler (lazy-initialised)
        self._scheduler: TaskScheduler | None = None
        
        # Reload / health configuration
        self._reload_config: ReloadConfig | None = None
        self._reload_manager: ReloadManager | None = None
        
        if routes is not None:
            for route in routes:
                wrapped = self._wrap_handler(
                    route.function,
                    route_path=route.path,
                )
                self._router.add_route(
                    route=RustRoute(
                        path=route.path,
                        function=wrapped,
                        method=route.method,
                        doc=route.doc,
                    )
                )
  
    @property
    def tasks(self) -> TaskExecutor | None:
        """Access the background task executor."""
        return self._tasks
    
    @property
    def openapi(self) -> OpenAPIGenerator | None:
        """Access the OpenAPI generator (if enabled)."""
        return self._openapi
    
    def set(self, key: str, value: Any) -> Hypern:
        """
        Set an application setting.
        
        Example:
            app.set("views", "./templates")
            app.set("json spaces", 2)
        """
        self._settings[key] = value
        return self
    
    def get_setting(self, key: str, default: Any = None) -> Any:
        """
        Get an application setting.
        
        Example:
            views_dir = app.get_setting("views", "./views")
        """
        return self._settings.get(key, default)
    
    def enable(self, key: str) -> Hypern:
        """Enable a boolean setting."""
        self._settings[key] = True
        return self
    
    def disable(self, key: str) -> Hypern:
        """Disable a boolean setting."""
        self._settings[key] = False
        return self
    
    def enabled(self, key: str) -> bool:
        """Check if a setting is enabled."""
        return self._settings.get(key, False) is True
    
    def disabled(self, key: str) -> bool:
        """Check if a setting is disabled."""
        return not self.enabled(key)
    
    def provide(
        self,
        key: object,
        provider: object,
        *,
        scope: Scope = "singleton",
    ) -> Hypern:
        """Register a provider for compiled handler injection."""
        self._assert_registration_open()
        self._providers.provide(key, provider, scope=scope)
        return self
    
    def background(
        self, 
        delay_seconds: float | None = None
    ) -> Callable:
        """
        Decorator to run a function as a background task.
        
        Note: This delegates to the global background decorator from hypern.tasks.
        You can also use `from hypern import background` directly in any module.
        
        Args:
            delay_seconds: Optional delay in seconds before executing the task
        
        Example:
            @app.background()  # Execute immediately
            def send_email(to: str, subject: str):
                # This runs in background
                ...
            
            @app.background(delay_seconds=60)  # Execute after 60 seconds
            def send_delayed_email(to: str, subject: str):
                ...
            
            @app.post("/notify")
            async def notify(req, res, ctx):
                send_email("user@example.com", "Hello!")
                res.json({"status": "queued"})
        """
        from hypern.tasks import background as global_background
        return global_background(delay_seconds=delay_seconds)
    
    def submit_task(
        self, 
        handler: Callable, 
        args: tuple = (),
        delay_seconds: float | None = None
    ) -> str | None:
        """
        Submit a background task programmatically.
        
        Note: This delegates to the global submit_task from hypern.tasks.
        You can also use `from hypern import submit_task` directly in any module.
        
        Args:
            handler: The function to run in the background
            args: Arguments to pass to the function
            delay_seconds: Optional delay in seconds before executing the task
        
        Returns:
            task_id: The ID of the submitted task
        
        Example:
            task_id = app.submit_task(process_data, (data,))
            # With delay:
            task_id = app.submit_task(process_data, (data,), delay_seconds=300)
        """
        from hypern.tasks import submit_task as global_submit_task
        return global_submit_task(handler, args=args, delay_seconds=delay_seconds)
    
    def get_task(self, task_id: str) -> TaskResult | None:
        """
        Get the result of a background task.
        
        Note: This delegates to the global get_task from hypern.tasks.
        You can also use `from hypern import get_task` directly in any module.
        
        Example:
            result = app.get_task(task_id)
            if result.is_success():
                print(result.result)
        """
        from hypern.tasks import get_task as global_get_task
        return global_get_task(task_id)
    
    def sse(self, buffer_size: int = 100) -> SSEStream:
        """
        Create an SSE stream for sending server-sent events.
        
        Example:
            @app.get("/events")
            async def events(req, res, ctx):
                # Create SSE events
                from hypern import SSEEvent
                events = [
                    SSEEvent("Hello", event="greeting"),
                    SSEEvent("World", event="message")
                ]
                # Send as batched SSE response
                res.sse(events)
                
            # Or use the SSEStream directly:
            @app.get("/stream")
            async def stream_events(req, res, ctx):
                stream = app.sse()
                stream.send_event("message", "Hello!")
                stream.send_data("Plain data")
                # Note: This creates events that can be collected
                # For batched response, use res.sse(events)
        """
        # Return a new SSEStream instance that can be used to build events
        return SSEStream(buffer_size)
    
    def stream(
        self, 
        content_type: str = "application/octet-stream",
        buffer_size: int = 100
    ) -> StreamingResponse:
        """
        Create a streaming response builder.
        
        Example:
            @app.get("/download")
            async def download(req, res, ctx):
                stream = app.stream("text/plain")
                stream.write_str("Chunk 1")
                stream.write_str("Chunk 2")
                # The stream collects data for response
        """
        # Return a new StreamingResponse instance
        return StreamingResponse(content_type, buffer_size)
    
    # ------------------------------------------------------------------
    # WebSocket support
    # ------------------------------------------------------------------
    
    def ws(self, path: str, **options) -> Callable:
        """
        Decorator to register a WebSocket handler.
        
        Example:
            @app.ws("/chat")
            async def chat(ws):
                await ws.accept()
                while True:
                    msg = await ws.receive_text()
                    await ws.send_text(f"echo: {msg}")
        """
        def decorator(handler: Callable) -> Callable:
            self._assert_registration_open()
            self._ws_router.add_route(path, handler, **options)
            return handler
        return decorator
    
    @property
    def ws_router(self) -> WebSocketRouter:
        """Access the WebSocket router."""
        return self._ws_router
    
    @property
    def scheduler(self) -> TaskScheduler:
        """
        Access or create the task scheduler.
        
        The scheduler is lazily created on first access.
        
        Example:
            @app.scheduler.cron("0 3 * * *")
            def nightly_cleanup():
                ...
            
            @app.scheduler.interval(seconds=30)
            def health_check():
                ...
        """
        if self._scheduler is None:
            from hypern.scheduler import TaskScheduler
            self._scheduler = TaskScheduler()
        return self._scheduler
    
    def setup_logging(
        self,
        level: str = "info",
        log_request: bool = True,
        log_response: bool = True,
        queue_size: int = 10_000,
        skip_paths: list[str] | None = None,
    ) -> Hypern:
        """
        Configure logging behavior from the Rust layer.
        
        Uses a high-performance lock-free log queue implemented in Rust.
        Request/response logging can be independently enabled or disabled.
        
        Args:
            level: Minimum log level - "trace", "debug", "info", "warn", "error", "off"
            log_request: Log incoming requests (method, path) (default: True)
            log_response: Log outgoing responses (status, duration) (default: True)
            queue_size: Internal log queue capacity (default: 10000)
            skip_paths: Paths to exclude from request/response logging
        
        Example:
            # Default: info level with request/response logging
            app.setup_logging()
            
            # Verbose debug logging
            app.setup_logging(level="debug")
            
            # Disable request/response logging (only app-level logs)
            app.setup_logging(log_request=False, log_response=False)
            
            # Production: errors only, no request/response noise
            app.setup_logging(level="error", log_request=False, log_response=False)
            
            # Disable all logging
            app.setup_logging(level="off")
        """
        kwargs = {
            "level": level,
            "log_request": log_request,
            "log_response": log_response,
            "queue_size": queue_size,
        }
        if skip_paths is not None:
            kwargs["skip_paths"] = skip_paths
        return self
    
    def setup_reload(
        self,
        drain_timeout_secs: int = 30,
        startup_grace_secs: int = 2,
        health_probes: bool = True,
        health_path: str = "/_health",
    ) -> Hypern:
        """
        Configure zero-downtime reload and health probes.
        
        Args:
            drain_timeout_secs: Max seconds to wait for in-flight requests during graceful reload
            startup_grace_secs: Seconds to wait before marking new workers as healthy
            health_probes: Whether to enable built-in health probe endpoints
            health_path: Path prefix for health probes (default "/health")
        
        Health probe endpoints (when enabled):
            - GET {health_path}          → Full health status JSON
            - GET {health_path}/live     → Liveness probe (is process alive?)
            - GET {health_path}/ready    → Readiness probe (accepting traffic?)
            - GET {health_path}/startup  → Startup probe (finished starting?)
        
        Reload signals (Unix):
            - SIGUSR1 → Graceful reload (drain in-flight requests, then restart workers)
            - SIGUSR2 → Hot reload (immediate restart, for development)
        
        Example:
            app = Hypern()
            app.setup_reload(
                drain_timeout_secs=60,
                health_probes=True,
                health_path="/health",
            )
            
            # Check health:
            # curl http://localhost:3000/health
            # curl http://localhost:3000/health/ready
            
            # Graceful reload (from shell):
            # kill -USR1 <pid>
            
            # Hot reload (from shell):
            # kill -USR2 <pid>
        """
        self._reload_config = ReloadConfig(
            drain_timeout_secs=drain_timeout_secs,
            startup_grace_secs=startup_grace_secs,
            health_probes_enabled=health_probes,
            health_path_prefix=health_path,
        )
        return self
    
    @property
    def health(self) -> HealthCheck | None:
        """
        Access the health check instance (available after server starts).
        
        Example:
            if app.health and app.health.is_ready():
                print(f"Healthy, {app.health.in_flight()} requests in flight")
        """
        if self._reload_manager is not None:
            return self._reload_manager.health()
        return None
    
    @property
    def reload_manager(self) -> ReloadManager | None:
        """
        Access the reload manager (available after server starts).
        
        Example:
            # Programmatic graceful reload
            app.reload_manager.graceful_reload()
            
            # Check status
            print(app.reload_manager.status())
            print(app.reload_manager.in_flight())
        """
        return self._reload_manager
    
    def graceful_reload(self):
        """
        Trigger a graceful reload: drain in-flight requests, then restart workers.
        
        Equivalent to sending SIGUSR1 to the parent process.
        """
        if self._reload_manager is not None:
            self._reload_manager.graceful_reload()
        else:
            import os
            os.kill(os.getpid(), signal.SIGUSR1)
    
    def hot_reload_signal(self):
        """
        Trigger an immediate hot reload (development mode).
        
        Equivalent to sending SIGUSR2 to the parent process.
        """
        if self._reload_manager is not None:
            self._reload_manager.hot_reload()
        else:
            import os
            os.kill(os.getpid(), signal.SIGUSR2)
    
    def setup_openapi(
        self,
        title: str = "API Documentation",
        version: str = "1.0.0",
        description: str = "",
        docs_path: str = "/docs",
        redoc_path: str = "/redoc",
        openapi_path: str = "/openapi.json",
    ) -> Hypern:
        """
        Enable OpenAPI/Swagger documentation.
        
        Example:
            app.setup_openapi(
                title="My API",
                version="1.0.0",
                description="My awesome API",
            )
            
            # Access documentation at:
            # - /docs (Swagger UI)
            # - /redoc (ReDoc)
            # - /openapi.json (OpenAPI spec)
        """
        from hypern.openapi import OpenAPIGenerator, setup_openapi_routes
        
        self._openapi = OpenAPIGenerator(
            title=title,
            version=version,
            description=description,
        )
        self._openapi_enabled = True
        
        # Add routes
        setup_openapi_routes(
            self,
            self._openapi,
            docs_path=docs_path,
            redoc_path=redoc_path,
            spec_path=openapi_path,
        )
        
        return self
    
    def _add_route(self, method: str, endpoint: str, handler: Callable[..., Any]) -> None:
        """Register an application-owned route wrapper with the Rust router."""
        self._assert_registration_open()

        if endpoint and not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        if not endpoint:
            endpoint = "/"

        route = RustRoute(path=endpoint, function=handler, method=method.upper())
        self._router.add_route(route=route)

    def add_route(self, method: str, endpoint: str, handler: Callable[..., Any]):
        """
        Add a route to the router.
        
        Args:
            method: The HTTP method (GET, POST, PUT, DELETE, etc.)
            endpoint: The endpoint path (e.g., "/users/:id")
            handler: The function that handles requests
        """
        wrapped = self._wrap_handler(handler, route_path=endpoint)
        self._add_route(method, endpoint, wrapped)
    
    def get_routes(self) -> list:
        """
        Return a list of all registered routes.
        
        Each route is a dict with keys: method, path, handler, doc.
        
        Example:
            routes = app.get_routes()
            for r in routes:
                print(f"{r['method']} {r['path']} -> {r['handler']}")
        """
        return self._router.get_routes_info_py()
        
        # Register with OpenAPI if enabled
        # Note: OpenAPI registration happens during spec generation
        # if self._openapi_enabled and self._openapi:
        #     self._openapi.add_route(method, endpoint, handler)
    
    def get(self, path: str, middleware: list[Callable] | None = None, **options):
        """
        Register a GET route.
        
        Example:
            @app.get("/users")
            async def get_users(req, res, ctx):
                res.json([{"id": 1}])
        """
        def decorator(handler: Callable[..., Any]):
            wrapped = self._wrap_handler(handler, middleware, route_path=path)
            self._add_route("GET", path, wrapped)
            return handler
        return decorator
    
    def post(self, path: str, middleware: list[Callable] | None = None, **options):
        """
        Register a POST route.
        
        Example:
            @app.post("/users")
            async def create_user(req, res, ctx):
                body = req.json()
                res.status(201).json(body)
        """
        def decorator(handler: Callable[..., Any]):
            wrapped = self._wrap_handler(handler, middleware, route_path=path)
            self._add_route("POST", path, wrapped)
            return handler
        return decorator
    
    def put(self, path: str, middleware: list[Callable] | None = None, **options):
        """Register a PUT route."""
        def decorator(handler: Callable[..., Any]):
            wrapped = self._wrap_handler(handler, middleware, route_path=path)
            self._add_route("PUT", path, wrapped)
            return handler
        return decorator
    
    def delete(self, path: str, middleware: list[Callable] | None = None, **options):
        """Register a DELETE route."""
        def decorator(handler: Callable[..., Any]):
            wrapped = self._wrap_handler(handler, middleware, route_path=path)
            self._add_route("DELETE", path, wrapped)
            return handler
        return decorator
    
    def patch(self, path: str, middleware: list[Callable] | None = None, **options):
        """Register a PATCH route."""
        def decorator(handler: Callable[..., Any]):
            wrapped = self._wrap_handler(handler, middleware, route_path=path)
            self._add_route("PATCH", path, wrapped)
            return handler
        return decorator
    
    def options(self, path: str, middleware: list[Callable] | None = None, **options):
        """Register an OPTIONS route."""
        def decorator(handler: Callable[..., Any]):
            wrapped = self._wrap_handler(handler, middleware, route_path=path)
            self._add_route("OPTIONS", path, wrapped)
            return handler
        return decorator
    
    def head(self, path: str, middleware: list[Callable] | None = None, **options):
        """Register a HEAD route."""
        def decorator(handler: Callable[..., Any]):
            wrapped = self._wrap_handler(handler, middleware, route_path=path)
            self._add_route("HEAD", path, wrapped)
            return handler
        return decorator
    
    def all(self, path: str, middleware: list[Callable] | None = None, **options):
        """
        Register a route for all HTTP methods.
        
        Example:
            @app.all("/api/*")
            async def api_handler(req, res, ctx):
                res.json({"method": req.method})
        """
        def decorator(handler: Callable[..., Any]):
            wrapped = self._wrap_handler(handler, middleware, route_path=path)
            for method in ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]:
                self._add_route(method, path, wrapped)
            return handler
        return decorator
    
    def route(self, path: str):
        """
        Create a route builder for chaining methods.
        
        Example:
            app.route("/users")
                .get(get_users)
                .post(create_user)
        """
        
        class AppRouteBuilder:
            def __init__(self_rb, app, path):
                self_rb.app = app
                self_rb.path = path
            
            def get(self_rb, handler):
                self_rb.app.get(self_rb.path)(handler)
                return self_rb
            
            def post(self_rb, handler):
                self_rb.app.post(self_rb.path)(handler)
                return self_rb
            
            def put(self_rb, handler):
                self_rb.app.put(self_rb.path)(handler)
                return self_rb
            
            def delete(self_rb, handler):
                self_rb.app.delete(self_rb.path)(handler)
                return self_rb
            
            def patch(self_rb, handler):
                self_rb.app.patch(self_rb.path)(handler)
                return self_rb
            
            def all(self_rb, handler):
                wrapped = self_rb.app._wrap_handler(
                    handler,
                    route_path=self_rb.path,
                )
                for method in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
                    self_rb.app._add_route(method, self_rb.path, wrapped)
                return self_rb
        
        return AppRouteBuilder(self, path)
    
    def static(
        self,
        url_path: str = "/static",
        directory: str = "static",
        index: str = "index.html"
    ) -> Hypern:
        """
        Serve static files from a directory.
        
        Similar to Express: app.use('/static', express.static('public'))
        
        Args:
            url_path: URL path prefix for static files
            directory: Directory to serve files from
            index: Default file to serve for directory requests
        
        Example:
            app.static("/assets", "public")  # Serve /assets/* from ./public
            app.static()  # Serve /static/* from ./static
        """
        import mimetypes
        import os
        
        # Ensure directory exists
        if not os.path.isdir(directory):
            raise ValueError(f"Static directory not found: {directory}")
        
        # Normalize paths
        url_path = url_path.rstrip('/')
        directory = os.path.abspath(directory)
        
        @self.get(f"{url_path}/*filepath")
        def serve_static(req, res, ctx):
            # Get the filepath from the wildcard
            filepath = req.param("filepath") or ""
            
            # Prevent directory traversal
            if ".." in filepath:
                res.status(403).send("Forbidden")
                return
            
            # Construct full file path
            full_path = os.path.join(directory, filepath)
            
            # Check if it's a directory
            if os.path.isdir(full_path):
                # Try to serve index file
                full_path = os.path.join(full_path, index)
            
            # Check if file exists
            if not os.path.isfile(full_path):
                res.status(404).send("Not Found")
                return
            
            # Guess content type
            content_type, _ = mimetypes.guess_type(full_path)
            if content_type is None:
                content_type = "application/octet-stream"
            
            # Read and serve file
            try:
                with open(full_path, "rb") as f:
                    content = f.read()
                
                res.header("Content-Type", content_type)
                res.header("Content-Length", str(len(content)))
                
                # Add cache control for static files
                res.header("Cache-Control", "public, max-age=3600")
                
                res.send(content)
            except OSError:
                res.status(500).send("Error reading file")
        
        return self
    
    def use(
        self, 
        path_or_middleware: str | Middleware | Callable | Router, 
        middleware_or_router: Middleware | Callable | Router | None = None
    ) -> Hypern:
        """
        Use middleware or mount a router.
        
        Example:
            # Global middleware
            app.use(cors_middleware)
            app.use(LoggingMiddleware())
            
            # Mounted router
            api = Router(prefix="/api")
            app.use("/api", api)
            
            # Path-specific middleware
            app.use("/admin", auth_middleware)
        """
        from hypern.middleware import MiddlewareStack

        self._assert_registration_open()

        if isinstance(path_or_middleware, str):
            path = path_or_middleware
            target = middleware_or_router
            
            if isinstance(target, Router):
                # Mount router at path
                self._mount_router(path, target)
            elif isinstance(target, MiddlewareStack):
                for mw in target:
                    self.use(path, mw)
            else:
                # Path-specific middleware
                self._register_middleware(target, path)
        else:
            target = path_or_middleware
            
            if isinstance(target, Router):
                # Mount router at root
                self._mount_router("", target)
            elif isinstance(target, MiddlewareStack):
                for mw in target:
                    self.use(mw)
            else:
                # Global middleware
                self._register_middleware(target)
        
        return self

    def _register_middleware(self, target: Any, path: str | None = None):
        """Register middleware or hook, optionally with a path."""
        self._assert_registration_open()

        descriptor = normalize_middleware(target)
        if descriptor is not None:
            target = descriptor

        if path:
            self._middleware.append((path, target))
        else:
            self._middleware.append(target)
        self._refresh_pipeline_descriptors()
    
    def mount(
        self,
        router_or_prefix: str | Router,
        router: Router | None = None,
    ) -> Hypern:
        """
        Mount a router on the application.
        
        Example:
            # Mount using router's own prefix
            api_v1 = Router(prefix="/api/v1")
            app.mount(api_v1)
            
            # Mount with explicit prefix
            app.mount("/api/v2", api_v2)
        """
        self._assert_registration_open()

        if isinstance(router_or_prefix, Router):
            # app.mount(router) - use router's own prefix
            self._mount_router(router_or_prefix.prefix, router_or_prefix)
        elif isinstance(router_or_prefix, str) and isinstance(router, Router):
            # app.mount("/prefix", router)
            self._mount_router(router_or_prefix, router)
        else:
            raise TypeError(
                "Expected mount(router) or mount(prefix, router). "
                f"Got mount({type(router_or_prefix).__name__}, {type(router).__name__})"
            )
        return self

    def _mount_router(self, prefix: str, router: Router):
        """Mount a router at a path prefix."""
        self._assert_registration_open()
        self._routers.append((prefix, router))
        mounted_route_count = 0

        def sync_router_registration() -> None:
            nonlocal mounted_route_count
            self._assert_registration_open()

            # The application owns the only Python wrapper for mounted routes.
            # A router may add routes after mounting while registration is open.
            for route in router._routes[mounted_route_count:]:
                full_path = prefix + route.path if prefix else route.path
                wrapped = self._wrap_handler(
                    route.handler,
                    route.middleware,
                    router=router,
                    route_path=full_path,
                    path_parameter_names=route.path_parameter_names,
                )
                self._add_route(route.method, full_path, wrapped)
            mounted_route_count = len(router._routes)
            self._refresh_pipeline_descriptors()

        router._register_change_listener(sync_router_registration)
        sync_router_registration()
    
    def on_startup(self, handler: Callable) -> Callable:
        """
        Register a startup handler.
        
        Example:
            @app.on_startup
            async def startup():
                service = await create_service()
                await service.start()
        """
        self._assert_registration_open()
        self._startup_handlers.append(handler)
        return handler
    
    def on_shutdown(self, handler: Callable) -> Callable:
        """
        Register a shutdown handler.
        
        Example:
            service = ApplicationService()

            @app.on_shutdown
            async def shutdown():
                await service.aclose()
        """
        self._assert_registration_open()
        self._shutdown_handlers.append(handler)
        return handler
    
    def errorhandler(self, exc_class: type[Exception]) -> Callable:
        """
        Register an exception handler.
        
        Example:
            @app.errorhandler(NotFound)
            def handle_not_found(req, res, error):
                res.status(404).json({"error": "Not found"})
            
            @app.errorhandler(Exception)
            def handle_all(req, res, error):
                res.status(500).json({"error": "Server error"})
        """
        self._assert_registration_open()

        def decorator(handler: Callable) -> Callable:
            self._assert_registration_open()
            self._exception_handler.add_handler(exc_class, handler)
            return handler

        return decorator
    
    def register_error_handler(self, exc_class: type[Exception], handler: Callable):
        """Register an exception handler programmatically."""
        self._assert_registration_open()
        self._exception_handler.add_handler(exc_class, handler)

    def _assert_registration_open(self) -> None:
        """Reject setup mutations after listen() freezes the application."""
        if self._registration_frozen:
            raise RuntimeError("application registration is frozen after listen()")

    def _refresh_pipeline_descriptors(self) -> None:
        """Recompile route descriptors after a setup-time pipeline mutation."""
        for compile_descriptor in self._pipeline_compilers:
            compile_descriptor()

    def _freeze_registration(self) -> None:
        """Compile final descriptors and freeze the app and mounted routers."""
        if self._registration_frozen:
            return

        self._providers.freeze()
        self._refresh_pipeline_descriptors()
        for _, router in self._routers:
            router._freeze_registration()
        self._registration_frozen = True

    @staticmethod
    def _response_is_terminal(res: Any) -> bool:
        """Return whether the response has become terminal for inward stages."""
        is_sent = getattr(res, "is_sent", None)
        if callable(is_sent):
            return bool(is_sent())
        if is_sent is not None:
            return bool(is_sent)
        return bool(getattr(res, "finished", False))

    @staticmethod
    def _handle_validation_error(req: Any, res: Any, error: Exception) -> None:
        """Render request-binding validation failures as bad requests."""
        to_dict = getattr(error, "to_dict", None)
        payload = to_dict() if callable(to_dict) else {"message": str(error)}
        res.status(400).json(payload)

    def _python_middleware_for(self, route_path: str) -> tuple[Callable, ...]:
        """Compile Python middleware for a registered route path."""
        if route_path and not route_path.startswith("/"):
            route_path = "/" + route_path
        selected: list[Callable] = []
        for entry in self._middleware:
            if isinstance(entry, tuple):
                path_prefix, middleware = entry
                if route_path.startswith(path_prefix) and callable(middleware):
                    selected.append(middleware)
            elif callable(entry):
                # Rust middleware objects are not callable and remain owned by
                # the server's Tower pipeline.
                selected.append(entry)
        return tuple(selected)

    def _compile_pipeline_scopes(
        self,
        middleware: tuple[Callable, ...],
        *,
        router: Router | None,
        route_path: str,
    ) -> tuple[_PipelineScope, ...]:
        """Build one immutable descriptor for a registered route."""
        scopes = [
            _PipelineScope(
                name="app",
                middleware=self._python_middleware_for(route_path),
            )
        ]
        if router is not None:
            scopes.append(
                _PipelineScope(
                    name="router",
                    middleware=tuple(router._middleware),
                )
            )
        scopes.append(
            _PipelineScope(
                name="route",
                middleware=middleware,
            )
        )
        return tuple(scopes)

    async def _run_middleware_chain(
        self,
        middleware: list[Callable] | tuple[Callable, ...],
        req: Any,
        res: Any,
        ctx: Any,
        continuation: Callable[[], Awaitable[None]],
    ) -> None:
        """Run async middleware in registration order around a continuation."""
        async def dispatch(index: int) -> None:
            if self._response_is_terminal(res):
                return
            if index == len(middleware):
                await continuation()
                return

            next_called = False

            async def next_fn() -> None:
                nonlocal next_called
                if next_called:
                    raise RuntimeError("middleware next_fn may only be awaited once")
                next_called = True
                if not self._response_is_terminal(res):
                    await dispatch(index + 1)

            result = middleware[index](req, res, ctx, next_fn)
            if not inspect.isawaitable(result):
                # Compatibility for legacy synchronous middleware that has
                # already completed a terminal short-circuit. It cannot enter
                # another pipeline stage; every non-terminal middleware call
                # still has to produce an awaitable.
                if self._response_is_terminal(res):
                    return
                raise TypeError(
                    "Python middleware must return an awaitable and use "
                    "(req, res, ctx, next)"
                )
            await result

        await dispatch(0)

    async def _execute_python_pipeline(
        self,
        handler_plan: HandlerPlan,
        scopes: tuple[_PipelineScope, ...],
        req: Any,
        res: Any,
        ctx: Any,
        request_scope: RequestScope,
    ) -> Any:
        """Execute the canonical app -> router -> route Python pipeline."""
        handler_result: Any = None

        async def execute_scope(index: int) -> None:
            nonlocal handler_result
            scope = scopes[index]
            async def continue_inward() -> None:
                nonlocal handler_result
                if self._response_is_terminal(res):
                    return
                if index + 1 < len(scopes):
                    await execute_scope(index + 1)
                elif handler_plan.requires_async:
                    handler_result = await handler_plan.invoke(
                        req,
                        res,
                        ctx,
                        request_scope,
                    )
                else:
                    handler_result = handler_plan.invoke_sync(
                        req,
                        res,
                        ctx,
                        request_scope,
                    )

            await self._run_middleware_chain(
                scope.middleware,
                req,
                res,
                ctx,
                continue_inward,
            )

        await execute_scope(0)
        return handler_result

    def _wrap_handler(
        self,
        handler: Callable,
        middleware: list[Callable] | tuple[Callable, ...] | None = None,
        *,
        router: Router | None = None,
        route_path: str = "/",
        path_parameter_names: frozenset[str] | None = None,
    ) -> Callable:
        """Create the application-owned wrapper for one Python route pipeline."""
        self._assert_registration_open()
        route_middleware = tuple(middleware or ())
        scopes: tuple[_PipelineScope, ...] = ()
        handler_plan: HandlerPlan | None = None
        parameter_names = Router._path_parameter_names(route_path)
        if path_parameter_names is not None:
            parameter_names |= path_parameter_names

        def compile_descriptor() -> None:
            nonlocal handler_plan, scopes
            scopes = self._compile_pipeline_scopes(
                route_middleware,
                router=router,
                route_path=route_path,
            )
            if self._providers._frozen:
                handler_plan = compile_handler(
                    handler,
                    path_parameter_names=parameter_names,
                    registry=self._providers,
                )

        compile_descriptor()
        self._pipeline_compilers.append(compile_descriptor)

        async def execute_with_loop(req: Any, res: Any) -> Any:
            if handler_plan is None:
                raise RuntimeError(
                    "application registration must be frozen before handling requests"
                )
            ctx = Context()
            request_scope = RequestScope(self._providers)
            result: Any = None
            unhandled_error: Exception | None = None
            exception_handler_error: Exception | None = None

            try:
                result = await self._execute_python_pipeline(
                    handler_plan,
                    scopes,
                    req,
                    res,
                    ctx,
                    request_scope,
                )
                if result is not None and not self._response_is_terminal(res):
                    res.send(result)
            except Exception as exc:  # noqa: BLE001
                response_was_terminal = self._response_is_terminal(res)
                try:
                    await self._exception_handler.handle_exception(req, res, exc)
                except Exception as handler_exc:  # noqa: BLE001
                    unhandled_error = exc
                    exception_handler_error = handler_exc
                else:
                    response_is_terminal = self._response_is_terminal(res)
                    if response_was_terminal or not response_is_terminal:
                        unhandled_error = exc
            if unhandled_error is not None:
                raise unhandled_error.with_traceback(unhandled_error.__traceback__) from exception_handler_error
            return result

        @functools.wraps(handler)
        async def wrapped(req, res):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(execute_with_loop(req, res))
            return await execute_with_loop(req, res)
        
        return wrapped
    
    async def _run_startup_handlers(self):
        """Run all startup handlers."""
        for handler in self._startup_handlers:
            if inspect.iscoroutinefunction(handler):
                await handler()
            else:
                handler()
    
    async def _run_shutdown_handlers(self):
        """Run all shutdown handlers."""
        for handler in self._shutdown_handlers:
            try:
                if inspect.iscoroutinefunction(handler):
                    await handler()
                else:
                    handler()
            except Exception as e:  # noqa: BLE001
                print(f"Error in shutdown handler: {e}")
    
    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            print(f"\nReceived signal {signum}, shutting down gracefully...")
            self._running = False
            if self._shutdown_event:
                self._shutdown_event.set()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def listen(
        self,
        port: int = 3000,
        host: str = '0.0.0.0',
        callback: Callable | None = None,
        **kwargs
    ):
        """
        Start the server.
        
        Example:
            app.listen(3000)
            app.listen(3000, "127.0.0.1")
            app.listen(3000, callback=lambda: print("Server running on port 3000"))
        """
        self._freeze_registration()

        if callback:
            callback()
        else:
            print(f"🚀 Hypern server running at http://{host}:{port}")
            if self._openapi_enabled:
                print(f"📚 API docs available at http://{host}:{port}/docs")
        
        self.start(
            host=host,
            port=port,
            **kwargs
        )
    
    def start(
        self,
        host: str = '0.0.0.0',
        port: int = 5000,
        num_processes: int = 1,
        workers_threads: int = 1,
        max_blocking_threads: int = 16,
        max_connections: int = 10000,
    ):
        """
        Start the server with full configuration.
        
        Args:
            host: The host to bind to
            port: The port to listen on
            num_processes: Number of worker processes
            workers_threads: Number of worker threads per process
            max_blocking_threads: Max blocking threads for Python handlers
            max_connections: Max concurrent connections
        """
        self._freeze_registration()
        self._running = True
        self._setup_signal_handlers()
        
        # Run startup handlers synchronously before starting server
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._run_startup_handlers())
        finally:
            loop.close()
        
        # Auto-start the scheduler if it was configured
        if self._scheduler is not None and not self._scheduler.is_running:
            self._scheduler.start()
        
        try:
            server = Server()
            server.set_router(router=self._router)
            
            # Configure reload / health probes
            if self._reload_config is not None:
                server.set_reload_config(self._reload_config)
            else:
                # Default: enable health probes
                server.set_reload_config(ReloadConfig())
            
            # Register Rust middleware
            for mw in self._middleware:
                # Skip path-specific middleware tuples and Python callables
                if isinstance(mw, tuple) or callable(mw):
                    continue
                    
                # Register Rust middleware objects (CORS, SecurityHeaders, etc.)
                server.use_middleware(mw)
            
            server.start(
                host=host,
                port=port,
                num_processes=num_processes,
                workers_threads=workers_threads,
                max_blocking_threads=max_blocking_threads,
                max_connections=max_connections,
            )
            
            # Store reload manager reference after start
            self._reload_manager = server.get_reload_manager()
        finally:
            # Run shutdown handlers
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self._run_shutdown_handlers())
            finally:
                loop.close()
            
            # Stop task executor
            if self._tasks is not None:
                self._tasks.shutdown()
            
            # Stop scheduler
            if self._scheduler is not None:
                self._scheduler.stop()
    
    def run_dev(
        self,
        port: int = 3000,
        host: str = '0.0.0.0',
        reload: bool = True,
        reload_dirs: list[str] | None = None,
        reload_delay: float = 0.5,
        **kwargs
    ):
        """
        Start the server in development mode with auto-reload.
        
        Args:
            port: The port to listen on
            host: The host to bind to
            reload: Whether to enable auto-reload on file changes
            reload_dirs: Directories to watch for changes (default: current directory)
            reload_delay: Delay in seconds before reloading (debounce)
            **kwargs: Additional arguments passed to start()
        
        Example:
            app.run_dev(
                port=3000,
                reload=True,
                reload_dirs=["./src", "./templates"]
            )
        """
        import os
        import subprocess
        import sys
        
        if not reload:
            # No reload, just start normally
            print(f"🚀 Hypern dev server running at http://{host}:{port}")
            self.start(host=host, port=port, **kwargs)
            return
        
        # Use watchdog for file watching if available, otherwise use polling
        try:
            from watchdog.events import FileModifiedEvent, FileSystemEventHandler
            from watchdog.observers import Observer
            
            watch_dirs = reload_dirs or ["."]
            
            class ReloadHandler(FileSystemEventHandler):
                def __init__(self_handler, process):
                    self_handler.process = process
                    self_handler.last_reload = 0
                
                def should_reload(self_handler, path: str) -> bool:
                    # Only reload on Python file changes
                    return path.endswith('.py')
                
                def on_modified(self_handler, event):
                    import time
                    if not isinstance(event, FileModifiedEvent):
                        return
                    if not self_handler.should_reload(event.src_path):
                        return
                    
                    # Debounce
                    now = time.time()
                    if now - self_handler.last_reload < reload_delay:
                        return
                    self_handler.last_reload = now
                    
                    print(f"\n🔄 File changed: {event.src_path}")
                    print("   Reloading server...")
                    
                    # Restart the process
                    self_handler.process.terminate()
                    self_handler.process.wait()
                    self_handler.process = subprocess.Popen(
                        [sys.executable] + sys.argv,
                        env={**os.environ, '_HYPERN_CHILD': '1'}
                    )
            
            # Check if we're the child process
            if os.environ.get('_HYPERN_CHILD'):
                # We're the child, just run the server
                print(f"🚀 Hypern dev server running at http://{host}:{port} (with auto-reload)")
                if self._openapi_enabled:
                    print(f"📚 API docs available at http://{host}:{port}/docs")
                self.start(host=host, port=port, num_processes=1, **kwargs)
                return
            
            # We're the parent, start the child and watch for changes
            print("🔧 Starting Hypern in development mode...")
            print(f"   Watching directories: {watch_dirs}")
            
            process = subprocess.Popen(
                [sys.executable] + sys.argv,
                env={**os.environ, '_HYPERN_CHILD': '1'}
            )
            
            handler = ReloadHandler(process)
            observer = Observer()
            
            for watch_dir in watch_dirs:
                if os.path.isdir(watch_dir):
                    observer.schedule(handler, watch_dir, recursive=True)
            
            observer.start()
            
            try:
                while True:
                    import time
                    time.sleep(1)
                    # Check if child process is still running
                    if process.poll() is not None:
                        # Child exited, restart it
                        print("\n⚠️  Server stopped, restarting...")
                        process = subprocess.Popen(
                            [sys.executable] + sys.argv,
                            env={**os.environ, '_HYPERN_CHILD': '1'}
                        )
                        handler.process = process
            except KeyboardInterrupt:
                print("\n👋 Stopping development server...")
                observer.stop()
                process.terminate()
                process.wait()
            
            observer.join()
            
        except ImportError:
            # Watchdog not available, use simple restart mechanism
            print("⚠️  watchdog package not installed. Install with: pip install watchdog")
            print("   Running without auto-reload...")
            print(f"🚀 Hypern server running at http://{host}:{port}")
            self.start(host=host, port=port, **kwargs)
    
def create_app(**kwargs) -> Hypern:
    """
    Factory function to create a Hypern application.
    
    Example:
        app = create_app(debug=True)
    """
    return Hypern(**kwargs)


def hypern() -> Hypern:
    """
    Create a new Hypern application.
    
    Example:
        from hypern import hypern
        app = hypern()
    """
    return Hypern()


__all__ = [  # noqa: PLE0604
    Hypern,
    'create_app',
    'hypern',
]
