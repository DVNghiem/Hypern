from ._hypern import (
    BlockingExecutor,
    Context,
    FormData,
    # Reload / Health
    HealthCheck,
    # Logging
    # Utils (Rust-accelerated)
    PageInfo,
    ReloadConfig,
    ReloadManager,
    Request,
    Response,
    Route,
    SSEEvent,
    SSEStream,
    StreamingResponse,
    TaskExecutor,
    TaskResult,
    TaskStatus,
    UploadedFile,
    paginate,
)
from .application import Hypern, create_app, hypern

# Auth module
from .auth import (
    APIKeyAuth,
    JWTAuth,
    JWTError,
    RBACPolicy,
    requires_permission,
    requires_role,
)

# Blocking executor — GIL-free parallel execution
from .blocking import (
    blocking,
    blocking_map,
    blocking_parallel,
    blocking_run,
    get_default_executor,
    set_default_executor,
)

# Exceptions
from .exceptions import (
    BadRequest,
    Conflict,
    ExceptionHandler,
    Forbidden,
    HTTPException,
    InternalServerError,
    MethodNotAllowed,
    NotFound,
    ServiceUnavailable,
    TooManyRequests,
    Unauthorized,
    UnprocessableEntity,
    error_boundary,
    exception_handler,
)
from .injection import (
    Body,
    DependencyCycleError,
    Header,
    Inject,
    InjectionConfigurationError,
    Json,
    Path,
    Query,
)

# Middleware (Rust-based)
from .middleware import (
    BasicAuthMiddleware,
    CompressionMiddleware,
    # Rust middleware
    CorsMiddleware,
    # Utilities
    Middleware,
    MiddlewareStack,
    RateLimitMiddleware,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
    TimeoutMiddleware,
    middleware,
)
from .openapi import (
    OpenAPIGenerator,
    api_doc,
    api_tags,
    setup_openapi_routes,
)

# Realtime module
from .realtime import (
    BackpressurePolicy,
    BroadcastConfig,
    BroadcastStats,
    BroadcastSubscriber,
    ChannelManager,
    ChannelStats,
    HeartbeatConfig,
    HeartbeatMonitor,
    HeartbeatStats,
    PresenceDiff,
    PresenceInfo,
    PresenceTracker,
    RealtimeBroadcast,
    RealtimeHub,
    Subscriber,
    TopicMatcher,
)

# Router module
from .router import RouteBuilder, Router

# Scheduler module
from .scheduler import (
    CronExpression,
    RetryPolicy,
    ScheduledTaskResult,
    ScheduledTaskState,
    TaskMetrics,
    TaskMonitor,
    TaskScheduler,
    periodic,
)

# Background tasks - global executor and utilities
from .tasks import (
    background,
    get_task,
    get_task_executor,
    set_task_executor,
    submit_task,
)
from .validation import ValidationError

# WebSocket module
from .websocket import (
    WebSocket,
    WebSocketDisconnect,
    WebSocketError,
    WebSocketMessage,
    WebSocketRoom,
    WebSocketRoute,
    WebSocketRouter,
    WebSocketState,
)

__version__ = "0.4.0"

__all__ = [
    "APIKeyAuth",
    "BackpressurePolicy",
    "BadRequest",
    "BasicAuthMiddleware",
    "Body",
    # Blocking Executor
    "BlockingExecutor",
    "BroadcastConfig",
    "BroadcastStats",
    "BroadcastSubscriber",
    # Realtime
    "ChannelManager",
    "ChannelStats",
    "CompressionMiddleware",
    "Conflict",
    # Dependency Injection
    "Context",
    # Middleware (Rust-based)
    "CorsMiddleware",
    "CronExpression",
    "DependencyCycleError",
    "ExceptionHandler",
    "Forbidden",
    # File Uploads
    "FormData",
    # Exceptions
    "HTTPException",
    # Reload / Health
    "HealthCheck",
    "Header",
    "HeartbeatConfig",
    "HeartbeatMonitor",
    "HeartbeatStats",
    # Core
    "Hypern",
    "Inject",
    "InjectionConfigurationError",
    "InternalServerError",
    # Auth
    "JWTAuth",
    "JWTError",
    "Json",
    "MethodNotAllowed",
    # Middleware utilities
    "Middleware",
    "MiddlewareStack",
    "NotFound",
    # OpenAPI
    "OpenAPIGenerator",
    # Utils
    "PageInfo",
    "Path",
    "PresenceDiff",
    "PresenceInfo",
    "PresenceTracker",
    "RBACPolicy",
    "Query",
    "RateLimitMiddleware",
    "RealtimeBroadcast",
    "RealtimeHub",
    "ReloadConfig",
    "ReloadManager",
    "Request",
    "RequestIdMiddleware",
    "Response",
    # Scheduler
    "RetryPolicy",
    "Route",
    "RouteBuilder",
    # Router
    "Router",
    # Streaming/SSE
    "SSEEvent",
    "SSEStream",
    "ScheduledTaskResult",
    "ScheduledTaskState",
    "SecurityHeadersMiddleware",
    "ServiceUnavailable",
    "StreamingResponse",
    "Subscriber",
    # Background Tasks
    "TaskExecutor",
    "TaskMetrics",
    "TaskMonitor",
    "TaskResult",
    "TaskScheduler",
    "TaskStatus",
    "TimeoutMiddleware",
    "TooManyRequests",
    "TopicMatcher",
    "Unauthorized",
    "UnprocessableEntity",
    "UploadedFile",
    # Validation
    "ValidationError",
    # WebSocket
    "WebSocket",
    "WebSocketDisconnect",
    "WebSocketError",
    "WebSocketMessage",
    "WebSocketRoom",
    "WebSocketRoute",
    "WebSocketRouter",
    "WebSocketState",
    "api_doc",
    "api_tags",
    "background",
    "blocking",
    "blocking_map",
    "blocking_parallel",
    "blocking_run",
    "create_app",
    "error_boundary",
    "exception_handler",
    "get_default_executor",
    "get_task",
    "get_task_executor",
    "hypern",
    "middleware",
    "paginate",
    "periodic",
    "requires_permission",
    "requires_role",
    "set_default_executor",
    "set_task_executor",
    "setup_openapi_routes",
    "submit_task",
]
