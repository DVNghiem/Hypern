//! Pre-allocated response handling for high-performance HTTP responses.
//!
//! This module provides `ResponseSlot` which uses pre-allocated buffers
//! and atomic operations for lock-free response completion signaling.

use bytes::Bytes;
use http_body_util::BodyExt;
use hyper::header::{HeaderMap, HeaderName, HeaderValue, SERVER};
use pyo3::prelude::*;
use pyo3::pybacked::PyBackedStr;
use smallvec::SmallVec;
use std::sync::atomic::{AtomicBool, AtomicU16, Ordering};
use std::sync::Arc;
use tokio::sync::oneshot;

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

        let mut header_map = HeaderMap::with_capacity(headers.len() + 1);
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

        let body_bytes = Bytes::from(body.clone());
        let http_body = http_body_util::Full::new(body_bytes)
            .map_err(std::convert::Into::into)
            .boxed();

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

    pub fn finish(&self) {
        self.slot.mark_ready();
    }
}

impl ResponseWriter {
    pub fn new(slot: Arc<ResponseSlot>) -> Self {
        Self { slot }
    }
}

/// Python-exposed response type (backwards compatible)
pub(crate) enum PyResponse {
    Body(PyResponseBody),
}

pub(crate) struct PyResponseBody {
    status: hyper::StatusCode,
    headers: HeaderMap,
    body: HTTPResponseBody,
}

macro_rules! headers_from_py {
    ($headers:expr) => {{
        let mut headers = HeaderMap::with_capacity($headers.len() + 3);
        for (key, value) in $headers {
            headers.append(
                HeaderName::from_bytes(key.as_bytes()).unwrap(),
                HeaderValue::from_str(&value).unwrap(),
            );
        }
        headers
            .entry(SERVER)
            .or_insert(HeaderValue::from_static("hypern"));
        headers
    }};
}

impl PyResponseBody {
    pub fn empty(status: u16, headers: Vec<(PyBackedStr, PyBackedStr)>) -> Self {
        Self {
            status: status.try_into().unwrap(),
            headers: headers_from_py!(headers),
            body: http_body_util::Empty::<Bytes>::new()
                .map_err(|e| match e {})
                .boxed(),
        }
    }

    pub fn from_bytes(
        status: u16,
        headers: Vec<(PyBackedStr, PyBackedStr)>,
        body: Box<[u8]>,
    ) -> Self {
        Self {
            status: status.try_into().unwrap(),
            headers: headers_from_py!(headers),
            body: http_body_util::Full::new(Bytes::from(body))
                .map_err(std::convert::Into::into)
                .boxed(),
        }
    }

    pub fn from_string(
        status: u16,
        headers: Vec<(PyBackedStr, PyBackedStr)>,
        body: String,
    ) -> Self {
        Self {
            status: status.try_into().unwrap(),
            headers: headers_from_py!(headers),
            body: http_body_util::Full::new(Bytes::from(body))
                .map_err(std::convert::Into::into)
                .boxed(),
        }
    }

    #[inline]
    pub fn to_response(self) -> hyper::Response<HTTPResponseBody> {
        let mut res = hyper::Response::new(self.body);
        *res.status_mut() = self.status;
        *res.headers_mut() = self.headers;
        res
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

/// Python-exposed Response class (backwards compatible)
#[pyclass(frozen)]
pub struct Response {
    tx: std::sync::Mutex<Option<oneshot::Sender<PyResponse>>>,
    disconnect_guard: Arc<tokio::sync::Notify>,
    disconnected: Arc<AtomicBool>,
}

impl Response {
    pub fn new(tx: oneshot::Sender<PyResponse>) -> Self {
        Self {
            tx: std::sync::Mutex::new(Some(tx)),
            disconnect_guard: Arc::new(tokio::sync::Notify::new()),
            disconnected: Arc::new(AtomicBool::new(false)),
        }
    }
}

#[pymethods]
impl Response {
    fn client_disconnect<'p>(&self, py: Python<'p>) -> PyResult<Bound<'p, PyAny>> {
        use pyo3::IntoPyObjectExt;
        if self.disconnected.load(Ordering::Acquire) {
            return PyEmptyAwaitable.into_bound_py_any(py);
        }

        let guard = self.disconnect_guard.clone();
        let state = self.disconnected.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            guard.notified().await;
            state.store(true, Ordering::Release);
            Ok(())
        })
    }

    #[pyo3(signature = (status=200, headers=vec![]))]
    pub fn send_empty(&self, status: u16, headers: Vec<(PyBackedStr, PyBackedStr)>) {
        if let Some(tx) = self.tx.lock().unwrap().take() {
            let _ = tx.send(PyResponse::Body(PyResponseBody::empty(status, headers)));
        }
    }

    #[pyo3(signature = (status=200, headers=vec![], body=vec![].into()))]
    pub fn send_bytes(
        &self,
        status: u16,
        headers: Vec<(PyBackedStr, PyBackedStr)>,
        body: std::borrow::Cow<[u8]>,
    ) {
        if let Some(tx) = self.tx.lock().unwrap().take() {
            let _ = tx.send(PyResponse::Body(PyResponseBody::from_bytes(
                status,
                headers,
                body.into(),
            )));
        }
    }

    #[pyo3(signature = (status=200, headers=vec![], body=String::new()))]
    pub fn send_str(&self, status: u16, headers: Vec<(PyBackedStr, PyBackedStr)>, body: String) {
        if let Some(tx) = self.tx.lock().unwrap().take() {
            let _ = tx.send(PyResponse::Body(PyResponseBody::from_string(
                status, headers, body,
            )));
        }
    }
}
