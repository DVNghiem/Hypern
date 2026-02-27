from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class Request:
    pass

class Response:
    def status(self, status: int) -> Response: ...
    def header(self, key: str, value: str) -> Response: ...
    def body(self, body: bytes) -> Response: ...
    def body_str(self, body: str) -> Response: ...
    def finish(self) -> None: ...
    # ExpressJS-like methods
    def send(self, data: str | bytes) -> Response: ...
    def json(self, data: Any) -> Response: ...
    def html(self, content: str) -> Response: ...
    def text(self, content: str) -> Response: ...
    def xml(self, content: str) -> Response: ...
    def redirect(self, url: str, status: int = 302) -> Response: ...
    def cookie(self, name: str, value: str, **options: Any) -> Response: ...
    def clear_cookie(self, name: str) -> Response: ...
    def cache_control(self, **directives: Any) -> Response: ...
    def cors(self, **options: Any) -> Response: ...
    def attachment(self, filename: Optional[str] = None) -> Response: ...
    def content_type(self, mime_type: str) -> Response: ...
    def vary(self, header: str) -> Response: ...
    def etag(self, value: str) -> Response: ...
    def location(self, url: str) -> Response: ...
    def links(self, links: Dict[str, str]) -> Response: ...
    # SSE/Streaming methods
    def sse(self, events: List["SSEEvent"]) -> Response: ...
    def sse_event(self, data: str, event: Optional[str] = None, id: Optional[str] = None) -> Response: ...
    def sse_headers(self) -> Response: ...
    
@dataclass
class Server:
    router: Router
    websocket_router: Any
    startup_handler: Any
    shutdown_handler: Any

    def add_route(self, route: Route) -> None: ...
    def set_router(self, router: Router) -> None: ...
    def use_middleware(self, middleware: Any) -> None: ...
    def start(self, host: str, port: int, num_processes: int, workers_threads: int, max_blocking_threads: int, max_connections: int) -> None: ...
    def enable_http2(self) -> None: ...
    def set_reload_config(self, config: "ReloadConfig") -> None: ...
    def get_reload_manager(self) -> Optional["ReloadManager"]: ...
    def get_health_check(self) -> Optional["HealthCheck"]: ...
    def graceful_reload(self) -> None: ...
    def hot_reload(self) -> None: ...

class Route:
    path: str
    function: Callable[[Request, Response], Any]
    method: str
    doc: str | None = None

    def matches(self, path: str, method: str) -> str: ...
    def clone_route(self) -> Route: ...
    def update_path(self, new_path: str) -> None: ...
    def update_method(self, new_method: str) -> None: ...
    def is_valid(self) -> bool: ...
    def get_path_parans(self) -> List[str]: ...
    def has_parameters(self) -> bool: ...
    def normalized_path(self) -> str: ...
    def same_handler(self, other: Route) -> bool: ...

class Router:
    routes: List[Route]

    def add_route(self, route: Route) -> None: ...
    def remove_route(self, path: str, method: str) -> bool: ...
    def get_route(self, path: str, method) -> Route | None: ...
    def get_routes_by_path(self, path: str) -> List[Route]: ...
    def get_routes_by_method(self, method: str) -> List[Route]: ...
    def extend_route(self, routes: List[Route]) -> None: ...

@dataclass
class SocketHeld:
    socket: Any

@dataclass
class HeaderMap:

    def get(self, key: str) -> str | None: ...
    def get_all(self, key: str) -> List[str]: ...
    def keys(self) -> List[str]: ...
    def values(self) -> List[str]: ...
    def items(self) -> Dict[str, str]: ...

class Context:
    """Request-scoped dependency injection context."""
    user_id: Optional[str]
    is_authenticated: bool
    request_id: str
    
    def __init__(self) -> None: ...
    def set(self, key: str, value: Any) -> None: ...
    def get(self, key: str) -> Any: ...
    def has(self, key: str) -> bool: ...
    def remove(self, key: str) -> bool: ...
    def keys(self) -> List[str]: ...
    def set_auth(self, user_id: str, roles: Optional[List[str]] = None) -> None: ...
    def clear_auth(self) -> None: ...
    def has_role(self, role: str) -> bool: ...
    def elapsed_ms(self) -> float: ...

class DIContainer:
    
    def __init__(self) -> None: ...
    def singleton(self, name: str, value: Any) -> None: ...
    def factory(self, name: str, factory: Callable[[], Any]) -> None: ...
    def get_singleton(self, name: str) -> Any: ...
    def create_context(self) -> Context: ...
    def has(self, name: str) -> bool: ...
    def remove(self, name: str) -> bool: ...

class TaskStatus(Enum):
    Pending = ...
    Running = ...
    Completed = ...
    Failed = ...
    Cancelled = ...

class TaskResult:
    """Result of a background task."""
    task_id: str
    status: TaskStatus
    result: Optional[str]
    error: Optional[str]
    started_at: Optional[float]
    completed_at: Optional[float]
    
    def is_success(self) -> bool: ...
    def is_failed(self) -> bool: ...
    def is_pending(self) -> bool: ...

class TaskExecutor:
    """Background task executor with worker pool."""
    
    def __init__(self, num_workers: int = 4, queue_size: int = 1000) -> None: ...
    def submit(
        self, 
        handler: Callable[..., Any], 
        args: tuple = (),
        delay_seconds: Optional[float] = None
    ) -> str: ...
    def get_result(self, task_id: str) -> Optional[TaskResult]: ...
    def cancel(self, task_id: str) -> bool: ...
    def pending_count(self) -> int: ...
    def completed_count(self) -> int: ...
    def shutdown(self, wait: bool = True) -> None: ...


class BlockingExecutor:
    """
    High-performance, GIL-releasing thread pool executor implemented in Rust.
    
    Runs Python callables on dedicated Rust OS threads. The calling thread
    releases the GIL while waiting for results, enabling true parallelism
    for CPU-bound work without GIL contention.
    
    Unlike ``concurrent.futures.ThreadPoolExecutor``, worker threads use
    Rust's crossbeam channels (lock-free) for task dispatch, and the GIL is
    only held for the brief duration of the Python callable execution.
    
    Supports context-manager protocol (``with`` statement) for automatic
    shutdown.
    
    Example::
    
        from hypern import BlockingExecutor
    
        executor = BlockingExecutor(max_threads=8)
        result = executor.run_sync(heavy_computation, arg1, arg2)
    """
    
    def __init__(self, max_threads: int = 0, queue_size: int = 0) -> None:
        """
        Create a new blocking executor.
        
        Args:
            max_threads: Number of OS worker threads. 0 = auto-detect CPU count.
            queue_size: Bounded queue depth. 0 = unbounded.
        """
        ...
    
    def run_sync(self, callable: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """
        Execute a callable on a pool thread, blocking until done.
        
        The calling thread releases the GIL while waiting, so other Python
        threads and async tasks can progress concurrently.
        
        Args:
            callable: Any Python callable.
            *args: Positional arguments.
            **kwargs: Keyword arguments.
        
        Returns:
            The return value of ``callable(*args, **kwargs)``.
        
        Raises:
            RuntimeError: If the pool is shut down or the callable raises.
        """
        ...
    
    def run_parallel(
        self,
        tasks: List[tuple[Callable[..., Any], tuple, Optional[Dict[str, Any]]]]
    ) -> List[Any]:
        """
        Run multiple callables in parallel, returning results in order.
        
        Each element is ``(callable, args)`` or ``(callable, args, kwargs)``.
        The calling thread releases the GIL and waits for all tasks.
        
        Args:
            tasks: List of (callable, args) or (callable, args, kwargs) tuples.
        
        Returns:
            List of results in the same order as input.
        
        Raises:
            RuntimeError: If any task raises an exception.
        """
        ...
    
    def map(
        self,
        callable: Callable[[Any], Any],
        items: List[Any],
        chunk_size: int = 0
    ) -> List[Any]:
        """
        Map a callable over items in parallel with automatic chunking.
        
        Equivalent to ``[callable(item) for item in items]`` but distributed
        across all pool threads with the GIL released between chunks.
        
        Args:
            callable: Function taking a single item.
            items: List of items to process.
            chunk_size: Items per work unit. 0 = auto-tune based on pool size.
        
        Returns:
            List of results in the same order as items.
        """
        ...
    
    def active_threads(self) -> int:
        """Number of currently alive worker threads."""
        ...
    
    def pool_size(self) -> int:
        """Maximum thread pool size."""
        ...
    
    def pending_tasks(self) -> int:
        """Number of tasks waiting in the queue."""
        ...
    
    def is_running(self) -> bool:
        """Whether the executor is still accepting work."""
        ...
    
    def shutdown(self, wait: bool = True, timeout_secs: float = 30.0) -> None:
        """
        Shut down the executor.
        
        Args:
            wait: If True, block until pending tasks finish.
            timeout_secs: Maximum seconds to wait.
        """
        ...
    
    def __enter__(self) -> "BlockingExecutor": ...
    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool: ...
    def __repr__(self) -> str: ...

class SSEEvent:
    """Server-Sent Event."""
    id: Optional[str]
    event: Optional[str]
    data: str
    retry: Optional[int]
    
    def __init__(
        self, 
        data: str, 
        id: Optional[str] = None, 
        event: Optional[str] = None,
        retry: Optional[int] = None
    ) -> None: ...
    def format(self) -> str: ...
    def to_bytes(self) -> bytes: ...

class SSEStream:
    """SSE stream for sending events to clients."""
    
    def __init__(self, buffer_size: int = 100) -> None: ...
    def send(self, event: SSEEvent) -> bool: ...
    def send_data(self, data: str) -> bool: ...
    def send_event(self, event_name: str, data: str) -> bool: ...
    def keepalive(self) -> bool: ...
    def close(self) -> None: ...
    def is_closed(self) -> bool: ...
    def event_count(self) -> int: ...

class StreamingResponse:
    """Streaming response for large data transfers."""
    content_type: str
    
    def __init__(self, buffer_size: int = 100, content_type: str = "application/octet-stream") -> None: ...
    def write(self, data: bytes) -> bool: ...
    def write_str(self, data: str) -> bool: ...
    def write_line(self, data: str) -> bool: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...
    def is_closed(self) -> bool: ...


class CorsMiddleware:
    """
    CORS middleware - handles Cross-Origin Resource Sharing.
    
    Implemented in Rust for high performance.
    """
    def __init__(
        self,
        allowed_origins: Optional[List[str]] = None,
        allowed_methods: Optional[List[str]] = None,
        allowed_headers: Optional[List[str]] = None,
        expose_headers: Optional[List[str]] = None,
        allow_credentials: bool = False,
        max_age: int = 86400
    ) -> None: ...
    
    @staticmethod
    def permissive() -> CorsMiddleware: ...


class RateLimitMiddleware:
    """
    Rate limiting middleware with multiple algorithms.
    
    Implemented in Rust for high performance.
    """
    def __init__(
        self,
        max_requests: int = 100,
        window_secs: int = 60,
        algorithm: str = "sliding",
        key_header: Optional[str] = None,
        skip_paths: Optional[List[str]] = None
    ) -> None: ...


class SecurityHeadersMiddleware:
    """
    Security headers middleware.
    
    Adds security headers like HSTS, CSP, X-Frame-Options, etc.
    """
    def __init__(
        self,
        hsts: bool = True,
        hsts_max_age: int = 31536000,
        frame_options: str = "DENY",
        content_type_options: bool = True,
        xss_protection: bool = True,
        csp: Optional[str] = None
    ) -> None: ...
    
    @staticmethod
    def strict() -> SecurityHeadersMiddleware: ...


class TimeoutMiddleware:
    """
    Request timeout middleware.
    
    Enforces request timeout at the Rust/Tokio level.
    """
    def __init__(self, timeout_secs: int = 30) -> None: ...


class CompressionMiddleware:
    """
    Response compression middleware.
    
    Compresses response bodies using gzip based on Accept-Encoding.
    """
    def __init__(self, min_size: int = 1024) -> None: ...


class RequestIdMiddleware:
    """
    Request ID middleware.
    
    Adds a unique request ID to each request for tracing.
    """
    def __init__(self, header_name: str = "X-Request-ID") -> None: ...


class LogMiddleware:
    """
    Request logging middleware.
    
    Logs incoming requests using Rust's tracing infrastructure.
    """
    def __init__(
        self,
        level: str = "info",
        log_headers: bool = False,
        skip_paths: Optional[List[str]] = None
    ) -> None: ...
    
    @staticmethod
    def default_logger() -> LogMiddleware: ...


class BasicAuthMiddleware:
    """
    HTTP Basic Authentication middleware.
    
    Implements HTTP Basic Authentication with username/password pairs.
    """
    def __init__(
        self,
        realm: str = "Restricted",
        users: Optional[Dict[str, str]] = None
    ) -> None: ...


class HealthCheck:
    """
    Health check / probe state for zero-downtime reload support.
    
    Tracks service health status, in-flight requests, and uptime.
    Used by Kubernetes-style liveness/readiness/startup probes.
    """
    
    def __init__(self) -> None: ...
    def status(self) -> str:
        """Current health status: 'starting', 'healthy', 'draining', 'unhealthy'."""
        ...
    def mark_healthy(self) -> None:
        """Mark the service as healthy and ready to accept traffic."""
        ...
    def mark_draining(self) -> None:
        """Mark the service as draining (no new traffic accepted)."""
        ...
    def mark_unhealthy(self) -> None:
        """Mark the service as unhealthy."""
        ...
    def in_flight(self) -> int:
        """Number of currently in-flight requests."""
        ...
    def uptime_secs(self) -> float:
        """Uptime in seconds since the process started."""
        ...
    def is_live(self) -> bool:
        """Whether the liveness probe passes (process is alive)."""
        ...
    def is_ready(self) -> bool:
        """Whether the readiness probe passes (ready for traffic)."""
        ...
    def to_json(self) -> str:
        """JSON representation of health state."""
        ...
    def add_custom_check(self, name: str) -> None:
        """Add a named custom health check."""
        ...


class ReloadConfig:
    """
    Configuration for zero-downtime reload behavior.
    
    Controls drain timeouts, health probe paths, and startup grace periods.
    """
    drain_timeout_secs: int
    health_poll_interval_ms: int
    startup_grace_secs: int
    health_probes_enabled: bool
    health_path_prefix: str
    
    def __init__(
        self,
        drain_timeout_secs: int = 30,
        health_poll_interval_ms: int = 100,
        startup_grace_secs: int = 2,
        health_probes_enabled: bool = True,
        health_path_prefix: str = "/_health",
    ) -> None: ...


class ReloadManager:
    """
    Manager for zero-downtime reloads with health probes.
    
    Supports:
    - Graceful reload (drain in-flight requests, then restart workers)
    - Hot reload (immediate restart for development)
    - Health probes (liveness, readiness, startup) for Kubernetes
    
    Health probe endpoints (when enabled):
    - GET /_health          - Full health status JSON
    - GET /_health/live     - Liveness probe (is process alive?)
    - GET /_health/ready    - Readiness probe (accepting traffic?)
    - GET /_health/startup  - Startup probe (finished starting?)
    
    Signals:
    - SIGUSR1 → Graceful reload (drain + restart)
    - SIGUSR2 → Hot reload (immediate restart)
    """
    
    def __init__(self, config: Optional[ReloadConfig] = None) -> None: ...
    def health(self) -> HealthCheck:
        """Get the health check instance."""
        ...
    def graceful_reload(self) -> None:
        """Trigger a graceful reload (drain in-flight, then restart workers)."""
        ...
    def hot_reload(self) -> None:
        """Trigger a hot reload (immediate restart, for development)."""
        ...
    def shutdown(self) -> None:
        """Trigger a full shutdown."""
        ...
    def is_draining(self) -> bool:
        """Whether the server is currently draining connections."""
        ...
    def status(self) -> str:
        """Current health status string."""
        ...
    def in_flight(self) -> int:
        """Number of in-flight requests."""
        ...


class PoolConfig:
    """Configuration for the database connection pool."""
    url: str
    max_size: int
    min_idle: Optional[int]
    connect_timeout_secs: int
    idle_timeout_secs: Optional[int]
    max_lifetime_secs: Optional[int]
    test_before_acquire: bool
    keepalive_secs: Optional[int]
    
    def __init__(
        self,
        url: str,
        max_size: int = 16,
        min_idle: Optional[int] = None,
        connect_timeout_secs: int = 30,
        idle_timeout_secs: Optional[int] = None,
        max_lifetime_secs: Optional[int] = None,
        test_before_acquire: bool = False,
        keepalive_secs: Optional[int] = None,
    ) -> None: ...


class PoolStatus:
    """Status information about the connection pool."""
    size: int
    available: int
    max_size: int


class ConnectionPool:
    """Static connection pool manager."""
    
    def __init__(self) -> None: ...
    
    @staticmethod
    def initialize(config: PoolConfig) -> None:
        """Initialize the connection pool with the given configuration."""
        ...
    
    @staticmethod
    def status() -> Optional[PoolStatus]:
        """Get the current pool status."""
        ...
    
    @staticmethod
    def is_initialized() -> bool:
        """Check if the connection pool is initialized."""
        ...
    
    @staticmethod
    def close() -> None:
        """Close all connections and reset the pool."""
        ...

    @staticmethod
    def status_for_alias(alias: str) -> Optional[PoolStatus]:
        """Get the current pool status for a specific alias."""
        ...

    @staticmethod
    def close_all() -> None:
        """Close all connections and reset all pools for all aliases."""
        ...

    @staticmethod
    def close_alias(alias: str) -> None:
        """Close all connections and reset the pool for a specific alias."""
        ...

    @staticmethod
    def initialize_with_alias(config: PoolConfig, alias: str) -> None:
        """Initialize the connection pool for a specific alias with the given configuration."""
        ...


class DbSession:
    """
    Request-scoped database session.
    
    Provides methods for executing SQL queries within a request context.
    """
    request_id: str
    
    def begin(self) -> None:
        """Begin a database transaction."""
        ...
    
    def commit(self) -> None:
        """Commit the current transaction."""
        ...
    
    def rollback(self) -> None:
        """Rollback the current transaction."""
        ...
    
    def query(self, sql: str, params: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
        """Execute a SELECT query and return results as list of dicts."""
        ...
    
    def query_one(self, sql: str, params: Optional[List[Any]] = None) -> Dict[str, Any]:
        """Execute a SELECT query and return a single result as dict."""
        ...
    
    def execute(self, sql: str, params: Optional[List[Any]] = None) -> int:
        """Execute INSERT, UPDATE, DELETE and return affected row count."""
        ...
    
    def execute_many(self, sql: str, params_list: List[List[Any]]) -> int:
        """Execute a batch of INSERT/UPDATE/DELETE statements."""
        ...
    
    def set_auto_commit(self, auto_commit: bool) -> None:
        """Set auto-commit behavior."""
        ...
    
    def set_error(self) -> None:
        """Mark that an error occurred (triggers rollback on finalize)."""
        ...
    
    def state(self) -> str:
        """Get current state as string."""
        ...


class RowStream:
    """
    Streaming row iterator that yields chunks of rows lazily.
    
    This allows Python to iterate over large result sets without loading everything into memory.
    Use in a for loop to iterate over chunks.
    
    Example:
        stream = transaction.stream_data("SELECT * FROM large_table", [], chunk_size=1000)
        for chunk in stream:
            for row in chunk:
                process(row)
    """
    
    def __iter__(self) -> "RowStream":
        """Return the iterator."""
        ...
    
    def __next__(self) -> List[Dict[str, Any]]:
        """Get the next chunk of rows."""
        ...
    
    def is_exhausted(self) -> bool:
        """Check if the stream is exhausted."""
        ...
    
    def chunk_count(self) -> int:
        """Get the total number of chunks (available after streaming completes)."""
        ...


def get_db(request_id: str) -> DbSession:
    """
    Get or create a database session for the given request ID.
    
    Deprecated: Use db() from hypern.database instead.
    """
    ...


def finalize_db(request_id: str) -> None:
    """
    Finalize the database session for a request.
    
    Commits or rolls back any pending transaction and releases the connection.
    """
    ...

def finalize_db_all(request_id: str) -> None:
    """
    Finalize all database sessions for a request across all aliases.
    
    Commits or rolls back any pending transactions and releases all connections.
    """
    ...


# ============================================================================
# Realtime: Channel / Topic
# ============================================================================

class ChannelStats:
    """Statistics for a single channel."""
    name: str
    subscriber_count: int
    total_messages: int
    dropped_messages: int
    metadata: dict[str, str]

class Subscriber:
    """Subscriber handle that receives messages from a channel."""
    channel_name: str
    client_id: str
    received_count: int
    missed_count: int
    
    def try_recv(self) -> Optional[str]: ...
    def drain(self) -> List[str]: ...

class TopicMatcher:
    """Pattern-based topic matching for pub/sub routing."""
    
    def __init__(self) -> None: ...
    def subscribe(self, pattern: str, client_id: str) -> None: ...
    def unsubscribe(self, pattern: str, client_id: str) -> bool: ...
    def unsubscribe_all(self, client_id: str) -> int: ...
    def match_topic(self, topic: str) -> List[str]: ...
    @staticmethod
    def pattern_matches(pattern: str, topic: str) -> bool: ...
    def patterns(self) -> List[str]: ...
    def subscriber_count(self, pattern: str) -> int: ...

class ChannelManager:
    """High-performance channel manager for pub/sub messaging."""
    topic_matcher: TopicMatcher
    
    def __init__(self, default_buffer_size: int = 256) -> None: ...
    def create_channel(
        self,
        name: str,
        buffer_size: Optional[int] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> bool: ...
    def remove_channel(self, name: str) -> bool: ...
    def has_channel(self, name: str) -> bool: ...
    def subscribe(self, channel_name: str, client_id: str) -> Subscriber: ...
    def unsubscribe(self, channel_name: str, client_id: str) -> bool: ...
    def publish(self, channel_name: str, message: str) -> int: ...
    def publish_to_topic(self, topic: str, message: str) -> int: ...
    def get_stats(self, channel_name: str) -> ChannelStats: ...
    def list_channels(self) -> List[str]: ...
    def get_subscribers(self, channel_name: str) -> List[str]: ...
    def channel_count(self) -> int: ...
    def clear(self) -> None: ...


# ============================================================================
# Realtime: Presence
# ============================================================================

class PresenceInfo:
    """Information about a connected client's presence."""
    client_id: str
    channel: str
    metadata: Dict[str, str]
    joined_at: float
    last_seen: float
    
    def __init__(
        self,
        client_id: str,
        channel: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> None: ...

class PresenceDiff:
    """Diff of presence changes (joins and leaves)."""
    joins: List[PresenceInfo]
    leaves: List[str]
    
    def __init__(self) -> None: ...
    def has_changes(self) -> bool: ...
    def change_count(self) -> int: ...

class PresenceTracker:
    """Track connected clients' presence across channels."""
    
    def __init__(self) -> None: ...
    def track(
        self,
        channel: str,
        client_id: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> PresenceInfo: ...
    def untrack(self, channel: str, client_id: str) -> bool: ...
    def untrack_all(self, client_id: str) -> List[str]: ...
    def update(self, channel: str, client_id: str, metadata: Dict[str, str]) -> bool: ...
    def touch(self, channel: str, client_id: str) -> bool: ...
    def list(self, channel: str) -> List[PresenceInfo]: ...
    def get(self, channel: str, client_id: str) -> Optional[PresenceInfo]: ...
    def count(self, channel: str) -> int: ...
    def flush_diff(self, channel: str) -> PresenceDiff: ...
    def client_channels(self, client_id: str) -> List[str]: ...
    def active_channels(self) -> List[str]: ...
    def total_clients(self) -> int: ...
    def evict_stale(self, timeout_secs: float) -> List[tuple[str, str]]: ...
    def clear(self) -> None: ...


# ============================================================================
# Realtime: Broadcast
# ============================================================================

class BackpressurePolicy(Enum):
    """Policy for handling backpressure when subscribers are slow."""
    DropOldest = 0
    Error = 1

class BroadcastConfig:
    """Configuration for a broadcast channel."""
    buffer_size: int
    policy: BackpressurePolicy
    dedup_enabled: bool
    dedup_window: int
    
    def __init__(
        self,
        buffer_size: int = 256,
        policy: BackpressurePolicy = BackpressurePolicy.DropOldest,
        dedup_enabled: bool = False,
        dedup_window: int = 1000,
    ) -> None: ...

class BroadcastStats:
    """Statistics for broadcast operations."""
    total_sent: int
    total_dropped: int
    total_deduped: int
    active_subscribers: int
    channel_count: int

class BroadcastSubscriber:
    """Subscriber handle for receiving broadcast messages."""
    channel_name: str
    received_count: int
    lagged_count: int
    
    def try_recv(self) -> Optional[str]: ...
    def drain(self) -> List[str]: ...

class RealtimeBroadcast:
    """Backpressure-aware broadcast system."""
    
    def __init__(self) -> None: ...
    def create(self, name: str, config: Optional[BroadcastConfig] = None) -> bool: ...
    def remove(self, name: str) -> bool: ...
    def subscribe(self, name: str) -> BroadcastSubscriber: ...
    def send(self, name: str, message: str, message_id: Optional[str] = None) -> int: ...
    def send_many(self, names: List[str], message: str) -> Dict[str, int]: ...
    def stats(self, name: str) -> BroadcastStats: ...
    def global_stats(self) -> BroadcastStats: ...
    def list_channels(self) -> List[str]: ...
    def has_channel(self, name: str) -> bool: ...
    def clear(self) -> None: ...


# ============================================================================
# Realtime: Heartbeat
# ============================================================================

class HeartbeatConfig:
    """Configuration for heartbeat monitoring."""
    interval_secs: float
    timeout_secs: float
    max_retries: int
    sse_retry_ms: int
    send_keepalive: bool
    
    def __init__(
        self,
        interval_secs: float = 30.0,
        timeout_secs: float = 90.0,
        max_retries: int = 5,
        sse_retry_ms: int = 3000,
        send_keepalive: bool = True,
    ) -> None: ...

class HeartbeatStats:
    """Stats for heartbeat monitoring."""
    monitored_clients: int
    total_pings: int
    total_pongs: int
    total_timeouts: int
    timed_out_clients: int

class HeartbeatMonitor:
    """Server-side heartbeat monitor for SSE and WebSocket connections."""
    config: HeartbeatConfig
    
    def __init__(self, config: Optional[HeartbeatConfig] = None) -> None: ...
    def register(self, client_id: str, last_event_id: Optional[str] = None) -> None: ...
    def unregister(self, client_id: str) -> bool: ...
    def ping(self, client_id: str) -> bool: ...
    def pong(self, client_id: str) -> bool: ...
    def check_timeouts(self) -> List[str]: ...
    def is_timed_out(self, client_id: str) -> bool: ...
    def is_alive(self, client_id: str) -> bool: ...
    def get_dead_clients(self) -> List[str]: ...
    def evict_dead(self) -> List[str]: ...
    def set_last_event_id(self, client_id: str, event_id: str) -> bool: ...
    def get_last_event_id(self, client_id: str) -> Optional[str]: ...
    def clients_needing_ping(self) -> List[str]: ...
    def sse_keepalive_comment(self) -> str: ...
    def sse_retry_field(self) -> str: ...
    def sse_heartbeat_event(self) -> str: ...
    def retry_count(self, client_id: str) -> int: ...
    def stats(self) -> HeartbeatStats: ...
    def client_ids(self) -> List[str]: ...
    def client_info(self) -> Dict[str, Dict[str, str]]: ...
    def clear(self) -> None: ...
    def client_count(self) -> int: ...


# ============================================================================
# Utils: String Helpers
# ============================================================================

def slugify(text: str, separator: str = "-") -> str:
    """Convert text to a URL-safe slug."""
    ...

def truncate(text: str, max_len: int, suffix: str = "...") -> str:
    """Truncate text, appending suffix if truncated."""
    ...

def mask_email(email: str) -> str:
    """Mask an email address for display (PII)."""
    ...

def mask_phone(phone: str, keep_last: int = 4) -> str:
    """Mask a phone number, keeping only the last N digits visible."""
    ...

def mask_string(text: str, keep_start: int = 1, keep_end: int = 1) -> str:
    """Mask a string, keeping keep_start/keep_end chars visible."""
    ...

def snake_to_camel(text: str, upper_first: bool = False) -> str:
    """Convert snake_case to camelCase (or PascalCase)."""
    ...

def camel_to_snake(text: str) -> str:
    """Convert camelCase/PascalCase to snake_case."""
    ...

def keys_to_camel(data: Dict[str, Any], upper_first: bool = False) -> Dict[str, Any]:
    """Convert all dict keys from snake_case to camelCase."""
    ...

def keys_to_snake(data: Dict[str, Any]) -> Dict[str, Any]:
    """Convert all dict keys from camelCase to snake_case."""
    ...

def pad_left(text: str, width: int, pad_char: str = " ") -> str:
    """Left-pad a string to reach ``width`` characters."""
    ...

def pad_right(text: str, width: int, pad_char: str = " ") -> str:
    """Right-pad a string to reach ``width`` characters."""
    ...

def word_count(text: str) -> int:
    """Count whitespace-delimited words."""
    ...

def is_url_safe(text: str) -> bool:
    """Check whether text contains only URL-safe ASCII characters."""
    ...


# ============================================================================
# Utils: Pagination
# ============================================================================

class PageInfo:
    """Pagination metadata (immutable, computed in Rust)."""
    total: int
    page: int
    per_page: int
    total_pages: int
    has_next: bool
    has_prev: bool
    offset: int
    from_item: int
    to_item: int

    def to_dict(self) -> Dict[str, Any]: ...

def paginate(total: int, page: int = 1, per_page: int = 20) -> PageInfo:
    """Compute pagination metadata."""
    ...

def encode_cursor(offset: int) -> str:
    """Encode an offset into an opaque cursor string."""
    ...

def decode_cursor(cursor: str) -> int:
    """Decode a cursor string back to an integer offset."""
    ...


# ============================================================================
# Utils: Crypto / Encoding / IDs
# ============================================================================

def random_token(length: int = 32) -> str:
    """Generate a cryptographically-secure URL-safe token."""
    ...

def random_bytes(n: int) -> bytes:
    """Generate n cryptographically-secure random bytes."""
    ...

def hmac_sha256_hex(key: str, data: str) -> str:
    """Compute HMAC-SHA-256 hex digest."""
    ...

def hmac_sha256_bytes(key: bytes, data: bytes) -> bytes:
    """Compute HMAC-SHA-256 from raw bytes, return raw bytes."""
    ...

def sha256_hex(data: str) -> str:
    """Compute SHA-256 hex digest of a string."""
    ...

def secure_compare(a: bytes, b: bytes) -> bool:
    """Constant-time comparison (timing-attack safe)."""
    ...

def b64_encode(data: bytes) -> str:
    """Encode bytes to standard Base64."""
    ...

def b64_decode(data: str) -> Optional[bytes]:
    """Decode standard Base64.  Returns None on invalid input."""
    ...

def b64url_encode(data: bytes) -> str:
    """Encode bytes to URL-safe Base64 (no padding)."""
    ...

def b64url_decode(data: str) -> Optional[bytes]:
    """Decode URL-safe Base64.  Returns None on invalid input."""
    ...

def uuid_v4() -> str:
    """Generate a UUID v4 (random)."""
    ...

def uuid_v7() -> str:
    """Generate a UUID v7 (time-sortable)."""
    ...

def fast_hash(data: str) -> int:
    """Compute xxHash3-64 of a string (non-cryptographic)."""
    ...

def fast_hash_bytes(data: bytes) -> int:
    """Compute xxHash3-64 of raw bytes (non-cryptographic)."""
    ...


# ============================================================================
# Utils: Time Helpers
# ============================================================================

def now_ms() -> int:
    """Current UTC Unix timestamp in milliseconds."""
    ...

def now_sec() -> int:
    """Current UTC Unix timestamp in seconds."""
    ...

def now_iso() -> str:
    """Current UTC time as ISO 8601 string."""
    ...

def format_timestamp(ts_secs: int) -> str:
    """Format a Unix timestamp (seconds) to ISO 8601 UTC."""
    ...

def parse_iso(s: str) -> Optional[int]:
    """Parse ISO 8601 datetime to Unix seconds.  Returns None on failure."""
    ...

def relative_time(ts_secs: int) -> str:
    """Human-readable relative time (e.g. '3 hours ago')."""
    ...

def elapsed_ms(start_ms: int) -> int:
    """Elapsed milliseconds from start_ms to now."""
    ...

def ms_to_sec(ms: int) -> int:
    """Convert milliseconds to seconds."""
    ...

def sec_to_ms(sec: int) -> int:
    """Convert seconds to milliseconds."""
    ...
