pub mod builtin;
pub mod chain;

// Re-export pure Rust middleware types
pub use chain::{
    BoxedMiddleware, MiddlewareChain, MiddlewareChainBuilder, MiddlewareContext, MiddlewareError,
    MiddlewareResponse, MiddlewareResult, MiddlewareState, RustMiddleware, StateValue,
};

// Re-export built-in middleware
pub use builtin::{
    BasicAuthMiddleware, CompressionMiddleware, CorsConfig, CorsMiddleware, LogAfterMiddleware,
    LogConfig, LogLevel, LogMiddleware, MethodMiddleware, PathMiddleware, RateLimitAlgorithm,
    RateLimitConfig, RateLimitMiddleware, RequestIdMiddleware, SecurityHeadersConfig,
    SecurityHeadersMiddleware, TimeoutMiddleware,
};

/// Convert a MiddlewareResponse to a hyper Response
pub fn middleware_response_to_hyper(
    response: MiddlewareResponse,
) -> hyper::Response<crate::body::HTTPResponseBody> {
    let mut builder = hyper::Response::builder().status(response.status);

    for (key, value) in &response.headers {
        builder = builder.header(key.as_str(), value.as_str());
    }

    builder
        .body(crate::body::full_http(response.body))
        .unwrap_or_else(|_| {
            hyper::Response::builder()
                .status(500)
                .body(crate::body::full_http(b"Internal Server Error".to_vec()))
                .unwrap()
        })
}
