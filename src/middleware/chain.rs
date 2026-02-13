use pyo3::prelude::*;
use std::collections::HashMap;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;

use bytes::Bytes;
use parking_lot::RwLock;

use crate::http::method::HttpMethod;

/// The result of middleware execution
#[pyclass]
#[derive(Debug, Clone)]
pub enum MiddlewareResult {
    /// Continue to the next middleware/handler
    Continue(),
    /// Short-circuit and return a response immediately
    Response(MiddlewareResponse),
    /// An error occurred
    Error(MiddlewareError),
}

/// A response that can be returned by middleware to short-circuit the chain
#[pyclass]
#[derive(Debug, Clone)]
pub struct MiddlewareResponse {
    #[pyo3(get, set)]
    pub status: u16,
    #[pyo3(get, set)]
    pub headers: Vec<(String, String)>,
    #[pyo3(get, set)]
    pub body: Vec<u8>,
}

#[pymethods]
impl MiddlewareResponse {
    #[new]
    pub fn new(status: u16) -> Self {
        Self {
            status,
            headers: Vec::new(),
            body: Vec::new(),
        }
    }

    #[pyo3(name = "with_status")]
    pub fn with_status_py(&mut self, status: u16) {
        self.status = status;
    }

    #[pyo3(name = "with_header")]
    pub fn with_header_py(&mut self, key: String, value: String) {
        self.headers.push((key, value));
    }

    #[pyo3(name = "with_body")]
    pub fn with_body_py(&mut self, body: Vec<u8>) {
        self.body = body;
    }

    #[pyo3(name = "with_json_body")]
    pub fn with_json_body_py(&mut self, body: String) {
        self.headers
            .push(("content-type".to_string(), "application/json".to_string()));
        self.body = body.into_bytes();
    }

    #[pyo3(name = "with_text_body")]
    pub fn with_text_body_py(&mut self, body: String) {
        self.headers
            .push(("content-type".to_string(), "text/plain".to_string()));
        self.body = body.into_bytes();
    }
}

impl MiddlewareResponse {
    pub fn with_status(mut self, status: u16) -> Self {
        self.status = status;
        self
    }

    pub fn with_header(mut self, key: impl Into<String>, value: impl Into<String>) -> Self {
        self.headers.push((key.into(), value.into()));
        self
    }

    pub fn with_body(mut self, body: impl Into<Vec<u8>>) -> Self {
        self.body = body.into();
        self
    }

    pub fn with_json_body(mut self, body: impl AsRef<str>) -> Self {
        self.headers
            .push(("content-type".to_string(), "application/json".to_string()));
        self.body = body.as_ref().as_bytes().to_vec();
        self
    }

    pub fn with_text_body(mut self, body: impl Into<String>) -> Self {
        self.headers
            .push(("content-type".to_string(), "text/plain".to_string()));
        self.body = body.into().into_bytes();
        self
    }

    /// Create a 400 Bad Request response
    pub fn bad_request(message: impl Into<String>) -> Self {
        Self::new(400).with_text_body(message)
    }

    /// Create a 401 Unauthorized response
    pub fn unauthorized(message: impl Into<String>) -> Self {
        Self::new(401).with_text_body(message)
    }

    /// Create a 403 Forbidden response
    pub fn forbidden(message: impl Into<String>) -> Self {
        Self::new(403).with_text_body(message)
    }

    /// Create a 404 Not Found response
    pub fn not_found(message: impl Into<String>) -> Self {
        Self::new(404).with_text_body(message)
    }

    /// Create a 429 Too Many Requests response
    pub fn too_many_requests(message: impl Into<String>) -> Self {
        Self::new(429).with_text_body(message)
    }

    /// Create a 500 Internal Server Error response
    pub fn internal_error(message: impl Into<String>) -> Self {
        Self::new(500).with_text_body(message)
    }

    /// Create a 503 Service Unavailable response
    pub fn service_unavailable(message: impl Into<String>) -> Self {
        Self::new(503).with_text_body(message)
    }
}

/// Error information from middleware
#[pyclass]
#[derive(Debug, Clone)]
pub struct MiddlewareError {
    #[pyo3(get, set)]
    pub code: String,
    #[pyo3(get, set)]
    pub message: String,
    #[pyo3(get, set)]
    pub status: u16,
}

#[pymethods]
impl MiddlewareError {
    #[new]
    pub fn new(code: String, message: String, status: u16) -> Self {
        Self {
            code,
            message,
            status,
        }
    }
}

impl MiddlewareError {
    /// Convert to a response
    pub fn to_response(&self) -> MiddlewareResponse {
        MiddlewareResponse::new(self.status).with_json_body(format!(
            r#"{{"error":"{}","message":"{}"}}"#,
            self.code, self.message
        ))
    }
}

/// Context passed through the middleware chain - contains request data and mutable state
#[pyclass]
#[derive(Clone)]
pub struct MiddlewareContext {
    // Request data - now mutable to allow middleware modifications
    pub path: Arc<RwLock<String>>,
    pub method: HttpMethod,
    pub headers: Arc<RwLock<HashMap<String, String>>>,
    pub query_string: Arc<RwLock<String>>,
    pub query_params: Arc<RwLock<HashMap<String, String>>>,
    pub path_params: Arc<RwLock<HashMap<String, String>>>,
    pub body: Arc<RwLock<Option<Bytes>>>,

    // Middleware state (mutable, shared between middleware)
    pub state: Arc<RwLock<MiddlewareState>>,

    // Response modifications (accumulated by middleware)
    pub response_headers: Arc<RwLock<Vec<(String, String)>>>,

    // Timing information
    pub start_time: std::time::Instant,

    // Request ID for tracing
    pub request_id: Arc<str>,
}

/// Mutable state that can be set by middleware and read by handlers
#[pyclass]
#[derive(Default, Clone)]
pub struct MiddlewareState {
    /// Custom key-value store for middleware communication
    pub values: HashMap<String, StateValue>,

    /// User ID if authenticated
    #[pyo3(get, set)]
    pub user_id: Option<String>,

    /// Request is authenticated
    #[pyo3(get, set)]
    pub is_authenticated: bool,

    /// Additional roles/permissions
    #[pyo3(get, set)]
    pub roles: Vec<String>,

    /// Trace/correlation ID
    #[pyo3(get, set)]
    pub trace_id: Option<String>,
}

/// A value that can be stored in middleware state
#[pyclass]
#[derive(Debug, Clone)]
pub enum StateValue {
    String(String),
    Int(i64),
    Float(f64),
    Bool(bool),
    Bytes(Vec<u8>),
}

impl StateValue {
    pub fn as_string(&self) -> Option<&str> {
        match self {
            StateValue::String(s) => Some(s),
            _ => None,
        }
    }

    pub fn as_int(&self) -> Option<i64> {
        match self {
            StateValue::Int(i) => Some(*i),
            _ => None,
        }
    }

    pub fn as_bool(&self) -> Option<bool> {
        match self {
            StateValue::Bool(b) => Some(*b),
            _ => None,
        }
    }
}

#[pymethods]
impl MiddlewareContext {
    #[getter]
    pub fn path(&self) -> String {
        self.path.read().clone()
    }

    #[getter]
    pub fn method(&self) -> HttpMethod {
        self.method
    }

    #[getter]
    pub fn query_string(&self) -> String {
        self.query_string.read().clone()
    }

    #[getter]
    pub fn request_id(&self) -> String {
        self.request_id.to_string()
    }

    /// Get a header value (case-insensitive)
    #[pyo3(name = "get_header")]
    pub fn get_header_py(&self, name: &str) -> Option<String> {
        self.headers.read().get(&name.to_lowercase()).cloned()
    }

    /// Set a header value
    #[pyo3(name = "set_header")]
    pub fn set_header_py(&self, name: String, value: String) {
        self.headers.write().insert(name.to_lowercase(), value);
    }

    /// Remove a header
    #[pyo3(name = "remove_header")]
    pub fn remove_header_py(&self, name: &str) -> Option<String> {
        self.headers.write().remove(&name.to_lowercase())
    }

    /// Get a query parameter
    #[pyo3(name = "get_query")]
    pub fn get_query_py(&self, name: &str) -> Option<String> {
        self.query_params.read().get(name).cloned()
    }

    /// Set a query parameter
    #[pyo3(name = "set_query")]
    pub fn set_query_py(&self, name: String, value: String) {
        self.query_params.write().insert(name, value);
    }

    /// Remove a query parameter
    #[pyo3(name = "remove_query")]
    pub fn remove_query_py(&self, name: &str) -> Option<String> {
        self.query_params.write().remove(name)
    }

    /// Get a path parameter
    pub fn get_param(&self, name: &str) -> Option<String> {
        self.path_params.read().get(name).cloned()
    }

    /// Set a path parameter
    #[pyo3(name = "set_param")]
    pub fn set_param_py(&self, name: String, value: String) {
        self.path_params.write().insert(name, value);
    }

    /// Set the request body
    #[pyo3(name = "set_body")]
    pub fn set_body_py(&self, body: Vec<u8>) {
        *self.body.write() = Some(Bytes::from(body));
    }

    /// Set the request body from string
    #[pyo3(name = "set_body_str")]
    pub fn set_body_str_py(&self, body: String) {
        *self.body.write() = Some(Bytes::from(body.into_bytes()));
    }

    /// Clear the request body
    #[pyo3(name = "clear_body")]
    pub fn clear_body_py(&self) {
        *self.body.write() = None;
    }

    /// Set the request path
    #[pyo3(name = "set_path")]
    pub fn set_path_py(&self, path: String) {
        *self.path.write() = path;
    }

    /// Set the query string
    #[pyo3(name = "set_query_string")]
    pub fn set_query_string_py(&self, query_string: String) {
        *self.query_string.write() = query_string;
    }

    /// Add a response header (will be added to the final response)
    #[pyo3(name = "add_response_header")]
    pub fn add_response_header_py(&self, name: String, value: String) {
        self.response_headers.write().push((name, value));
    }

    /// Set a state value
    #[pyo3(name = "set_state")]
    pub fn set_state_py(&self, key: String, value: StateValue) {
        self.state.write().values.insert(key, value);
    }

    /// Get a state value
    pub fn get_state(&self, key: &str) -> Option<StateValue> {
        self.state.read().values.get(key).cloned()
    }

    /// Set the user as authenticated
    #[pyo3(name = "set_authenticated")]
    pub fn set_authenticated_py(&self, user_id: String, roles: Vec<String>) {
        let mut state = self.state.write();
        state.is_authenticated = true;
        state.user_id = Some(user_id);
        state.roles = roles;
    }

    /// Check if authenticated
    pub fn is_authenticated(&self) -> bool {
        self.state.read().is_authenticated
    }

    /// Get user ID if authenticated
    pub fn user_id(&self) -> Option<String> {
        self.state.read().user_id.clone()
    }

    /// Check if user has a role
    pub fn has_role(&self, role: &str) -> bool {
        self.state.read().roles.contains(&role.to_string())
    }

    /// Get elapsed time since request start in seconds
    pub fn elapsed_seconds(&self) -> f64 {
        self.start_time.elapsed().as_secs_f64()
    }

    /// Get the request body
    pub fn body(&self, py: Python<'_>) -> Option<Py<pyo3::types::PyBytes>> {
        self.body
            .read()
            .as_ref()
            .map(|b| pyo3::types::PyBytes::new(py, b).into())
    }
}

impl MiddlewareContext {
    /// Create a new context from request data
    pub fn new(
        path: &str,
        method: HttpMethod,
        headers: HashMap<String, String>,
        query_string: &str,
        body: Option<Bytes>,
    ) -> Self {
        use xxhash_rust::xxh3::xxh3_64;

        // Generate request ID
        let now = std::time::Instant::now();
        let id_seed = format!("{}{}{:?}", path, query_string, now);
        let request_id = format!("{:016x}", xxh3_64(id_seed.as_bytes()));

        // Parse query params
        let query_params: HashMap<String, String> = if query_string.is_empty() {
            HashMap::new()
        } else {
            form_urlencoded::parse(query_string.as_bytes())
                .into_owned()
                .collect()
        };

        Self {
            path: Arc::new(RwLock::new(path.to_string())),
            method,
            headers: Arc::new(RwLock::new(headers)),
            query_string: Arc::new(RwLock::new(query_string.to_string())),
            query_params: Arc::new(RwLock::new(query_params)),
            path_params: Arc::new(RwLock::new(HashMap::new())),
            body: Arc::new(RwLock::new(body)),
            state: Arc::new(RwLock::new(MiddlewareState::default())),
            response_headers: Arc::new(RwLock::new(Vec::new())),
            start_time: now,
            request_id: Arc::from(request_id),
        }
    }

    /// Get a header value (case-insensitive)
    pub fn get_header(&self, name: &str) -> Option<String> {
        self.headers.read().get(&name.to_lowercase()).cloned()
    }

    /// Set a header value
    pub fn set_header(&self, name: impl Into<String>, value: impl Into<String>) {
        self.headers
            .write()
            .insert(name.into().to_lowercase(), value.into());
    }

    /// Remove a header
    pub fn remove_header(&self, name: &str) -> Option<String> {
        self.headers.write().remove(&name.to_lowercase())
    }

    /// Get a query parameter
    pub fn get_query(&self, name: &str) -> Option<String> {
        self.query_params.read().get(name).cloned()
    }

    /// Set a query parameter
    pub fn set_query(&self, name: impl Into<String>, value: impl Into<String>) {
        self.query_params.write().insert(name.into(), value.into());
    }

    /// Remove a query parameter
    pub fn remove_query(&self, name: &str) -> Option<String> {
        self.query_params.write().remove(name)
    }

    /// Set a path parameter
    pub fn set_param(&self, name: impl Into<String>, value: impl Into<String>) {
        self.path_params.write().insert(name.into(), value.into());
    }

    /// Set the request body
    pub fn set_body(&self, body: impl Into<Vec<u8>>) {
        *self.body.write() = Some(Bytes::from(body.into()));
    }

    /// Set the request body from string
    pub fn set_body_str(&self, body: impl Into<String>) {
        *self.body.write() = Some(Bytes::from(body.into().into_bytes()));
    }

    /// Clear the request body
    pub fn clear_body(&self) {
        *self.body.write() = None;
    }

    /// Get the request path
    pub fn get_path(&self) -> String {
        self.path.read().clone()
    }

    /// Set the request path
    pub fn set_path(&self, path: impl Into<String>) {
        *self.path.write() = path.into();
    }

    /// Get the query string
    pub fn get_query_string(&self) -> String {
        self.query_string.read().clone()
    }

    /// Set the query string
    pub fn set_query_string(&self, query_string: impl Into<String>) {
        *self.query_string.write() = query_string.into();
    }

    /// Add a response header (will be added to the final response)
    pub fn add_response_header(&self, name: impl Into<String>, value: impl Into<String>) {
        self.response_headers
            .write()
            .push((name.into(), value.into()));
    }

    /// Get all response headers to be added
    pub fn get_response_headers(&self) -> Vec<(String, String)> {
        self.response_headers.read().clone()
    }

    /// Set a state value
    pub fn set_state(&self, key: impl Into<String>, value: StateValue) {
        self.state.write().values.insert(key.into(), value);
    }

    /// Set the user as authenticated
    pub fn set_authenticated(&self, user_id: impl Into<String>, roles: Vec<String>) {
        let mut state = self.state.write();
        state.is_authenticated = true;
        state.user_id = Some(user_id.into());
        state.roles = roles;
    }

    /// Set path parameters from a map
    pub fn set_params(&self, params: HashMap<String, String>) {
        *self.path_params.write() = params;
    }

    /// Get elapsed time since request start
    pub fn elapsed(&self) -> std::time::Duration {
        self.start_time.elapsed()
    }

    /// Get the request body as Bytes
    pub fn body_bytes(&self) -> Option<Bytes> {
        self.body.read().clone()
    }

    /// Take the body (leaves None in its place)
    pub fn take_body(&self) -> Option<Bytes> {
        self.body.write().take()
    }
}

/// The trait that all pure Rust middleware must implement
pub trait RustMiddleware: Send + Sync {
    /// The name of this middleware (for logging/debugging)
    fn name(&self) -> &'static str;

    /// Execute the middleware - returns a future for async execution
    fn execute<'a>(
        &'a self,
        ctx: &'a MiddlewareContext,
    ) -> Pin<Box<dyn Future<Output = MiddlewareResult> + Send + 'a>>;

    /// Optional: Check if this middleware should run for the given path
    /// Default returns true (run for all paths)
    fn applies_to(&self, _path: &str) -> bool {
        true
    }

    /// Optional: Check if this middleware should run for the given method
    /// Default returns true (run for all methods)
    fn applies_to_method(&self, _method: HttpMethod) -> bool {
        true
    }
}

/// A boxed middleware for type erasure
pub type BoxedMiddleware = Arc<dyn RustMiddleware>;

/// The middleware chain that executes middleware in order
pub struct MiddlewareChain {
    /// Middleware that runs before the handler
    before: Vec<BoxedMiddleware>,
    /// Middleware that runs after the handler (for response modification)
    after: Vec<BoxedMiddleware>,
    /// Error handling middleware
    error_handlers: Vec<BoxedMiddleware>,
}

impl Default for MiddlewareChain {
    fn default() -> Self {
        Self::new()
    }
}

impl Clone for MiddlewareChain {
    fn clone(&self) -> Self {
        Self {
            before: self.before.clone(),
            after: self.after.clone(),
            error_handlers: self.error_handlers.clone(),
        }
    }
}

impl MiddlewareChain {
    pub fn new() -> Self {
        Self {
            before: Vec::new(),
            after: Vec::new(),
            error_handlers: Vec::new(),
        }
    }

    /// Add middleware that runs before the handler
    pub fn use_before<M: RustMiddleware + 'static>(&mut self, middleware: M) {
        self.before.push(Arc::new(middleware));
    }

    /// Add middleware that runs after the handler  
    pub fn use_after<M: RustMiddleware + 'static>(&mut self, middleware: M) {
        self.after.push(Arc::new(middleware));
    }

    /// Add error handling middleware
    pub fn use_error<M: RustMiddleware + 'static>(&mut self, middleware: M) {
        self.error_handlers.push(Arc::new(middleware));
    }

    /// Add boxed middleware before handler
    pub fn use_before_boxed(&mut self, middleware: BoxedMiddleware) {
        self.before.push(middleware);
    }

    /// Add boxed middleware after handler
    pub fn use_after_boxed(&mut self, middleware: BoxedMiddleware) {
        self.after.push(middleware);
    }

    /// Execute all "before" middleware in order
    /// Returns Continue if all passed, or the first Response/Error
    pub async fn execute_before(&self, ctx: &MiddlewareContext) -> MiddlewareResult {
        for middleware in &self.before {
            // Check if middleware applies to this request
            let path = ctx.get_path();
            if !middleware.applies_to(&path) || !middleware.applies_to_method(ctx.method) {
                continue;
            }

            match middleware.execute(ctx).await {
                MiddlewareResult::Continue() => continue,
                result => return result,
            }
        }
        MiddlewareResult::Continue()
    }

    /// Execute all "after" middleware in order
    pub async fn execute_after(&self, ctx: &MiddlewareContext) -> MiddlewareResult {
        for middleware in &self.after {
            let path = ctx.get_path();
            if !middleware.applies_to(&path) || !middleware.applies_to_method(ctx.method) {
                continue;
            }

            match middleware.execute(ctx).await {
                MiddlewareResult::Continue() => continue,
                result => return result,
            }
        }
        MiddlewareResult::Continue()
    }

    /// Execute error handlers
    pub async fn execute_error(
        &self,
        ctx: &MiddlewareContext,
        error: &MiddlewareError,
    ) -> Option<MiddlewareResponse> {
        // Store error in context state for error handlers to access
        ctx.set_state(
            "error_code".to_string(),
            StateValue::String(error.code.clone()),
        );
        ctx.set_state(
            "error_message".to_string(),
            StateValue::String(error.message.clone()),
        );
        ctx.set_state(
            "error_status".to_string(),
            StateValue::Int(error.status as i64),
        );

        let path = ctx.get_path();
        for handler in &self.error_handlers {
            if !handler.applies_to(&path) {
                continue;
            }

            if let MiddlewareResult::Response(response) = handler.execute(ctx).await {
                return Some(response);
            }
        }

        // Default error response if no handler caught it
        Some(error.to_response())
    }

    /// Get counts for debugging
    pub fn stats(&self) -> (usize, usize, usize) {
        (
            self.before.len(),
            self.after.len(),
            self.error_handlers.len(),
        )
    }
}

/// Builder pattern for creating middleware chains
pub struct MiddlewareChainBuilder {
    chain: MiddlewareChain,
}

impl Default for MiddlewareChainBuilder {
    fn default() -> Self {
        Self::new()
    }
}

impl MiddlewareChainBuilder {
    pub fn new() -> Self {
        Self {
            chain: MiddlewareChain::new(),
        }
    }

    /// Add middleware that runs before handlers
    pub fn before<M: RustMiddleware + 'static>(mut self, middleware: M) -> Self {
        self.chain.use_before(middleware);
        self
    }

    /// Add middleware that runs after handlers
    pub fn after<M: RustMiddleware + 'static>(mut self, middleware: M) -> Self {
        self.chain.use_after(middleware);
        self
    }

    /// Add error handling middleware
    pub fn error<M: RustMiddleware + 'static>(mut self, middleware: M) -> Self {
        self.chain.use_error(middleware);
        self
    }

    /// Build the chain
    pub fn build(self) -> MiddlewareChain {
        self.chain
    }
}
