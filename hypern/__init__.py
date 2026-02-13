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
    # Database
    "Database",
    "get_database",
]
