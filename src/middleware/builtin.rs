use std::collections::HashMap;
use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use dashmap::DashMap;
use parking_lot::RwLock;

use crate::http::method::HttpMethod;

use super::chain::{
    MiddlewareContext, MiddlewareResponse, MiddlewareResult, RustMiddleware, StateValue,
};

/// Configuration for CORS middleware
#[derive(Clone)]
pub struct CorsConfig {
    /// Allowed origins (use "*" for all, or specific origins)
    pub allowed_origins: Vec<String>,
    /// Allowed HTTP methods
    pub allowed_methods: Vec<HttpMethod>,
    /// Allowed headers
    pub allowed_headers: Vec<String>,
    /// Headers to expose to the client
    pub expose_headers: Vec<String>,
    /// Allow credentials
    pub allow_credentials: bool,
    /// Max age for preflight cache (in seconds)
    pub max_age: u32,
}

impl Default for CorsConfig {
    fn default() -> Self {
        Self {
            allowed_origins: vec!["*".to_string()],
            allowed_methods: vec![
                HttpMethod::GET,
                HttpMethod::POST,
                HttpMethod::PUT,
                HttpMethod::DELETE,
                HttpMethod::PATCH,
                HttpMethod::OPTIONS,
            ],
            allowed_headers: vec![
                "Content-Type".to_string(),
                "Authorization".to_string(),
                "X-Requested-With".to_string(),
            ],
            expose_headers: vec![],
            allow_credentials: false,
            max_age: 86400, // 24 hours
        }
    }
}

impl CorsConfig {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn allow_origin(mut self, origin: impl Into<String>) -> Self {
        self.allowed_origins.push(origin.into());
        self
    }

    pub fn allow_any_origin(mut self) -> Self {
        self.allowed_origins = vec!["*".to_string()];
        self
    }

    pub fn allow_method(mut self, method: HttpMethod) -> Self {
        if !self.allowed_methods.contains(&method) {
            self.allowed_methods.push(method);
        }
        self
    }

    pub fn allow_header(mut self, header: impl Into<String>) -> Self {
        self.allowed_headers.push(header.into());
        self
    }

    pub fn expose_header(mut self, header: impl Into<String>) -> Self {
        self.expose_headers.push(header.into());
        self
    }

    pub fn allow_credentials(mut self, allow: bool) -> Self {
        self.allow_credentials = allow;
        self
    }

    pub fn max_age(mut self, seconds: u32) -> Self {
        self.max_age = seconds;
        self
    }
}

/// CORS middleware for handling Cross-Origin Resource Sharing
pub struct CorsMiddleware {
    config: CorsConfig,
}

impl CorsMiddleware {
    pub fn new(config: CorsConfig) -> Self {
        Self { config }
    }

    pub fn permissive() -> Self {
        Self::new(CorsConfig::default())
    }

    fn is_origin_allowed(&self, origin: &str) -> bool {
        self.config
            .allowed_origins
            .iter()
            .any(|allowed| allowed == "*" || allowed == origin)
    }

    fn methods_string(&self) -> String {
        self.config
            .allowed_methods
            .iter()
            .map(|m| m.as_str())
            .collect::<Vec<_>>()
            .join(", ")
    }

    fn headers_string(&self) -> String {
        self.config.allowed_headers.join(", ")
    }
}

impl RustMiddleware for CorsMiddleware {
    fn name(&self) -> &'static str {
        "cors"
    }

    fn execute<'a>(
        &'a self,
        ctx: &'a MiddlewareContext,
    ) -> Pin<Box<dyn Future<Output = MiddlewareResult> + Send + 'a>> {
        Box::pin(async move {
            let origin = ctx.get_header("origin").unwrap_or_default();

            // If no origin header, this is not a CORS request
            if origin.is_empty() {
                return MiddlewareResult::Continue();
            }

            // Check if origin is allowed
            if !self.is_origin_allowed(&origin) {
                return MiddlewareResult::Response(MiddlewareResponse::forbidden(
                    "Origin not allowed",
                ));
            }

            // Add CORS headers to response
            let allowed_origin = if self.config.allowed_origins.contains(&"*".to_string())
                && !self.config.allow_credentials
            {
                "*".to_string()
            } else {
                origin.clone()
            };

            ctx.add_response_header("Access-Control-Allow-Origin", allowed_origin);

            if self.config.allow_credentials {
                ctx.add_response_header("Access-Control-Allow-Credentials", "true");
            }

            if !self.config.expose_headers.is_empty() {
                ctx.add_response_header(
                    "Access-Control-Expose-Headers",
                    self.config.expose_headers.join(", "),
                );
            }

            // Handle preflight OPTIONS request
            if ctx.method == HttpMethod::OPTIONS {
                let mut response = MiddlewareResponse::new(204);
                response.headers.push((
                    "Access-Control-Allow-Origin".to_string(),
                    if self.config.allowed_origins.contains(&"*".to_string()) {
                        "*".to_string()
                    } else {
                        origin
                    },
                ));
                response.headers.push((
                    "Access-Control-Allow-Methods".to_string(),
                    self.methods_string(),
                ));
                response.headers.push((
                    "Access-Control-Allow-Headers".to_string(),
                    self.headers_string(),
                ));
                response.headers.push((
                    "Access-Control-Max-Age".to_string(),
                    self.config.max_age.to_string(),
                ));

                if self.config.allow_credentials {
                    response.headers.push((
                        "Access-Control-Allow-Credentials".to_string(),
                        "true".to_string(),
                    ));
                }

                return MiddlewareResult::Response(response);
            }

            MiddlewareResult::Continue()
        })
    }
}

/// Rate limiting algorithm
#[derive(Clone, Copy)]
pub enum RateLimitAlgorithm {
    /// Fixed window - simple counter reset at fixed intervals
    FixedWindow,
    /// Sliding window - smoother rate limiting
    SlidingWindow,
    /// Token bucket - allows bursts
    TokenBucket { bucket_size: u32, refill_rate: f64 },
}

/// Configuration for rate limiting
#[derive(Clone)]
pub struct RateLimitConfig {
    /// Maximum requests per window
    pub max_requests: u32,
    /// Window duration
    pub window: Duration,
    /// Algorithm to use
    pub algorithm: RateLimitAlgorithm,
    /// Key extractor - how to identify clients (default: IP from X-Forwarded-For or peer)
    pub key_header: Option<String>,
    /// Skip rate limiting for certain paths
    pub skip_paths: Vec<String>,
}

impl Default for RateLimitConfig {
    fn default() -> Self {
        Self {
            max_requests: 100,
            window: Duration::from_secs(60),
            algorithm: RateLimitAlgorithm::SlidingWindow,
            key_header: None,
            skip_paths: vec!["/health".to_string(), "/metrics".to_string()],
        }
    }
}

impl RateLimitConfig {
    pub fn new(max_requests: u32, window_secs: u64) -> Self {
        Self {
            max_requests,
            window: Duration::from_secs(window_secs),
            ..Default::default()
        }
    }

    pub fn with_algorithm(mut self, algorithm: RateLimitAlgorithm) -> Self {
        self.algorithm = algorithm;
        self
    }

    pub fn with_key_header(mut self, header: impl Into<String>) -> Self {
        self.key_header = Some(header.into());
        self
    }

    pub fn skip_path(mut self, path: impl Into<String>) -> Self {
        self.skip_paths.push(path.into());
        self
    }
}

/// Per-client rate limit state
struct RateLimitState {
    count: AtomicU64,
    window_start: RwLock<Instant>,
    // For token bucket
    tokens: RwLock<f64>,
    last_refill: RwLock<Instant>,
}

impl RateLimitState {
    fn new() -> Self {
        let now = Instant::now();
        Self {
            count: AtomicU64::new(0),
            window_start: RwLock::new(now),
            tokens: RwLock::new(0.0),
            last_refill: RwLock::new(now),
        }
    }
}

/// Rate limiting middleware
pub struct RateLimitMiddleware {
    config: RateLimitConfig,
    clients: DashMap<String, Arc<RateLimitState>>,
}

impl RateLimitMiddleware {
    pub fn new(config: RateLimitConfig) -> Self {
        Self {
            config,
            clients: DashMap::new(),
        }
    }

    fn get_client_key(&self, ctx: &MiddlewareContext) -> String {
        // Try custom header first
        if let Some(header) = &self.config.key_header {
            if let Some(value) = ctx.get_header(header) {
                return value.clone();
            }
        }

        // Try X-Forwarded-For
        if let Some(xff) = ctx.get_header("x-forwarded-for") {
            // Take first IP (client IP)
            return xff
                .split(',')
                .next()
                .unwrap_or("unknown")
                .trim()
                .to_string();
        }

        // Try X-Real-IP
        if let Some(real_ip) = ctx.get_header("x-real-ip") {
            return real_ip.clone();
        }

        // Fallback
        "unknown".to_string()
    }

    fn check_fixed_window(&self, state: &RateLimitState) -> (bool, u64) {
        let now = Instant::now();
        let mut window_start = state.window_start.write();

        // Check if window has expired
        if now.duration_since(*window_start) >= self.config.window {
            *window_start = now;
            state.count.store(1, Ordering::SeqCst);
            return (true, self.config.max_requests as u64 - 1);
        }

        let count = state.count.fetch_add(1, Ordering::SeqCst) + 1;
        let remaining = (self.config.max_requests as u64).saturating_sub(count);
        (count <= self.config.max_requests as u64, remaining)
    }

    fn check_sliding_window(&self, state: &RateLimitState) -> (bool, u64) {
        let now = Instant::now();
        let mut window_start = state.window_start.write();
        let elapsed = now.duration_since(*window_start);

        if elapsed >= self.config.window {
            // Window fully expired, reset
            *window_start = now;
            state.count.store(1, Ordering::SeqCst);
            return (true, self.config.max_requests as u64 - 1);
        }

        // Calculate weighted count based on position in window
        let window_ratio = elapsed.as_secs_f64() / self.config.window.as_secs_f64();
        let prev_count = state.count.load(Ordering::SeqCst);
        let weighted_count = (prev_count as f64 * (1.0 - window_ratio)) as u64;

        let new_count = weighted_count + 1;
        state.count.store(new_count, Ordering::SeqCst);

        let remaining = (self.config.max_requests as u64).saturating_sub(new_count);
        (new_count <= self.config.max_requests as u64, remaining)
    }

    fn check_token_bucket(
        &self,
        state: &RateLimitState,
        bucket_size: u32,
        refill_rate: f64,
    ) -> (bool, u64) {
        let now = Instant::now();
        let mut tokens = state.tokens.write();
        let mut last_refill = state.last_refill.write();

        // Refill tokens based on time elapsed
        let elapsed = now.duration_since(*last_refill).as_secs_f64();
        *tokens = (*tokens + elapsed * refill_rate).min(bucket_size as f64);
        *last_refill = now;

        // Try to consume a token
        if *tokens >= 1.0 {
            *tokens -= 1.0;
            (true, *tokens as u64)
        } else {
            (false, 0)
        }
    }
}

impl RustMiddleware for RateLimitMiddleware {
    fn name(&self) -> &'static str {
        "rate_limit"
    }

    fn execute<'a>(
        &'a self,
        ctx: &'a MiddlewareContext,
    ) -> Pin<Box<dyn Future<Output = MiddlewareResult> + Send + 'a>> {
        Box::pin(async move {
            // Skip certain paths
            let path = ctx.get_path();
            if self.config.skip_paths.iter().any(|p| path.starts_with(p)) {
                return MiddlewareResult::Continue();
            }

            let client_key = self.get_client_key(ctx);

            // Get or create client state
            let state = self
                .clients
                .entry(client_key.clone())
                .or_insert_with(|| Arc::new(RateLimitState::new()))
                .clone();

            let (allowed, remaining) = match self.config.algorithm {
                RateLimitAlgorithm::FixedWindow => self.check_fixed_window(&state),
                RateLimitAlgorithm::SlidingWindow => self.check_sliding_window(&state),
                RateLimitAlgorithm::TokenBucket {
                    bucket_size,
                    refill_rate,
                } => self.check_token_bucket(&state, bucket_size, refill_rate),
            };

            // Add rate limit headers
            ctx.add_response_header("X-RateLimit-Limit", self.config.max_requests.to_string());
            ctx.add_response_header("X-RateLimit-Remaining", remaining.to_string());
            ctx.add_response_header(
                "X-RateLimit-Reset",
                (self.config.window.as_secs()).to_string(),
            );

            if !allowed {
                ctx.add_response_header("Retry-After", self.config.window.as_secs().to_string());
                return MiddlewareResult::Response(
                    MiddlewareResponse::too_many_requests("Rate limit exceeded")
                        .with_header("Retry-After", self.config.window.as_secs().to_string()),
                );
            }

            MiddlewareResult::Continue()
        })
    }
}

/// Log level for request logging
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum LogLevel {
    Debug,
    Info,
    Warn,
    Error,
}

/// Configuration for request logging
#[derive(Clone)]
pub struct LogConfig {
    /// Log level
    pub level: LogLevel,
    /// Include headers in log
    pub log_headers: bool,
    /// Include body in log (careful with large bodies)
    pub log_body: bool,
    /// Max body size to log
    pub max_body_log_size: usize,
    /// Skip logging for certain paths
    pub skip_paths: Vec<String>,
    /// Custom log format (uses placeholders like {method}, {path}, {status}, {duration})
    pub format: Option<String>,
}

impl Default for LogConfig {
    fn default() -> Self {
        Self {
            level: LogLevel::Info,
            log_headers: false,
            log_body: false,
            max_body_log_size: 1024,
            skip_paths: vec!["/health".to_string(), "/favicon.ico".to_string()],
            format: None,
        }
    }
}

impl LogConfig {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_level(mut self, level: LogLevel) -> Self {
        self.level = level;
        self
    }

    pub fn with_headers(mut self) -> Self {
        self.log_headers = true;
        self
    }

    pub fn skip_path(mut self, path: impl Into<String>) -> Self {
        self.skip_paths.push(path.into());
        self
    }
}

/// Request logging middleware
pub struct LogMiddleware {
    config: LogConfig,
}

impl LogMiddleware {
    pub fn new(config: LogConfig) -> Self {
        Self { config }
    }

    pub fn default_logger() -> Self {
        Self::new(LogConfig::default())
    }
}

impl RustMiddleware for LogMiddleware {
    fn name(&self) -> &'static str {
        "logger"
    }

    fn execute<'a>(
        &'a self,
        ctx: &'a MiddlewareContext,
    ) -> Pin<Box<dyn Future<Output = MiddlewareResult> + Send + 'a>> {
        Box::pin(async move {
            // Skip certain paths
            let path = ctx.get_path();
            if self.config.skip_paths.iter().any(|p| path.starts_with(p)) {
                return MiddlewareResult::Continue();
            }

            // Log the request (this runs before handler)
            let method = ctx.method.as_str();
            let request_id = &ctx.request_id;

            // Use tracing for structured logging
            tracing::info!(
                request_id = %request_id,
                method = %method,
                path = %path,
                "Incoming request"
            );

            if self.config.log_headers {
                let headers = ctx.headers.read();
                for (key, value) in headers.iter() {
                    tracing::debug!(
                        request_id = %request_id,
                        header_name = %key,
                        header_value = %value,
                        "Request header"
                    );
                }
            }

            // Store start time in state for after middleware
            ctx.set_state(
                "log_start_time",
                StateValue::Int(ctx.start_time.elapsed().as_nanos() as i64),
            );

            MiddlewareResult::Continue()
        })
    }
}

/// After-request logging middleware (logs response details)
pub struct LogAfterMiddleware {
    config: LogConfig,
}

impl LogAfterMiddleware {
    pub fn new(config: LogConfig) -> Self {
        Self { config }
    }
}

impl RustMiddleware for LogAfterMiddleware {
    fn name(&self) -> &'static str {
        "logger_after"
    }

    fn execute<'a>(
        &'a self,
        ctx: &'a MiddlewareContext,
    ) -> Pin<Box<dyn Future<Output = MiddlewareResult> + Send + 'a>> {
        Box::pin(async move {
            let path = ctx.get_path();
            if self.config.skip_paths.iter().any(|p| path.starts_with(p)) {
                return MiddlewareResult::Continue();
            }

            let duration = ctx.elapsed();
            let request_id = &ctx.request_id;

            tracing::info!(
                request_id = %request_id,
                duration_ms = duration.as_millis(),
                "Request completed"
            );

            MiddlewareResult::Continue()
        })
    }
}

/// Request ID middleware - ensures every request has a unique ID
pub struct RequestIdMiddleware {
    /// Header name to use for request ID
    header_name: String,
    /// Whether to trust incoming request ID header
    trust_incoming: bool,
}

impl RequestIdMiddleware {
    pub fn new() -> Self {
        Self {
            header_name: "X-Request-ID".to_string(),
            trust_incoming: true,
        }
    }

    pub fn with_header(mut self, header: impl Into<String>) -> Self {
        self.header_name = header.into();
        self
    }

    pub fn trust_incoming(mut self, trust: bool) -> Self {
        self.trust_incoming = trust;
        self
    }
}

impl Default for RequestIdMiddleware {
    fn default() -> Self {
        Self::new()
    }
}

impl RustMiddleware for RequestIdMiddleware {
    fn name(&self) -> &'static str {
        "request_id"
    }

    fn execute<'a>(
        &'a self,
        ctx: &'a MiddlewareContext,
    ) -> Pin<Box<dyn Future<Output = MiddlewareResult> + Send + 'a>> {
        Box::pin(async move {
            let request_id = if self.trust_incoming {
                ctx.get_header(&self.header_name.to_lowercase())
                    .unwrap_or_else(|| ctx.request_id.to_string())
            } else {
                ctx.request_id.to_string()
            };

            // Add to response headers
            ctx.add_response_header(&self.header_name, &request_id);

            // Store in state for other middleware/handlers
            ctx.set_state("request_id", StateValue::String(request_id));

            MiddlewareResult::Continue()
        })
    }
}

/// Security headers configuration
#[derive(Clone)]
pub struct SecurityHeadersConfig {
    /// X-Content-Type-Options
    pub content_type_options: bool,
    /// X-Frame-Options
    pub frame_options: Option<String>,
    /// X-XSS-Protection
    pub xss_protection: bool,
    /// Strict-Transport-Security
    pub hsts: Option<String>,
    /// Content-Security-Policy
    pub csp: Option<String>,
    /// Referrer-Policy
    pub referrer_policy: Option<String>,
    /// Permissions-Policy
    pub permissions_policy: Option<String>,
}

impl Default for SecurityHeadersConfig {
    fn default() -> Self {
        Self {
            content_type_options: true,
            frame_options: Some("DENY".to_string()),
            xss_protection: true,
            hsts: Some("max-age=31536000; includeSubDomains".to_string()),
            csp: None,
            referrer_policy: Some("strict-origin-when-cross-origin".to_string()),
            permissions_policy: None,
        }
    }
}

impl SecurityHeadersConfig {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_csp(mut self, policy: impl Into<String>) -> Self {
        self.csp = Some(policy.into());
        self
    }

    pub fn with_frame_options(mut self, option: impl Into<String>) -> Self {
        self.frame_options = Some(option.into());
        self
    }

    pub fn with_hsts(mut self, value: impl Into<String>) -> Self {
        self.hsts = Some(value.into());
        self
    }

    pub fn with_permissions_policy(mut self, policy: impl Into<String>) -> Self {
        self.permissions_policy = Some(policy.into());
        self
    }
}

/// Security headers middleware
pub struct SecurityHeadersMiddleware {
    config: SecurityHeadersConfig,
}

impl SecurityHeadersMiddleware {
    pub fn new(config: SecurityHeadersConfig) -> Self {
        Self { config }
    }

    pub fn default_headers() -> Self {
        Self::new(SecurityHeadersConfig::default())
    }
}

impl RustMiddleware for SecurityHeadersMiddleware {
    fn name(&self) -> &'static str {
        "security_headers"
    }

    fn execute<'a>(
        &'a self,
        ctx: &'a MiddlewareContext,
    ) -> Pin<Box<dyn Future<Output = MiddlewareResult> + Send + 'a>> {
        Box::pin(async move {
            if self.config.content_type_options {
                ctx.add_response_header("X-Content-Type-Options", "nosniff");
            }

            if let Some(ref frame_options) = self.config.frame_options {
                ctx.add_response_header("X-Frame-Options", frame_options);
            }

            if self.config.xss_protection {
                ctx.add_response_header("X-XSS-Protection", "1; mode=block");
            }

            if let Some(ref hsts) = self.config.hsts {
                ctx.add_response_header("Strict-Transport-Security", hsts);
            }

            if let Some(ref csp) = self.config.csp {
                ctx.add_response_header("Content-Security-Policy", csp);
            }

            if let Some(ref referrer) = self.config.referrer_policy {
                ctx.add_response_header("Referrer-Policy", referrer);
            }

            if let Some(ref permissions) = self.config.permissions_policy {
                ctx.add_response_header("Permissions-Policy", permissions);
            }

            MiddlewareResult::Continue()
        })
    }
}

/// Timeout middleware - sets a deadline for request processing
pub struct TimeoutMiddleware {
    timeout: Duration,
}

impl TimeoutMiddleware {
    pub fn new(timeout: Duration) -> Self {
        Self { timeout }
    }

    pub fn seconds(secs: u64) -> Self {
        Self::new(Duration::from_secs(secs))
    }

    pub fn millis(millis: u64) -> Self {
        Self::new(Duration::from_millis(millis))
    }
}

impl RustMiddleware for TimeoutMiddleware {
    fn name(&self) -> &'static str {
        "timeout"
    }

    fn execute<'a>(
        &'a self,
        ctx: &'a MiddlewareContext,
    ) -> Pin<Box<dyn Future<Output = MiddlewareResult> + Send + 'a>> {
        let timeout = self.timeout;
        Box::pin(async move {
            // Store deadline in context for handlers to check
            let deadline = ctx.start_time + timeout;
            ctx.set_state(
                "request_deadline",
                StateValue::Int(deadline.elapsed().as_nanos() as i64),
            );
            ctx.set_state(
                "request_timeout_ms",
                StateValue::Int(timeout.as_millis() as i64),
            );

            MiddlewareResult::Continue()
        })
    }
}

/// Compression middleware - marks responses for compression
pub struct CompressionMiddleware {
    /// Minimum size to compress
    min_size: usize,
    /// Content types to compress
    content_types: Vec<String>,
}

impl CompressionMiddleware {
    pub fn new() -> Self {
        Self {
            min_size: 1024,
            content_types: vec![
                "text/".to_string(),
                "application/json".to_string(),
                "application/javascript".to_string(),
                "application/xml".to_string(),
            ],
        }
    }

    pub fn with_min_size(mut self, size: usize) -> Self {
        self.min_size = size;
        self
    }

    pub fn with_content_type(mut self, content_type: impl Into<String>) -> Self {
        self.content_types.push(content_type.into());
        self
    }
}

impl Default for CompressionMiddleware {
    fn default() -> Self {
        Self::new()
    }
}

impl RustMiddleware for CompressionMiddleware {
    fn name(&self) -> &'static str {
        "compression"
    }

    fn execute<'a>(
        &'a self,
        ctx: &'a MiddlewareContext,
    ) -> Pin<Box<dyn Future<Output = MiddlewareResult> + Send + 'a>> {
        Box::pin(async move {
            // Check Accept-Encoding header
            let accept_encoding = ctx.get_header("accept-encoding").unwrap_or_default();

            let supports_gzip = accept_encoding.contains("gzip");
            let supports_deflate = accept_encoding.contains("deflate");
            let supports_br = accept_encoding.contains("br");

            // Store compression preference in state
            if supports_br {
                ctx.set_state("compression", StateValue::String("br".to_string()));
            } else if supports_gzip {
                ctx.set_state("compression", StateValue::String("gzip".to_string()));
            } else if supports_deflate {
                ctx.set_state("compression", StateValue::String("deflate".to_string()));
            }

            ctx.set_state(
                "compression_min_size",
                StateValue::Int(self.min_size as i64),
            );

            MiddlewareResult::Continue()
        })
    }
}

/// Basic authentication middleware
pub struct BasicAuthMiddleware {
    /// Username -> Password hash map
    credentials: HashMap<String, String>,
    /// Realm for WWW-Authenticate header
    realm: String,
}

impl BasicAuthMiddleware {
    pub fn new(realm: impl Into<String>) -> Self {
        Self {
            credentials: HashMap::new(),
            realm: realm.into(),
        }
    }

    pub fn add_user(mut self, username: impl Into<String>, password: impl Into<String>) -> Self {
        self.credentials.insert(username.into(), password.into());
        self
    }

    fn decode_basic_auth(&self, header: &str) -> Option<(String, String)> {
        let encoded = header.strip_prefix("Basic ")?;
        let decoded = base64_decode(encoded)?;
        let credentials = String::from_utf8(decoded).ok()?;
        let mut parts = credentials.splitn(2, ':');
        let username = parts.next()?.to_string();
        let password = parts.next()?.to_string();
        Some((username, password))
    }
}

// Simple base64 decoder (to avoid external dependency)
fn base64_decode(input: &str) -> Option<Vec<u8>> {
    const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

    let input = input.trim_end_matches('=');
    let mut output = Vec::with_capacity(input.len() * 3 / 4);
    let mut buffer: u32 = 0;
    let mut bits_collected: u8 = 0;

    for c in input.bytes() {
        let value = ALPHABET.iter().position(|&x| x == c)? as u32;
        buffer = (buffer << 6) | value;
        bits_collected += 6;

        if bits_collected >= 8 {
            bits_collected -= 8;
            output.push((buffer >> bits_collected) as u8);
            buffer &= (1 << bits_collected) - 1;
        }
    }

    Some(output)
}

impl RustMiddleware for BasicAuthMiddleware {
    fn name(&self) -> &'static str {
        "basic_auth"
    }

    fn execute<'a>(
        &'a self,
        ctx: &'a MiddlewareContext,
    ) -> Pin<Box<dyn Future<Output = MiddlewareResult> + Send + 'a>> {
        Box::pin(async move {
            let auth_header = match ctx.get_header("authorization") {
                Some(h) => h,
                None => {
                    return MiddlewareResult::Response(
                        MiddlewareResponse::unauthorized("Authentication required").with_header(
                            "WWW-Authenticate",
                            format!("Basic realm=\"{}\"", self.realm),
                        ),
                    );
                }
            };

            let (username, password) = match self.decode_basic_auth(&auth_header) {
                Some(creds) => creds,
                None => {
                    return MiddlewareResult::Response(MiddlewareResponse::unauthorized(
                        "Invalid authentication format",
                    ));
                }
            };

            // Check credentials
            match self.credentials.get(&username) {
                Some(stored_password) if stored_password == &password => {
                    ctx.set_authenticated(&username, vec![]);
                    MiddlewareResult::Continue()
                }
                _ => MiddlewareResult::Response(
                    MiddlewareResponse::unauthorized("Invalid credentials").with_header(
                        "WWW-Authenticate",
                        format!("Basic realm=\"{}\"", self.realm),
                    ),
                ),
            }
        })
    }
}

/// Wrapper that makes any middleware path-specific
pub struct PathMiddleware<M: RustMiddleware> {
    inner: M,
    paths: Vec<String>,
    exact: bool,
}

impl<M: RustMiddleware> PathMiddleware<M> {
    pub fn new(middleware: M, paths: Vec<String>) -> Self {
        Self {
            inner: middleware,
            paths,
            exact: false,
        }
    }

    pub fn exact(mut self) -> Self {
        self.exact = true;
        self
    }
}

impl<M: RustMiddleware> RustMiddleware for PathMiddleware<M> {
    fn name(&self) -> &'static str {
        self.inner.name()
    }

    fn applies_to(&self, path: &str) -> bool {
        if self.exact {
            self.paths.iter().any(|p| p == path)
        } else {
            self.paths.iter().any(|p| path.starts_with(p))
        }
    }

    fn execute<'a>(
        &'a self,
        ctx: &'a MiddlewareContext,
    ) -> Pin<Box<dyn Future<Output = MiddlewareResult> + Send + 'a>> {
        self.inner.execute(ctx)
    }
}

/// Wrapper that makes any middleware method-specific
pub struct MethodMiddleware<M: RustMiddleware> {
    inner: M,
    methods: Vec<HttpMethod>,
}

impl<M: RustMiddleware> MethodMiddleware<M> {
    pub fn new(middleware: M, methods: Vec<HttpMethod>) -> Self {
        Self {
            inner: middleware,
            methods,
        }
    }
}

impl<M: RustMiddleware> RustMiddleware for MethodMiddleware<M> {
    fn name(&self) -> &'static str {
        self.inner.name()
    }

    fn applies_to_method(&self, method: HttpMethod) -> bool {
        self.methods.contains(&method)
    }

    fn execute<'a>(
        &'a self,
        ctx: &'a MiddlewareContext,
    ) -> Pin<Box<dyn Future<Output = MiddlewareResult> + Send + 'a>> {
        self.inner.execute(ctx)
    }
}
