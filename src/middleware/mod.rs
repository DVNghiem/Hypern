pub mod builtin;
pub mod chain;

use axum::body::Body;
use pyo3::prelude::*;

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

/// Convert a MiddlewareResponse to a hyper Response - optimized
pub fn middleware_response_to_hyper(response: MiddlewareResponse) -> axum::response::Response {
    let mut builder = axum::response::Response::builder().status(response.status);

    // Pre-set all headers
    for (key, value) in &response.headers {
        builder = builder.header(key.as_str(), value.as_str());
    }

    // Set content-length for better client compatibility
    builder = builder.header("content-length", response.body.len().to_string());

    builder.body(Body::from(response.body)).unwrap_or_else(|_| {
        axum::response::Response::builder()
            .status(500)
            .body(Body::from("Internal Server Error"))
            .unwrap()
    })
}

use crate::http::method::HttpMethod;
use std::sync::Arc;

#[pyclass(name = "CorsMiddleware")]
#[derive(Clone)]
pub struct PyCorsMiddleware {
    pub(crate) inner: Arc<CorsMiddleware>,
}

#[pymethods]
impl PyCorsMiddleware {
    /// Create a new CORS middleware with default permissive settings
    #[new]
    #[pyo3(signature = (
        allowed_origins = None,
        allowed_methods = None,
        allowed_headers = None,
        expose_headers = None,
        allow_credentials = false,
        max_age = 86400
    ))]
    pub fn new(
        allowed_origins: Option<Vec<String>>,
        allowed_methods: Option<Vec<String>>,
        allowed_headers: Option<Vec<String>>,
        expose_headers: Option<Vec<String>>,
        allow_credentials: bool,
        max_age: u32,
    ) -> Self {
        let mut config = CorsConfig::default();

        if let Some(origins) = allowed_origins {
            config.allowed_origins = origins;
        }

        if let Some(methods) = allowed_methods {
            config.allowed_methods = methods
                .iter()
                .filter_map(|m| HttpMethod::from_str(m))
                .collect();
        }

        if let Some(headers) = allowed_headers {
            config.allowed_headers = headers;
        }

        if let Some(expose) = expose_headers {
            config.expose_headers = expose;
        }

        config.allow_credentials = allow_credentials;
        config.max_age = max_age;

        Self {
            inner: Arc::new(CorsMiddleware::new(config)),
        }
    }

    /// Create a permissive CORS middleware that allows all origins
    #[staticmethod]
    pub fn permissive() -> Self {
        Self {
            inner: Arc::new(CorsMiddleware::permissive()),
        }
    }

    fn __repr__(&self) -> String {
        "CorsMiddleware(...)".to_string()
    }
}

#[pyclass(name = "RateLimitMiddleware")]
#[derive(Clone)]
pub struct PyRateLimitMiddleware {
    pub(crate) inner: Arc<RateLimitMiddleware>,
}

#[pymethods]
impl PyRateLimitMiddleware {
    /// Create a new rate limiting middleware
    ///
    /// Args:
    ///     max_requests: Maximum requests allowed in the window
    ///     window_secs: Window duration in seconds
    ///     algorithm: "fixed", "sliding", or "token_bucket"
    ///     key_header: Header to use for client identification (optional)
    ///     skip_paths: Paths to skip rate limiting (default: /health, /metrics)
    #[new]
    #[pyo3(signature = (
        max_requests = 100,
        window_secs = 60,
        algorithm = "sliding",
        key_header = None,
        skip_paths = None
    ))]
    pub fn new(
        max_requests: u32,
        window_secs: u64,
        algorithm: &str,
        key_header: Option<String>,
        skip_paths: Option<Vec<String>>,
    ) -> PyResult<Self> {
        let algo = match algorithm.to_lowercase().as_str() {
            "fixed" | "fixed_window" => RateLimitAlgorithm::FixedWindow,
            "sliding" | "sliding_window" => RateLimitAlgorithm::SlidingWindow,
            "token" | "token_bucket" => RateLimitAlgorithm::TokenBucket {
                bucket_size: max_requests,
                refill_rate: max_requests as f64 / window_secs as f64,
            },
            _ => {
                return Err(pyo3::exceptions::PyValueError::new_err(
                    "Invalid algorithm. Use 'fixed', 'sliding', or 'token_bucket'",
                ))
            }
        };

        let mut config = RateLimitConfig::new(max_requests, window_secs).with_algorithm(algo);

        if let Some(header) = key_header {
            config = config.with_key_header(header);
        }

        if let Some(paths) = skip_paths {
            config.skip_paths = paths;
        }

        Ok(Self {
            inner: Arc::new(RateLimitMiddleware::new(config)),
        })
    }

    fn __repr__(&self) -> String {
        "RateLimitMiddleware(...)".to_string()
    }
}

/// Python-accessible security headers middleware
///
/// Adds security headers to all responses:
/// - X-Content-Type-Options: nosniff
/// - X-Frame-Options: DENY (configurable)
/// - X-XSS-Protection: 1; mode=block
/// - Strict-Transport-Security (HSTS)
/// - Content-Security-Policy (CSP)
#[pyclass(name = "SecurityHeadersMiddleware")]
#[derive(Clone)]
pub struct PySecurityHeadersMiddleware {
    pub(crate) inner: Arc<SecurityHeadersMiddleware>,
}

#[pymethods]
impl PySecurityHeadersMiddleware {
    /// Create security headers middleware
    ///
    /// Args:
    ///     hsts: Enable HSTS (default: true)
    ///     hsts_max_age: HSTS max-age in seconds (default: 31536000 = 1 year)
    ///     frame_options: X-Frame-Options value (default: "DENY")
    ///     content_type_options: X-Content-Type-Options (default: true)
    ///     xss_protection: X-XSS-Protection (default: true)
    ///     csp: Content-Security-Policy (optional)
    #[new]
    #[pyo3(signature = (
        hsts = true,
        hsts_max_age = 31536000,
        frame_options = "DENY",
        content_type_options = true,
        xss_protection = true,
        csp = None
    ))]
    pub fn new(
        hsts: bool,
        hsts_max_age: u64,
        frame_options: &str,
        content_type_options: bool,
        xss_protection: bool,
        csp: Option<String>,
    ) -> Self {
        let hsts_value = if hsts {
            Some(format!("max-age={}; includeSubDomains", hsts_max_age))
        } else {
            None
        };

        let config = SecurityHeadersConfig {
            content_type_options,
            frame_options: Some(frame_options.to_string()),
            xss_protection,
            hsts: hsts_value,
            csp,
            referrer_policy: Some("strict-origin-when-cross-origin".to_string()),
            permissions_policy: None,
        };

        Self {
            inner: Arc::new(SecurityHeadersMiddleware::new(config)),
        }
    }

    /// Create with strict security defaults
    #[staticmethod]
    pub fn strict() -> Self {
        let config = SecurityHeadersConfig {
            content_type_options: true,
            frame_options: Some("DENY".to_string()),
            xss_protection: true,
            hsts: Some("max-age=31536000; includeSubDomains".to_string()),
            csp: Some("default-src 'self'".to_string()),
            referrer_policy: Some("no-referrer".to_string()),
            permissions_policy: Some("geolocation=(), microphone=(), camera=()".to_string()),
        };

        Self {
            inner: Arc::new(SecurityHeadersMiddleware::new(config)),
        }
    }

    fn __repr__(&self) -> String {
        "SecurityHeadersMiddleware(...)".to_string()
    }
}

/// Python-accessible timeout middleware
///
/// Enforces request timeout at the Rust/Tokio level for maximum efficiency.
#[pyclass(name = "TimeoutMiddleware")]
#[derive(Clone)]
pub struct PyTimeoutMiddleware {
    pub(crate) inner: Arc<TimeoutMiddleware>,
}

#[pymethods]
impl PyTimeoutMiddleware {
    /// Create a timeout middleware
    ///
    /// Args:
    ///     timeout_secs: Request timeout in seconds (default: 30)
    #[new]
    #[pyo3(signature = (timeout_secs = 30))]
    pub fn new(timeout_secs: u64) -> Self {
        Self {
            inner: Arc::new(TimeoutMiddleware::new(std::time::Duration::from_secs(
                timeout_secs,
            ))),
        }
    }

    fn __repr__(&self) -> String {
        "TimeoutMiddleware(...)".to_string()
    }
}

/// Python-accessible compression middleware
///
/// Compresses response bodies using gzip for smaller transfer sizes.
#[pyclass(name = "CompressionMiddleware")]
#[derive(Clone)]
pub struct PyCompressionMiddleware {
    pub(crate) inner: Arc<CompressionMiddleware>,
}

#[pymethods]
impl PyCompressionMiddleware {
    /// Create compression middleware
    ///
    /// Args:
    ///     min_size: Minimum response size to compress (default: 1024 bytes)
    #[new]
    #[pyo3(signature = (min_size = 1024))]
    pub fn new(min_size: usize) -> Self {
        Self {
            inner: Arc::new(CompressionMiddleware::new().with_min_size(min_size)),
        }
    }

    fn __repr__(&self) -> String {
        "CompressionMiddleware(...)".to_string()
    }
}

/// Python-accessible request ID middleware
///
/// Adds a unique request ID to each request for tracing.
#[pyclass(name = "RequestIdMiddleware")]
#[derive(Clone)]
pub struct PyRequestIdMiddleware {
    pub(crate) inner: Arc<RequestIdMiddleware>,
}

#[pymethods]
impl PyRequestIdMiddleware {
    /// Create request ID middleware
    ///
    /// Args:
    ///     header_name: Header name for the request ID (default: "X-Request-ID")
    #[new]
    #[pyo3(signature = (header_name = "X-Request-ID"))]
    pub fn new(header_name: &str) -> Self {
        Self {
            inner: Arc::new(RequestIdMiddleware::new().with_header(header_name)),
        }
    }

    fn __repr__(&self) -> String {
        "RequestIdMiddleware(...)".to_string()
    }
}

/// Python-accessible logging middleware
///
/// Logs incoming requests with method, path, and timing information.
#[pyclass(name = "LogMiddleware")]
#[derive(Clone)]
pub struct PyLogMiddleware {
    pub(crate) inner: Arc<LogMiddleware>,
}

#[pymethods]
impl PyLogMiddleware {
    /// Create logging middleware
    ///
    /// Args:
    ///     level: Log level - "debug", "info", "warn", "error" (default: "info")
    ///     log_headers: Whether to log request headers (default: false)
    ///     skip_paths: Paths to skip logging (default: ["/health", "/favicon.ico"])
    #[new]
    #[pyo3(signature = (
        level = "info",
        log_headers = false,
        skip_paths = None
    ))]
    pub fn new(level: &str, log_headers: bool, skip_paths: Option<Vec<String>>) -> Self {
        let log_level = match level.to_lowercase().as_str() {
            "debug" => LogLevel::Debug,
            "warn" | "warning" => LogLevel::Warn,
            "error" => LogLevel::Error,
            _ => LogLevel::Info,
        };

        let mut config = LogConfig::new().with_level(log_level);

        if log_headers {
            config = config.with_headers();
        }

        if let Some(paths) = skip_paths {
            for path in paths {
                config = config.skip_path(path);
            }
        }

        Self {
            inner: Arc::new(LogMiddleware::new(config)),
        }
    }

    /// Create with default settings
    #[staticmethod]
    pub fn default_logger() -> Self {
        Self {
            inner: Arc::new(LogMiddleware::default_logger()),
        }
    }

    fn __repr__(&self) -> String {
        "LogMiddleware(...)".to_string()
    }
}

/// Python-accessible basic authentication middleware
///
/// Implements HTTP Basic Authentication.
#[pyclass(name = "BasicAuthMiddleware")]
#[derive(Clone)]
pub struct PyBasicAuthMiddleware {
    pub(crate) inner: Arc<BasicAuthMiddleware>,
}

#[pymethods]
impl PyBasicAuthMiddleware {
    /// Create basic auth middleware
    ///
    /// Args:
    ///     realm: Authentication realm shown in browser dialog (default: "Restricted")
    ///     users: Dictionary of username -> password pairs
    #[new]
    #[pyo3(signature = (realm = "Restricted", users = None))]
    pub fn new(realm: &str, users: Option<std::collections::HashMap<String, String>>) -> Self {
        let mut middleware = BasicAuthMiddleware::new(realm);

        if let Some(user_map) = users {
            for (username, password) in user_map {
                middleware = middleware.add_user(username, password);
            }
        }

        Self {
            inner: Arc::new(middleware),
        }
    }

    fn __repr__(&self) -> String {
        "BasicAuthMiddleware(...)".to_string()
    }
}
