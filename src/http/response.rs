use bytes::Bytes;
use hyper::header::{HeaderMap, HeaderName, HeaderValue, SERVER};
use pyo3::prelude::*;
use smallvec::SmallVec;
use std::sync::atomic::{AtomicBool, AtomicU16, Ordering};
use std::sync::Arc;

use crate::body::HTTPResponseBody;

/// Pre-allocated response slot for zero-allocation response handling.
///
/// Uses atomic operations for lock-free completion signaling.
pub struct ResponseSlot {
    /// HTTP status code
    status: AtomicU16,
    /// Response headers (small vector optimization for common case)
    headers: parking_lot::RwLock<SmallVec<[(String, String); 8]>>,
    /// Response body
    body: parking_lot::RwLock<Vec<u8>>,
    /// Completion flag
    ready: AtomicBool,
}

impl ResponseSlot {
    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            status: AtomicU16::new(200),
            headers: parking_lot::RwLock::new(SmallVec::new()),
            body: parking_lot::RwLock::new(Vec::with_capacity(4096)),
            ready: AtomicBool::new(false),
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

    pub fn set_headers(&self, headers: Vec<(String, String)>) {
        let mut h = self.headers.write();
        h.clear();
        h.extend(headers);
    }

    pub fn add_header(&self, key: String, value: String) {
        self.headers.write().push((key, value));
    }

    pub fn set_body(&self, body: Vec<u8>) {
        *self.body.write() = body;
    }

    pub fn set_body_str(&self, body: String) {
        *self.body.write() = body.into_bytes();
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

    /// Convert to hyper Response
    pub fn into_hyper_response(self: Arc<Self>) -> hyper::Response<HTTPResponseBody> {
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
            .or_insert(HeaderValue::from_static("hypern"));

        // Set Content-Length explicitly for better client compatibility
        header_map.insert(hyper::header::CONTENT_LENGTH, HeaderValue::from(body.len()));

        // Use standard helper for consistency
        let http_body = crate::body::full_http(body.clone());

        let mut res = hyper::Response::new(http_body);
        *res.status_mut() = hyper::StatusCode::from_u16(status).unwrap_or(hyper::StatusCode::OK);
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
        }
    }
}

/// Response writer for efficient response construction
#[pyclass]
pub struct ResponseWriter {
    slot: Arc<ResponseSlot>,
}

#[pymethods]
impl ResponseWriter {
    #[pyo3(signature = (status=200))]
    pub fn status<'py>(pyself: PyRef<'py, Self>, status: u16) -> PyRef<'py, Self> {
        pyself.slot.set_status(status);
        pyself
    }

    pub fn header<'py>(pyself: PyRef<'py, Self>, key: &str, value: &str) -> PyRef<'py, Self> {
        pyself.slot.add_header(key.to_string(), value.to_string());
        pyself
    }

    pub fn body<'py>(pyself: PyRef<'py, Self>, body: Vec<u8>) -> PyRef<'py, Self> {
        pyself.slot.set_body(body);
        pyself
    }

    pub fn body_str<'py>(pyself: PyRef<'py, Self>, body: &str) -> PyRef<'py, Self> {
        pyself.slot.set_body_str(body.to_string());
        pyself
    }

    pub fn write<'py>(pyself: PyRef<'py, Self>, body: Vec<u8>) -> PyRef<'py, Self> {
        pyself.slot.set_body(body);
        pyself
    }

    pub fn finish(&self) {
        self.slot.mark_ready();
    }
}

impl ResponseWriter {
    pub fn new(slot: Arc<ResponseSlot>) -> Self {
        Self { slot }
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
