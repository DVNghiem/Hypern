pub mod builtin;
pub mod chain;

// Re-export pure Rust middleware types
pub use chain::{
    MiddlewareChainBuilder,
    MiddlewareContext,
    MiddlewareError,
    MiddlewareResponse,
    MiddlewareResult,
    MiddlewareState,
    RustMiddleware,
    MiddlewareChain,
    StateValue,
    BoxedMiddleware,
};

// Re-export built-in middleware
pub use builtin::{
    BasicAuthMiddleware,
    CompressionMiddleware,
    CorsConfig,
    CorsMiddleware,
    LogConfig,
    LogLevel,
    LogMiddleware,
    LogAfterMiddleware,
    MethodMiddleware,
    PathMiddleware,
    RateLimitAlgorithm,
    RateLimitConfig,
    RateLimitMiddleware,
    RequestIdMiddleware,
    SecurityHeadersConfig,
    SecurityHeadersMiddleware,
    TimeoutMiddleware,
};
