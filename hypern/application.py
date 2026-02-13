from __future__ import annotations

import asyncio
import functools
import signal
from typing import (
    Any, Callable, Dict, List, Optional, Type, TypeVar, Union, 
    Awaitable, TYPE_CHECKING
)

from typing_extensions import Annotated, Doc

from hypern._hypern import Route as RustRoute
from hypern._hypern import Router as RustRouter
from hypern._hypern import Server
from hypern.exceptions import ExceptionHandler
from hypern.router import Router
from hypern._hypern import DIContainer, TaskExecutor, TaskResult
from hypern._hypern import SSEStream, StreamingResponse

from hypern.database import Database as _Database, finalize_db as _finalize_db
from hypern._hypern import get_db as _get_db

if TYPE_CHECKING:
    from hypern.openapi import OpenAPIGenerator

AppType = TypeVar("AppType", bound="Hypern")
HandlerType = Callable[..., Union[None, Awaitable[None]]]

# Type alias for middleware (can be Rust middleware object or Python callable)
Middleware = Union[Callable, object]


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
        self: AppType,
        routes: Annotated[
            Optional[List[RustRoute]],
            Doc("A list of routes to serve incoming HTTP and WebSocket requests.")
        ] = None,
        debug: bool = False,
        task_workers: int = 4,
        task_queue_size: int = 1000,
    ) -> None:
        # Core routing
        self._router = RustRouter(path="/")
        self._routers: List[Router] = []
        
        # Middleware (Rust middleware instances or callables)
        self._middleware: List[Union[Callable, object, tuple]] = []
        
        # Request lifecycle handlers
        self._before_handlers: List[Callable] = []
        self._after_handlers: List[Callable] = []
        
        # Exception handling
        self._exception_handler = ExceptionHandler()
        
        # Lifecycle handlers
        self._startup_handlers: List[Callable] = []
        self._shutdown_handlers: List[Callable] = []
        
        # Settings
        self._settings: Dict[str, Any] = {}
        self.debug = debug
        
        self._di = DIContainer()
        
        self._tasks = TaskExecutor(task_workers, task_queue_size)
        
        # Register this app's task executor as the global default
        from hypern.tasks import set_task_executor
        set_task_executor(self._tasks)
        
        # OpenAPI (lazy-loaded)
        self._openapi: Optional['OpenAPIGenerator'] = None
        self._openapi_enabled = False
        
        # Graceful shutdown
        self._shutdown_event: Optional[asyncio.Event] = None
        self._running = False
        
        # Backwards compatibility
        self.router = self._router
        self.response_headers: Dict[str, str] = {}
        self.start_up_handler = None
        self.shutdown_handler = None
        
        if routes is not None:
            self._router.extend_route(routes)
  
    @property
    def di(self) -> Optional['DIContainer']:
        """Access the dependency injection container."""
        return self._di
    
    @property
    def tasks(self) -> Optional['TaskExecutor']:
        """Access the background task executor."""
        return self._tasks
    
    @property
    def openapi(self) -> Optional['OpenAPIGenerator']:
        """Access the OpenAPI generator (if enabled)."""
        return self._openapi
    
    def set(self, key: str, value: Any) -> 'Hypern':
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
    
    def enable(self, key: str) -> 'Hypern':
        """Enable a boolean setting."""
        self._settings[key] = True
        return self
    
    def disable(self, key: str) -> 'Hypern':
        """Disable a boolean setting."""
        self._settings[key] = False
        return self
    
    def enabled(self, key: str) -> bool:
        """Check if a setting is enabled."""
        return self._settings.get(key, False) is True
    
    def disabled(self, key: str) -> bool:
        """Check if a setting is disabled."""
        return not self.enabled(key)
    
    def singleton(self, name: str, value: Any) -> 'Hypern':
        """
        Register a singleton dependency (shared across all requests).
        
        Example:
            app.singleton("database", db_connection)
            app.singleton("config", app_config)
        """
        if self._di is not None:
            self._di.singleton(name, value)
        return self
    
    def factory(self, name: str, factory_fn: Callable) -> 'Hypern':
        """
        Register a factory dependency (created for each request).
        
        Example:
            app.factory("user_service", lambda: UserService())
        """
        if self._di is not None:
            self._di.factory(name, factory_fn)
        return self
    
    def inject(self, name: str) -> Callable:
        """
        Decorator to inject a dependency by name.
        
        Example:
            @app.inject("database")
            async def get_users(req, res, ctx, database):
                users = await database.query("SELECT * FROM users")
                res.json(users)
        """
        def decorator(handler: HandlerType) -> HandlerType:
            @functools.wraps(handler)
            async def wrapped(req, res, ctx):
                dep = ctx.get(name) if ctx else None
                if asyncio.iscoroutinefunction(handler):
                    await handler(req, res, ctx, dep)
                else:
                    handler(req, res, ctx, dep)
            return wrapped
        return decorator
    
    def background(
        self, 
        delay_seconds: Optional[float] = None
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
        delay_seconds: Optional[float] = None
    ) -> Optional[str]:
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
    
    def get_task(self, task_id: str) -> Optional["TaskResult"]:
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
    
    def sse(self, buffer_size: int = 100) -> 'SSEStream':
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
    ) -> 'StreamingResponse':
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
    
    def setup_openapi(
        self,
        title: str = "API Documentation",
        version: str = "1.0.0",
        description: str = "",
        docs_path: str = "/docs",
        redoc_path: str = "/redoc",
        openapi_path: str = "/openapi.json",
    ) -> 'Hypern':
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
    
    def add_route(self, method: str, endpoint: str, handler: Callable[..., Any]):
        """
        Add a route to the router.
        
        Args:
            method: The HTTP method (GET, POST, PUT, DELETE, etc.)
            endpoint: The endpoint path (e.g., "/users/:id")
            handler: The function that handles requests
        """
        # Normalize path to start with /
        if endpoint and not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        if not endpoint:
            endpoint = "/"
        
        route = RustRoute(path=endpoint, function=handler, method=method.upper())
        self._router.add_route(route=route)
        
        # Register with OpenAPI if enabled
        # Note: OpenAPI registration happens during spec generation
        # if self._openapi_enabled and self._openapi:
        #     self._openapi.add_route(method, endpoint, handler)
    
    def get(self, path: str, middleware: Optional[List[Callable]] = None, **options):
        """
        Register a GET route.
        
        Example:
            @app.get("/users")
            async def get_users(req, res, ctx):
                res.json([{"id": 1}])
        """
        def decorator(handler: Callable[..., Any]):
            wrapped = self._wrap_handler(handler, middleware)
            self.add_route("GET", path, wrapped)
            return handler
        return decorator
    
    def post(self, path: str, middleware: Optional[List[Callable]] = None, **options):
        """
        Register a POST route.
        
        Example:
            @app.post("/users")
            async def create_user(req, res, ctx):
                body = req.json()
                res.status(201).json(body)
        """
        def decorator(handler: Callable[..., Any]):
            wrapped = self._wrap_handler(handler, middleware)
            self.add_route("POST", path, wrapped)
            return handler
        return decorator
    
    def put(self, path: str, middleware: Optional[List[Callable]] = None, **options):
        """Register a PUT route."""
        def decorator(handler: Callable[..., Any]):
            wrapped = self._wrap_handler(handler, middleware)
            self.add_route("PUT", path, wrapped)
            return handler
        return decorator
    
    def delete(self, path: str, middleware: Optional[List[Callable]] = None, **options):
        """Register a DELETE route."""
        def decorator(handler: Callable[..., Any]):
            wrapped = self._wrap_handler(handler, middleware)
            self.add_route("DELETE", path, wrapped)
            return handler
        return decorator
    
    def patch(self, path: str, middleware: Optional[List[Callable]] = None, **options):
        """Register a PATCH route."""
        def decorator(handler: Callable[..., Any]):
            wrapped = self._wrap_handler(handler, middleware)
            self.add_route("PATCH", path, wrapped)
            return handler
        return decorator
    
    def options(self, path: str, middleware: Optional[List[Callable]] = None, **options):
        """Register an OPTIONS route."""
        def decorator(handler: Callable[..., Any]):
            wrapped = self._wrap_handler(handler, middleware)
            self.add_route("OPTIONS", path, wrapped)
            return handler
        return decorator
    
    def head(self, path: str, middleware: Optional[List[Callable]] = None, **options):
        """Register a HEAD route."""
        def decorator(handler: Callable[..., Any]):
            wrapped = self._wrap_handler(handler, middleware)
            self.add_route("HEAD", path, wrapped)
            return handler
        return decorator
    
    def all(self, path: str, middleware: Optional[List[Callable]] = None, **options):
        """
        Register a route for all HTTP methods.
        
        Example:
            @app.all("/api/*")
            async def api_handler(req, res, ctx):
                res.json({"method": req.method})
        """
        def decorator(handler: Callable[..., Any]):
            wrapped = self._wrap_handler(handler, middleware)
            for method in ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]:
                self.add_route(method, path, wrapped)
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
                self_rb.app.add_route("GET", self_rb.path, handler)
                return self_rb
            
            def post(self_rb, handler):
                self_rb.app.add_route("POST", self_rb.path, handler)
                return self_rb
            
            def put(self_rb, handler):
                self_rb.app.add_route("PUT", self_rb.path, handler)
                return self_rb
            
            def delete(self_rb, handler):
                self_rb.app.add_route("DELETE", self_rb.path, handler)
                return self_rb
            
            def patch(self_rb, handler):
                self_rb.app.add_route("PATCH", self_rb.path, handler)
                return self_rb
            
            def all(self_rb, handler):
                for method in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
                    self_rb.app.add_route(method, self_rb.path, handler)
                return self_rb
        
        return AppRouteBuilder(self, path)
    
    def static(
        self,
        url_path: str = "/static",
        directory: str = "static",
        index: str = "index.html"
    ) -> 'Hypern':
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
        import os
        import mimetypes
        
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
            except IOError:
                res.status(500).send("Error reading file")
        
        return self
    
    def use(
        self, 
        path_or_middleware: Union[str, Middleware, Callable, Router], 
        middleware_or_router: Optional[Union[Middleware, Callable, Router]] = None
    ) -> 'Hypern':
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

    def _register_middleware(self, target: Any, path: Optional[str] = None):
        """Register middleware or hook, optionally with a path."""
        # Check for request hooks
        if hasattr(target, "_before_request"):
            self._before_handlers.append(target)
        
        if hasattr(target, "_after_request"):
            self._after_handlers.append(target)
            
        # If it's a hook but not explicitly marked as middleware, still keep it for global execution
        # But if it's a standard middleware (with next) or Rust middleware, add to _middleware
        if path:
            self._middleware.append((path, target))
        else:
            self._middleware.append(target)
    
    def _mount_router(self, prefix: str, router: Router):
        """Mount a router at a path prefix."""
        self._routers.append((prefix, router))
        
        # Add all routes from the router to the main router
        for method, path, handler, options in router._routes:
            full_path = prefix + path if prefix else path
            self.add_route(method, full_path, handler)
    
    def on_startup(self, handler: Callable) -> Callable:
        """
        Register a startup handler.
        
        Example:
            @app.on_startup
            async def startup():
                print("Server starting...")
                await init_database()
        """
        self._startup_handlers.append(handler)
        return handler
    
    def on_shutdown(self, handler: Callable) -> Callable:
        """
        Register a shutdown handler.
        
        Example:
            @app.on_shutdown
            async def shutdown():
                print("Server shutting down...")
                await close_database()
        """
        self._shutdown_handlers.append(handler)
        return handler
    
    def before_request(self, handler: Callable) -> Callable:
        """
        Register a before-request handler.
        
        Example:
            @app.before_request
            async def log_request(req, res, ctx):
                print(f"Request: {req.method} {req.path}")
        """
        self._before_handlers.append(handler)
        return handler
    
    def after_request(self, handler: Callable) -> Callable:
        """
        Register an after-request handler.
        
        Example:
            @app.after_request
            async def add_headers(req, res, ctx):
                res.header("X-Server", "Hypern")
        """
        self._after_handlers.append(handler)
        return handler
    
    def errorhandler(self, exc_class: Type[Exception]) -> Callable:
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
        return self._exception_handler.handle(exc_class)
    
    def register_error_handler(self, exc_class: Type[Exception], handler: Callable):
        """Register an exception handler programmatically."""
        self._exception_handler.add_handler(exc_class, handler)
    
    def _wrap_handler(
        self, 
        handler: Callable, 
        middleware: Optional[List[Callable]] = None
    ) -> Callable:
        """Wrap a handler with middleware, context injection, error handling, and auto DB finalization."""
        
        @functools.wraps(handler)
        async def wrapped(req, res):
            # Create request context with DI
            ctx = self._di.create_context() if self._di else None
            
            try:
                # Execute before-request handlers
                for before_handler in self._before_handlers:
                    try:
                        if asyncio.iscoroutinefunction(before_handler):
                            await before_handler(req, res, ctx)
                        else:
                            before_handler(req, res, ctx)
                    except Exception as e:
                        await self._exception_handler.handle_exception(req, res, e)
                        return
                
                async def execute_handler():
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            await handler(req, res, ctx)
                        else:
                            handler(req, res, ctx)
                    except Exception as e:
                        # Mark DB session as having error for rollback
                        if ctx:
                            try:
                                if _Database.is_configured():
                                    session = _get_db(ctx.request_id)
                                    session.set_error()
                            except Exception:
                                pass
                        await self._exception_handler.handle_exception(req, res, e)
                
                # Collect applicable Python middleware
                all_middleware = []
                
                # Add applicable global/path-specific middleware from self._middleware
                for mw_entry in self._middleware:
                    if isinstance(mw_entry, tuple):
                        path_prefix, mw = mw_entry
                        # Path matching for path-specific middleware
                        if req.path.startswith(path_prefix):
                            # Skip if it's already a before/after hook (already executed)
                            if not hasattr(mw, "_before_request") and not hasattr(mw, "_after_request"):
                                if callable(mw) or hasattr(mw, "_is_middleware"):
                                    all_middleware.append(mw)
                    else:
                        mw = mw_entry
                        # Skip Rust middleware (they are handled by server core)
                        # Skip before/after hooks (they are handled above/below)
                        if callable(mw) and not isinstance(mw, tuple):
                            if not hasattr(mw, "_before_request") and not hasattr(mw, "_after_request"):
                                if hasattr(mw, "_is_middleware") or (
                                    # Fallback for simple callables that behave like middleware (req, res, ctx, next)
                                    mw.__code__.co_argcount >= 4 if hasattr(mw, "__code__") else False
                                ):
                                    all_middleware.append(mw)
                
                # Add route-specific middleware
                if middleware:
                    all_middleware.extend(middleware)
                
                # Execute middleware chain
                if all_middleware:
                    index = 0
                    
                    async def next_middleware():
                        nonlocal index
                        if index < len(all_middleware):
                            mw = all_middleware[index]
                            index += 1
                            if asyncio.iscoroutinefunction(mw):
                                await mw(req, res, ctx, next_middleware)
                            else:
                                mw(req, res, ctx, next_middleware)
                        else:
                            await execute_handler()
                    
                    try:
                        await next_middleware()
                    except Exception as e:
                        await self._exception_handler.handle_exception(req, res, e)
                else:
                    await execute_handler()
                
                # Execute after-request handlers
                for after_handler in self._after_handlers:
                    try:
                        if asyncio.iscoroutinefunction(after_handler):
                            await after_handler(req, res, ctx)
                        else:
                            after_handler(req, res, ctx)
                    except Exception:
                        pass  # Don't fail on after-request errors
            finally:
                # Auto-finalize database session at end of request (like Flask-SQLAlchemy session scope)
                if ctx:
                    try:
                        if _Database.is_configured():
                            _finalize_db(ctx)
                    except Exception:
                        pass  # Don't fail if DB wasn't used
        
        return wrapped
    
    async def _run_startup_handlers(self):
        """Run all startup handlers."""
        for handler in self._startup_handlers:
            if asyncio.iscoroutinefunction(handler):
                await handler()
            else:
                handler()
    
    async def _run_shutdown_handlers(self):
        """Run all shutdown handlers."""
        for handler in self._shutdown_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler()
                else:
                    handler()
            except Exception as e:
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
        callback: Optional[Callable] = None,
        **kwargs
    ):
        """
        Start the server.
        
        Example:
            app.listen(3000)
            app.listen(3000, "127.0.0.1")
            app.listen(3000, callback=lambda: print("Server running on port 3000"))
        """
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
        self._running = True
        self._setup_signal_handlers()
        
        # Run startup handlers synchronously before starting server
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._run_startup_handlers())
        finally:
            loop.close()
        
        try:
            server = Server()
            server.set_router(router=self._router)
            
            # Register Rust middleware
            for mw in self._middleware:
                # Skip path-specific middleware tuples and Python callables
                if isinstance(mw, tuple) or callable(mw):
                    continue
                    
                # Register Rust middleware objects (CORS, SecurityHeaders, etc.)
                try:
                    server.use_middleware(mw)
                except Exception:
                    # Silently skip non-Rust middleware (e.g., MiddlewareStack, Python middleware)
                    pass
            
            server.start(
                host=host,
                port=port,
                num_processes=num_processes,
                workers_threads=workers_threads,
                max_blocking_threads=max_blocking_threads,
                max_connections=max_connections,
            )
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
    
    def run_dev(
        self,
        port: int = 3000,
        host: str = '0.0.0.0',
        reload: bool = True,
        reload_dirs: Optional[List[str]] = None,
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
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler, FileModifiedEvent
            
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


__all__ = [
    'Hypern',
    'create_app',
    'hypern',
]

