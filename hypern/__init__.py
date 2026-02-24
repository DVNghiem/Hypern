from ._hypern import (
    Context,
    DIContainer,
    TaskExecutor,
    TaskResult,
    TaskStatus,
    SSEEvent,
    SSEStream,
    StreamingResponse,
    FormData,
    UploadedFile,
    Request,
    Response,
    Route,
    # Database
    ConnectionPool,
    PoolConfig,
    PoolStatus,
    DbSession,
    get_db,
    finalize_db,
    # Reload / Health
    HealthCheck,
    ReloadConfig,
    ReloadManager,
    # Utils (Rust-accelerated)
    PageInfo,
    paginate,
)
from .application import Hypern, create_app, hypern

# Background tasks - global executor and utilities
from .tasks import (
    background,
    submit_task,
    get_task,
    get_task_executor,
    set_task_executor,
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

# Middleware (Rust-based)
from .middleware import (
    # Rust middleware
    CorsMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    TimeoutMiddleware,
    CompressionMiddleware,
    RequestIdMiddleware,
    LogMiddleware,
    BasicAuthMiddleware,
    # Utilities
    MiddlewareStack,
    after_request,
    before_request,
    middleware,
)

# Database module
from .database import Database, db as get_database

# Router module
from .router import RouteBuilder, Router
from .validation import (
    ValidationError,
    Validator,
    validate,
    validate_body,
    validate_params,
    validate_query,
)
from .openapi import (
    OpenAPIGenerator,
    api_doc,
    api_tags,
    setup_openapi_routes,
)

# Auth module
from .auth import (
    JWTAuth,
    JWTError,
    APIKeyAuth,
    RBACPolicy,
    requires_role,
    requires_permission,
)

# WebSocket module
from .websocket import (
    WebSocket,
    WebSocketState,
    WebSocketMessage,
    WebSocketDisconnect,
    WebSocketError,
    WebSocketRoom,
    WebSocketRoute,
    WebSocketRouter,
)

# Scheduler module
from .scheduler import (
    RetryPolicy,
    TaskMetrics,
    TaskMonitor,
    TaskScheduler,
    ScheduledTaskState,
    ScheduledTaskResult,
    CronExpression,
    periodic,
)

# Realtime module
from .realtime import (
    ChannelManager,
    ChannelStats,
    Subscriber,
    TopicMatcher,
    PresenceTracker,
    PresenceInfo,
    PresenceDiff,
    RealtimeBroadcast,
    BroadcastConfig,
    BroadcastStats,
    BroadcastSubscriber,
    BackpressurePolicy,
    HeartbeatMonitor,
    HeartbeatConfig,
    HeartbeatStats,
    RealtimeHub,
)


__version__ = "0.4.0"

__all__ = [
    # Core
    "Hypern",
    "create_app",
    "hypern",
    "Request",
    "Response",
    "Route",
    # File Uploads
    "FormData",
    "UploadedFile",
    # Dependency Injection
    "Context",
    "DIContainer",
    # Background Tasks
    "TaskExecutor",
    "TaskResult",
    "TaskStatus",
    "background",
    "submit_task",
    "get_task",
    "get_task_executor",
    "set_task_executor",
    # Streaming/SSE
    "SSEEvent",
    "SSEStream",
    "StreamingResponse",
    # Database
    "ConnectionPool",
    "PoolConfig",
    "PoolStatus",
    "DbSession",
    "get_db",
    "finalize_db",
    # Router
    "Router",
    "RouteBuilder",
    # Middleware (Rust-based)
    "CorsMiddleware",
    "RateLimitMiddleware",
    "SecurityHeadersMiddleware",
    "TimeoutMiddleware",
    "CompressionMiddleware",
    "RequestIdMiddleware",
    "LogMiddleware",
    "BasicAuthMiddleware",
    # Middleware utilities
    "MiddlewareStack",
    "middleware",
    "before_request",
    "after_request",
    # Exceptions
    "HTTPException",
    "BadRequest",
    "Unauthorized",
    "Forbidden",
    "NotFound",
    "MethodNotAllowed",
    "Conflict",
    "UnprocessableEntity",
    "TooManyRequests",
    "InternalServerError",
    "ServiceUnavailable",
    "ExceptionHandler",
    "exception_handler",
    "error_boundary",
    # Validation
    "ValidationError",
    "Validator",
    "validate_body",
    "validate_query",
    "validate_params",
    "validate",
    # OpenAPI
    "OpenAPIGenerator",
    "api_doc",
    "api_tags",
    "setup_openapi_routes",
    # Auth
    "JWTAuth",
    "JWTError",
    "APIKeyAuth",
    "RBACPolicy",
    "requires_role",
    "requires_permission",
    # WebSocket
    "WebSocket",
    "WebSocketState",
    "WebSocketMessage",
    "WebSocketDisconnect",
    "WebSocketError",
    "WebSocketRoom",
    "WebSocketRoute",
    "WebSocketRouter",
    # Scheduler
    "RetryPolicy",
    "TaskMetrics",
    "TaskMonitor",
    "TaskScheduler",
    "ScheduledTaskState",
    "ScheduledTaskResult",
    "CronExpression",
    "periodic",
    # Reload / Health
    "HealthCheck",
    "ReloadConfig",
    "ReloadManager",
    # Database
    "Database",
    "get_database",
    # Realtime
    "ChannelManager",
    "ChannelStats",
    "Subscriber",
    "TopicMatcher",
    "PresenceTracker",
    "PresenceInfo",
    "PresenceDiff",
    "RealtimeBroadcast",
    "BroadcastConfig",
    "BroadcastStats",
    "BroadcastSubscriber",
    "BackpressurePolicy",
    "HeartbeatMonitor",
    "HeartbeatConfig",
    "HeartbeatStats",
    "RealtimeHub",
    # Utils
    "PageInfo",
    "paginate",
]
