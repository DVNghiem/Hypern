use axum::body::Body;
use axum::http::header::SERVER;
use axum::http::{HeaderMap, HeaderName, HeaderValue};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use smallvec::SmallVec;
use std::sync::atomic::{AtomicBool, AtomicU16, Ordering};
use std::sync::Arc;

type SmallString = smartstring::SmartString<smartstring::LazyCompact>;

/// Common content types
pub mod content_types {
    pub const JSON: &str = "application/json";
    pub const HTML: &str = "text/html; charset=utf-8";
    pub const TEXT: &str = "text/plain; charset=utf-8";
    pub const XML: &str = "application/xml";
    pub const FORM: &str = "application/x-www-form-urlencoded";
    pub const MULTIPART: &str = "multipart/form-data";
    pub const OCTET_STREAM: &str = "application/octet-stream";
    pub const CSS: &str = "text/css";
    pub const JS: &str = "application/javascript";
    pub const PNG: &str = "image/png";
    pub const JPEG: &str = "image/jpeg";
    pub const GIF: &str = "image/gif";
    pub const SVG: &str = "image/svg+xml";
    pub const PDF: &str = "application/pdf";
}

pub struct ResponseSlot {
    /// HTTP status code
    status: AtomicU16,
    /// Response headers (small vector optimization for common case)
    headers: parking_lot::RwLock<SmallVec<[(SmallString, SmallString); 8]>>,
    /// Response body
    body: parking_lot::RwLock<Vec<u8>>,
    /// Completion flag
    ready: AtomicBool,
    /// Whether response has been sent
    sent: AtomicBool,
}

impl ResponseSlot {
    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            status: AtomicU16::new(200),
            headers: parking_lot::RwLock::new(SmallVec::new()),
            body: parking_lot::RwLock::new(Vec::with_capacity(8192)),
            ready: AtomicBool::new(false),
            sent: AtomicBool::new(false),
        })
    }

    #[inline]
    pub fn set_status(&self, status: u16) {
        self.status.store(status, Ordering::Release);
    }

    #[inline]
    pub fn get_status(&self) -> u16 {
        self.status.load(Ordering::Acquire)
    }

    pub fn set_headers(&self, headers: impl IntoIterator<Item = (String, String)>) {
        let mut header_guard = self.headers.write();
        header_guard.clear();
        header_guard.extend(
            headers
                .into_iter()
                .map(|(k, v)| (SmallString::from(k), SmallString::from(v))),
        );
    }

    pub fn add_header(&self, key: String, value: String) {
        self.headers
            .write()
            .push((SmallString::from(key), SmallString::from(value)));
    }

    pub fn get_header(&self, key: &str) -> Option<String> {
        let key_lower = key.to_lowercase();
        self.headers
            .read()
            .iter()
            .find(|(k, _)| k.to_lowercase() == key_lower)
            .map(|(_, v)| v.to_string())
    }

    pub fn remove_header(&self, key: &str) {
        let key_lower = key.to_lowercase();
        self.headers
            .write()
            .retain(|(k, _)| k.to_lowercase() != key_lower);
    }

    pub fn set_body(&self, body: Vec<u8>) {
        *self.body.write() = body;
    }

    pub fn set_body_str(&self, body: String) {
        *self.body.write() = body.into_bytes();
    }

    pub fn append_body(&self, data: &[u8]) {
        self.body.write().extend_from_slice(data);
    }

    pub fn get_body_len(&self) -> usize {
        self.body.read().len()
    }

    #[inline]
    pub fn mark_ready(&self) {
        self.ready.store(true, Ordering::Release);
    }

    #[inline]
    pub fn is_ready(&self) -> bool {
        self.ready.load(Ordering::Acquire)
    }

    #[inline]
    pub fn mark_sent(&self) {
        self.sent.store(true, Ordering::Release);
    }

    #[inline]
    pub fn is_sent(&self) -> bool {
        self.sent.load(Ordering::Acquire)
    }

    pub fn into_response(self: Arc<Self>) -> axum::response::Response {
        let status = self.status.load(Ordering::Acquire);
        let headers = self.headers.read();
        let body = self.body.read();

        let mut header_map = HeaderMap::with_capacity(headers.len() + 2);
        for (key, value) in headers.iter() {
            if let (Ok(name), Ok(val)) = (
                HeaderName::from_bytes(key.as_bytes()),
                HeaderValue::from_str(value),
            ) {
                header_map.append(name, val);
            }
        }
        header_map
            .entry(SERVER)
            .or_insert(HeaderValue::from_static("Hypern"));

        // Set Content-Length explicitly for better client compatibility
        header_map.insert(axum::http::header::CONTENT_LENGTH, HeaderValue::from(body.len()));

        // Clone body data from the lock guard before creating the HTTP body
        let http_body = body.clone().into();

        let mut res = axum::response::Response::new(http_body);
        *res.status_mut() = axum::http::StatusCode::from_u16(status).unwrap_or(axum::http::StatusCode::OK);
        *res.headers_mut() = header_map;
        res
    }
}

impl Default for ResponseSlot {
    fn default() -> Self {
        Self {
            status: AtomicU16::new(200),
            headers: parking_lot::RwLock::new(SmallVec::new()),
            body: parking_lot::RwLock::new(Vec::with_capacity(4096)),
            ready: AtomicBool::new(false),
            sent: AtomicBool::new(false),
        }
    }
}

/// Response writer for efficient response construction
/// Implements Express.js-like response API
#[pyclass]
pub struct Response {
    slot: Arc<ResponseSlot>,
}

#[pymethods]
impl Response {
    // ========== Status Methods ==========
    
    /// Set the HTTP status code (chainable)
    #[pyo3(signature = (status=200))]
    pub fn status<'py>(pyself: PyRef<'py, Self>, status: u16) -> PyRef<'py, Self> {
        pyself.slot.set_status(status);
        pyself
    }

    /// Get the current status code
    #[getter]
    pub fn status_code(&self) -> u16 {
        self.slot.get_status()
    }

    // ========== Header Methods ==========

    /// Set a response header (chainable)
    pub fn header<'py>(pyself: PyRef<'py, Self>, key: &str, value: &str) -> PyRef<'py, Self> {
        pyself.slot.add_header(key.to_string(), value.to_string());
        pyself
    }

    /// Alias for header() - Express.js compatibility
    pub fn set<'py>(pyself: PyRef<'py, Self>, key: &str, value: &str) -> PyRef<'py, Self> {
        pyself.slot.add_header(key.to_string(), value.to_string());
        pyself
    }

    /// Get a response header value
    pub fn get(&self, key: &str) -> Option<String> {
        self.slot.get_header(key)
    }

    /// Remove a header
    pub fn remove_header<'py>(pyself: PyRef<'py, Self>, key: &str) -> PyRef<'py, Self> {
        pyself.slot.remove_header(key);
        pyself
    }

    /// Set multiple headers at once
    pub fn headers<'py>(pyself: PyRef<'py, Self>, headers: &Bound<'_, PyDict>) -> PyResult<PyRef<'py, Self>> {
        for (key, value) in headers.iter() {
            let k: String = key.extract()?;
            let v: String = value.extract()?;
            pyself.slot.add_header(k, v);
        }
        Ok(pyself)
    }
    
    /// Append a value to an existing header (or create it)
    pub fn append<'py>(pyself: PyRef<'py, Self>, key: &str, value: &str) -> PyRef<'py, Self> {
        if let Some(existing) = pyself.slot.get_header(key) {
            pyself.slot.remove_header(key);
            pyself.slot.add_header(key.to_string(), format!("{}, {}", existing, value));
        } else {
            pyself.slot.add_header(key.to_string(), value.to_string());
        }
        pyself
    }
    
    /// Set the Vary header to instruct caches
    pub fn vary<'py>(pyself: PyRef<'py, Self>, field: &str) -> PyRef<'py, Self> {
        if let Some(existing) = pyself.slot.get_header("Vary") {
            if !existing.to_lowercase().contains(&field.to_lowercase()) {
                pyself.slot.remove_header("Vary");
                pyself.slot.add_header("Vary".to_string(), format!("{}, {}", existing, field));
            }
        } else {
            pyself.slot.add_header("Vary".to_string(), field.to_string());
        }
        pyself
    }
    
    /// Set Link header for pagination or related resources
    pub fn links<'py>(pyself: PyRef<'py, Self>, links_data: &Bound<'_, PyDict>) -> PyResult<PyRef<'py, Self>> {
        let mut parts = Vec::new();
        for (rel, url) in links_data.iter() {
            let rel_str: String = rel.extract()?;
            let url_str: String = url.extract()?;
            parts.push(format!("<{}>; rel=\"{}\"", url_str, rel_str));
        }
        pyself.slot.add_header("Link".to_string(), parts.join(", "));
        Ok(pyself)
    }
    
    /// Set the Location header
    pub fn location<'py>(pyself: PyRef<'py, Self>, url: &str) -> PyRef<'py, Self> {
        pyself.slot.add_header("Location".to_string(), url.to_string());
        pyself
    }
    
    /// Set ETag header for caching
    pub fn etag<'py>(pyself: PyRef<'py, Self>, etag: &str) -> PyRef<'py, Self> {
        // Ensure ETag is quoted
        let etag_val = if etag.starts_with('"') {
            etag.to_string()
        } else {
            format!("\"{}\"", etag)
        };
        pyself.slot.add_header("ETag".to_string(), etag_val);
        pyself
    }
    
    /// Set Last-Modified header
    pub fn last_modified<'py>(pyself: PyRef<'py, Self>, date: &str) -> PyRef<'py, Self> {
        pyself.slot.add_header("Last-Modified".to_string(), date.to_string());
        pyself
    }
    
    /// Set Expires header
    pub fn expires<'py>(pyself: PyRef<'py, Self>, date: &str) -> PyRef<'py, Self> {
        pyself.slot.add_header("Expires".to_string(), date.to_string());
        pyself
    }

    /// Set Content-Type header (chainable)
    pub fn content_type<'py>(pyself: PyRef<'py, Self>, content_type: &str) -> PyRef<'py, Self> {
        pyself.slot.add_header("Content-Type".to_string(), content_type.to_string());
        pyself
    }

    /// Alias for content_type() - Express.js compatibility
    #[pyo3(name = "type")]
    pub fn type_<'py>(pyself: PyRef<'py, Self>, content_type: &str) -> PyRef<'py, Self> {
        pyself.slot.add_header("Content-Type".to_string(), content_type.to_string());
        pyself
    }

    // ========== Body Methods ==========

    /// Set response body as bytes (chainable)
    pub fn body<'py>(pyself: PyRef<'py, Self>, body: Vec<u8>) -> PyRef<'py, Self> {
        pyself.slot.set_body(body);
        pyself
    }

    /// Set response body as string (chainable)
    pub fn body_str<'py>(pyself: PyRef<'py, Self>, body: &str) -> PyRef<'py, Self> {
        pyself.slot.set_body_str(body.to_string());
        pyself
    }

    /// Write data to response body (alias for body)
    pub fn write<'py>(pyself: PyRef<'py, Self>, body: Vec<u8>) -> PyRef<'py, Self> {
        pyself.slot.set_body(body);
        pyself
    }

    /// Append data to response body
    pub fn append_body<'py>(pyself: PyRef<'py, Self>, data: &[u8]) -> PyRef<'py, Self> {
        pyself.slot.append_body(data);
        pyself
    }

    // ========== Express.js-style Response Methods ==========

    /// Send a response (auto-detects content type)
    pub fn send<'py>(pyself: PyRef<'py, Self>, body: &Bound<'_, PyAny>) -> PyResult<PyRef<'py, Self>> {
        if let Ok(s) = body.extract::<String>() {
            // String - send as text/html
            if pyself.slot.get_header("Content-Type").is_none() {
                pyself.slot.add_header("Content-Type".to_string(), content_types::HTML.to_string());
            }
            pyself.slot.set_body_str(s);
        } else if let Ok(bytes) = body.extract::<Vec<u8>>() {
            // Bytes - send as-is
            if pyself.slot.get_header("Content-Type").is_none() {
                pyself.slot.add_header("Content-Type".to_string(), content_types::OCTET_STREAM.to_string());
            }
            pyself.slot.set_body(bytes);
        } else if body.is_none() {
            // None - empty body
            pyself.slot.set_body(Vec::new());
        } else {
            // Try to serialize as JSON
            let json_bytes = crate::utils::serialize_py_to_json(body)?;
            pyself.slot.add_header("Content-Type".to_string(), content_types::JSON.to_string());
            pyself.slot.set_body(json_bytes);
        }
        pyself.slot.mark_ready();
        Ok(pyself)
    }

    /// Send JSON response
    pub fn json<'py>(pyself: PyRef<'py, Self>, data: &Bound<'_, PyAny>) -> PyResult<PyRef<'py, Self>> {
        let json_bytes = crate::utils::serialize_py_to_json(data)?;
        pyself.slot.add_header("Content-Type".to_string(), content_types::JSON.to_string());
        pyself.slot.set_body(json_bytes);
        pyself.slot.mark_ready();
        Ok(pyself)
    }

    /// Send HTML response
    pub fn html<'py>(pyself: PyRef<'py, Self>, html: &str) -> PyRef<'py, Self> {
        pyself.slot.add_header("Content-Type".to_string(), content_types::HTML.to_string());
        pyself.slot.set_body_str(html.to_string());
        pyself.slot.mark_ready();
        pyself
    }

    /// Send plain text response
    pub fn text<'py>(pyself: PyRef<'py, Self>, text: &str) -> PyRef<'py, Self> {
        pyself.slot.add_header("Content-Type".to_string(), content_types::TEXT.to_string());
        pyself.slot.set_body_str(text.to_string());
        pyself.slot.mark_ready();
        pyself
    }

    /// Send XML response
    pub fn xml<'py>(pyself: PyRef<'py, Self>, xml: &str) -> PyRef<'py, Self> {
        pyself.slot.add_header("Content-Type".to_string(), content_types::XML.to_string());
        pyself.slot.set_body_str(xml.to_string());
        pyself.slot.mark_ready();
        pyself
    }
    
    /// Send SSE response with all events
    /// This batches all SSE events and sends them as a complete response.
    /// For true streaming SSE, use the async SSE handler pattern.
    pub fn sse<'py>(pyself: PyRef<'py, Self>, events: &Bound<'_, pyo3::types::PyList>) -> PyResult<PyRef<'py, Self>> {
        let mut body = String::new();
        for item in events.iter() {
            let event: PyRef<crate::http::streaming::SSEEvent> = item.extract()?;
            body.push_str(&event.format());
        }
        
        pyself.slot.add_header("Content-Type".to_string(), "text/event-stream".to_string());
        pyself.slot.add_header("Cache-Control".to_string(), "no-cache".to_string());
        pyself.slot.add_header("Connection".to_string(), "keep-alive".to_string());
        pyself.slot.add_header("X-Accel-Buffering".to_string(), "no".to_string());
        pyself.slot.set_body_str(body);
        pyself.slot.mark_ready();
        Ok(pyself)
    }

    /// Send SSE response from a Python generator/iterator.
    /// 
    /// This method consumes events from a Python generator one at a time,
    /// providing memory-efficient streaming without buffering all events.
    /// 
    /// Usage:
    /// ```python
    /// def event_generator():
    ///     for i in range(1000):
    ///         yield SSEEvent(f"Event {i}", event="counter")
    /// 
    /// res.sse_stream(event_generator())
    /// ```
    /// 
    /// The generator can yield:
    /// - SSEEvent objects
    /// - Dictionaries with 'data', 'event', 'id', 'retry' keys
    /// - Strings (will be wrapped as simple data events)
    /// - Any object with a 'data' attribute
    pub fn sse_stream<'py>(pyself: PyRef<'py, Self>, generator: &Bound<'_, pyo3::PyAny>) -> PyResult<PyRef<'py, Self>> {
        // Collect events from the generator using our efficient streaming function
        let events = crate::http::streaming::collect_sse_from_generator(pyself.py(), generator)?;
        
        // Build the response body from all events
        let total_size: usize = events.iter().map(|b| b.len()).sum();
        let mut body = Vec::with_capacity(total_size);
        for event_bytes in events {
            body.extend_from_slice(&event_bytes);
        }
        
        pyself.slot.add_header("Content-Type".to_string(), "text/event-stream".to_string());
        pyself.slot.add_header("Cache-Control".to_string(), "no-cache".to_string());
        pyself.slot.add_header("Connection".to_string(), "keep-alive".to_string());
        pyself.slot.add_header("X-Accel-Buffering".to_string(), "no".to_string());
        pyself.slot.set_body(body);
        pyself.slot.mark_ready();
        Ok(pyself)
    }
    
    /// Send a single SSE event as a response
    pub fn sse_event<'py>(pyself: PyRef<'py, Self>, data: &str, event: Option<&str>, id: Option<&str>) -> PyRef<'py, Self> {
        let sse_event = crate::http::streaming::SSEEvent {
            id: id.map(|s| s.to_string()),
            event: event.map(|s| s.to_string()),
            data: data.to_string(),
            retry: None,
        };
        
        pyself.slot.add_header("Content-Type".to_string(), "text/event-stream".to_string());
        pyself.slot.add_header("Cache-Control".to_string(), "no-cache".to_string());
        pyself.slot.add_header("Connection".to_string(), "keep-alive".to_string());
        pyself.slot.add_header("X-Accel-Buffering".to_string(), "no".to_string());
        pyself.slot.set_body_str(sse_event.format());
        pyself.slot.mark_ready();
        pyself
    }
    
    /// Set SSE headers without body (for use with long-polling or manual event building)
    pub fn sse_headers<'py>(pyself: PyRef<'py, Self>) -> PyRef<'py, Self> {
        pyself.slot.add_header("Content-Type".to_string(), "text/event-stream".to_string());
        pyself.slot.add_header("Cache-Control".to_string(), "no-cache".to_string());
        pyself.slot.add_header("Connection".to_string(), "keep-alive".to_string());
        pyself.slot.add_header("X-Accel-Buffering".to_string(), "no".to_string());
        pyself
    }

    /// Send empty response with status
    pub fn send_status<'py>(pyself: PyRef<'py, Self>, status: u16) -> PyRef<'py, Self> {
        pyself.slot.set_status(status);
        let message = status_message(status);
        pyself.slot.set_body_str(message.to_string());
        pyself.slot.mark_ready();
        pyself
    }

    /// End the response (finalize)
    #[pyo3(signature = (data=None))]
    pub fn end<'py>(pyself: PyRef<'py, Self>, data: Option<&Bound<'_, PyAny>>) -> PyResult<PyRef<'py, Self>> {
        if let Some(d) = data {
            if let Ok(s) = d.extract::<String>() {
                pyself.slot.set_body_str(s);
            } else if let Ok(bytes) = d.extract::<Vec<u8>>() {
                pyself.slot.set_body(bytes);
            }
        }
        pyself.slot.mark_ready();
        Ok(pyself)
    }

    /// Mark response as finished
    pub fn finish(&self) {
        self.slot.mark_ready();
    }

    // ========== Redirect Methods ==========

    /// Redirect to URL (default 302)
    #[pyo3(signature = (url, status=302))]
    pub fn redirect<'py>(pyself: PyRef<'py, Self>, url: &str, status: u16) -> PyRef<'py, Self> {
        pyself.slot.set_status(status);
        pyself.slot.add_header("Location".to_string(), url.to_string());
        pyself.slot.mark_ready();
        pyself
    }

    // ========== Cookie Methods ==========

    /// Set a cookie
    #[pyo3(signature = (name, value, max_age=None, path=None, domain=None, secure=false, http_only=false, same_site=None))]
    pub fn cookie<'py>(
        pyself: PyRef<'py, Self>,
        name: &str,
        value: &str,
        max_age: Option<i64>,
        path: Option<&str>,
        domain: Option<&str>,
        secure: bool,
        http_only: bool,
        same_site: Option<&str>,
    ) -> PyRef<'py, Self> {
        let mut cookie = format!("{}={}", name, value);
        
        if let Some(age) = max_age {
            cookie.push_str(&format!("; Max-Age={}", age));
        }
        if let Some(p) = path {
            cookie.push_str(&format!("; Path={}", p));
        }
        if let Some(d) = domain {
            cookie.push_str(&format!("; Domain={}", d));
        }
        if secure {
            cookie.push_str("; Secure");
        }
        if http_only {
            cookie.push_str("; HttpOnly");
        }
        if let Some(ss) = same_site {
            cookie.push_str(&format!("; SameSite={}", ss));
        }
        
        pyself.slot.add_header("Set-Cookie".to_string(), cookie);
        pyself
    }

    /// Clear a cookie
    #[pyo3(signature = (name, path=None, domain=None))]
    pub fn clear_cookie<'py>(
        pyself: PyRef<'py, Self>,
        name: &str,
        path: Option<&str>,
        domain: Option<&str>,
    ) -> PyRef<'py, Self> {
        let mut cookie = format!("{}=; Max-Age=0", name);
        if let Some(p) = path {
            cookie.push_str(&format!("; Path={}", p));
        }
        if let Some(d) = domain {
            cookie.push_str(&format!("; Domain={}", d));
        }
        pyself.slot.add_header("Set-Cookie".to_string(), cookie);
        pyself
    }

    // ========== Cache Control Methods ==========

    /// Set cache control headers
    #[pyo3(signature = (max_age=0, private=false, no_cache=false, no_store=false))]
    pub fn cache_control<'py>(
        pyself: PyRef<'py, Self>,
        max_age: u32,
        private: bool,
        no_cache: bool,
        no_store: bool,
    ) -> PyRef<'py, Self> {
        let mut directives = Vec::new();
        
        if no_store {
            directives.push("no-store".to_string());
        } else if no_cache {
            directives.push("no-cache".to_string());
        } else {
            if private {
                directives.push("private".to_string());
            } else {
                directives.push("public".to_string());
            }
            directives.push(format!("max-age={}", max_age));
        }
        
        pyself.slot.add_header("Cache-Control".to_string(), directives.join(", "));
        pyself
    }

    /// Set no-cache headers
    pub fn no_cache<'py>(pyself: PyRef<'py, Self>) -> PyRef<'py, Self> {
        pyself.slot.add_header("Cache-Control".to_string(), "no-cache, no-store, must-revalidate".to_string());
        pyself.slot.add_header("Pragma".to_string(), "no-cache".to_string());
        pyself.slot.add_header("Expires".to_string(), "0".to_string());
        pyself
    }

    // ========== CORS Headers ==========

    /// Set CORS headers for allowing cross-origin requests
    #[pyo3(signature = (origin="*", methods=None, headers=None, credentials=false, max_age=None))]
    pub fn cors<'py>(
        pyself: PyRef<'py, Self>,
        origin: &str,
        methods: Option<Vec<String>>,
        headers: Option<Vec<String>>,
        credentials: bool,
        max_age: Option<u32>,
    ) -> PyRef<'py, Self> {
        pyself.slot.add_header("Access-Control-Allow-Origin".to_string(), origin.to_string());
        
        if let Some(m) = methods {
            pyself.slot.add_header("Access-Control-Allow-Methods".to_string(), m.join(", "));
        }
        if let Some(h) = headers {
            pyself.slot.add_header("Access-Control-Allow-Headers".to_string(), h.join(", "));
        }
        if credentials {
            pyself.slot.add_header("Access-Control-Allow-Credentials".to_string(), "true".to_string());
        }
        if let Some(age) = max_age {
            pyself.slot.add_header("Access-Control-Max-Age".to_string(), age.to_string());
        }
        pyself
    }

    // ========== Download/Attachment ==========

    /// Set Content-Disposition for file download
    #[pyo3(signature = (filename=None))]
    pub fn attachment<'py>(pyself: PyRef<'py, Self>, filename: Option<&str>) -> PyRef<'py, Self> {
        let value = match filename {
            Some(f) => format!("attachment; filename=\"{}\"", f),
            None => "attachment".to_string(),
        };
        pyself.slot.add_header("Content-Disposition".to_string(), value);
        pyself
    }

    /// Send a file as response (for file downloads)
    #[pyo3(signature = (path, filename=None, content_type=None))]
    pub fn send_file<'py>(
        pyself: PyRef<'py, Self>,
        path: &str,
        filename: Option<&str>,
        content_type: Option<&str>,
    ) -> PyResult<PyRef<'py, Self>> {
        use std::fs;
        use std::path::Path;
        
        let file_path = Path::new(path);
        
        // Check file exists
        if !file_path.exists() {
            return Err(pyo3::exceptions::PyFileNotFoundError::new_err(
                format!("File not found: {}", path)
            ));
        }
        
        // Read file contents
        let contents = fs::read(file_path)?;
        
        // Determine content type
        let mime_type = content_type.unwrap_or_else(|| {
            // Guess content type from extension
            match file_path.extension().and_then(|e| e.to_str()) {
                Some("html") | Some("htm") => "text/html",
                Some("css") => "text/css",
                Some("js") => "application/javascript",
                Some("json") => "application/json",
                Some("xml") => "application/xml",
                Some("txt") => "text/plain",
                Some("png") => "image/png",
                Some("jpg") | Some("jpeg") => "image/jpeg",
                Some("gif") => "image/gif",
                Some("svg") => "image/svg+xml",
                Some("pdf") => "application/pdf",
                Some("zip") => "application/zip",
                Some("mp3") => "audio/mpeg",
                Some("mp4") => "video/mp4",
                Some("webp") => "image/webp",
                Some("woff") => "font/woff",
                Some("woff2") => "font/woff2",
                _ => "application/octet-stream",
            }
        });
        
        pyself.slot.add_header("Content-Type".to_string(), mime_type.to_string());
        
        // Set filename for download
        let download_name = filename.map(String::from).unwrap_or_else(|| {
            file_path
                .file_name()
                .and_then(|n| n.to_str())
                .unwrap_or("download")
                .to_string()
        });
        
        pyself.slot.add_header(
            "Content-Disposition".to_string(),
            format!("attachment; filename=\"{}\"", download_name),
        );
        
        pyself.slot.set_body(contents);
        pyself.slot.mark_ready();
        
        Ok(pyself)
    }
    
    /// Download a file (alias for send_file)
    #[pyo3(signature = (path, filename=None))]
    pub fn download<'py>(
        pyself: PyRef<'py, Self>,
        path: &str,
        filename: Option<&str>,
    ) -> PyResult<PyRef<'py, Self>> {
        Self::send_file(pyself, path, filename, None)
    }

    // ========== Check Methods ==========

    /// Check if headers have been sent
    #[getter]
    pub fn headers_sent(&self) -> bool {
        self.slot.is_sent()
    }

    /// Check if response is complete
    #[getter]
    pub fn finished(&self) -> bool {
        self.slot.is_ready()
    }
}

impl Response {
    pub fn new(slot: Arc<ResponseSlot>) -> Self {
        Self { slot }
    }

    pub fn slot(&self) -> Arc<ResponseSlot> {
        self.slot.clone()
    }
}


/// Get status message for HTTP status code
fn status_message(status: u16) -> &'static str {
    match status {
        100 => "Continue",
        101 => "Switching Protocols",
        200 => "OK",
        201 => "Created",
        202 => "Accepted",
        204 => "No Content",
        301 => "Moved Permanently",
        302 => "Found",
        303 => "See Other",
        304 => "Not Modified",
        307 => "Temporary Redirect",
        308 => "Permanent Redirect",
        400 => "Bad Request",
        401 => "Unauthorized",
        403 => "Forbidden",
        404 => "Not Found",
        405 => "Method Not Allowed",
        406 => "Not Acceptable",
        408 => "Request Timeout",
        409 => "Conflict",
        410 => "Gone",
        413 => "Payload Too Large",
        415 => "Unsupported Media Type",
        422 => "Unprocessable Entity",
        429 => "Too Many Requests",
        500 => "Internal Server Error",
        501 => "Not Implemented",
        502 => "Bad Gateway",
        503 => "Service Unavailable",
        504 => "Gateway Timeout",
        _ => "Unknown Status",
    }
}

/// Empty awaitable for immediate response
#[pyclass(frozen, freelist = 128)]
pub(crate) struct PyEmptyAwaitable;

#[pymethods]
impl PyEmptyAwaitable {
    fn __await__(pyself: PyRef<'_, Self>) -> PyRef<'_, Self> {
        pyself
    }

    fn __iter__(pyself: PyRef<'_, Self>) -> PyRef<'_, Self> {
        pyself
    }

    fn __next__(&self) -> Option<()> {
        None
    }
}

pub fn response_404() -> axum::response::Response<Body> {
    axum::response::Response::builder()
        .status(404)
        .header("content-type", "text/plain")
        .body(Body::from("Not Found"))
        .unwrap()
}

pub fn response_500() -> axum::response::Response {
    axum::response::Response::builder()
        .status(500)
        .header("content-type", "text/plain")
        .body(Body::from("Internal Server Error"))
        .unwrap()
}

pub fn response_405() -> axum::response::Response {
    axum::response::Response::builder()
        .status(405)
        .header("content-type", "text/plain")
        .body(Body::from("Method Not Allowed"))
        .unwrap()
}
