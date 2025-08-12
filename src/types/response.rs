use std::{
    borrow::Cow,
    sync::{atomic, Arc, Mutex},
};

use bytes::Bytes;
use http_body_util::BodyExt;
use pyo3::{prelude::*, pybacked::PyBackedStr, IntoPyObjectExt};

use hyper::{
    header::{HeaderMap, HeaderName, HeaderValue, SERVER},
};
use pyo3_async_runtimes::tokio::future_into_py;
use tokio::sync::{oneshot, Notify};

pub(crate) type HTTPResponseBody = http_body_util::combinators::BoxBody<Bytes, anyhow::Error>;

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
#[pyclass(frozen)]
pub(crate) struct Response {
    tx: Mutex<Option<oneshot::Sender<PyResponse>>>,
    disconnect_guard: Arc<Notify>,
    disconnected: Arc<atomic::AtomicBool>,
}

impl Response {
    pub fn new(tx: oneshot::Sender<PyResponse>) -> Self {
        Self {
            tx: Mutex::new(Some(tx)),
            disconnect_guard: Arc::new(Notify::new()),
            disconnected: Arc::new(atomic::AtomicBool::new(false)),
        }
    }
}

#[pymethods]
impl Response {
    fn client_disconnect<'p>(&self, py: Python<'p>) -> PyResult<Bound<'p, PyAny>> {
        if self.disconnected.load(atomic::Ordering::Acquire) {
            return PyEmptyAwaitable.into_bound_py_any(py);
        }

        let guard = self.disconnect_guard.clone();
        let state = self.disconnected.clone();
        future_into_py(py, async move {
            guard.notified().await;
            state.store(true, atomic::Ordering::Release);
            Ok(())
        })
    }

    #[pyo3(signature = (status=200, headers=vec![]))]
    fn response_empty(&self, status: u16, headers: Vec<(PyBackedStr, PyBackedStr)>) {
        if let Some(tx) = self.tx.lock().unwrap().take() {
            _ = tx.send(PyResponse::Body(PyResponseBody::empty(status, headers)));
        }
    }

    #[pyo3(signature = (status=200, headers=vec![], body=vec![].into()))]
    fn response_bytes(
        &self,
        status: u16,
        headers: Vec<(PyBackedStr, PyBackedStr)>,
        body: Cow<[u8]>,
    ) {
        if let Some(tx) = self.tx.lock().unwrap().take() {
            _ = tx.send(PyResponse::Body(PyResponseBody::from_bytes(
                status,
                headers,
                body.into(),
            )));
        }
    }

    #[pyo3(signature = (status=200, headers=vec![], body=String::new()))]
    fn response_str(&self, status: u16, headers: Vec<(PyBackedStr, PyBackedStr)>, body: String) {
        if let Some(tx) = self.tx.lock().unwrap().take() {
            _ = tx.send(PyResponse::Body(PyResponseBody::from_string(
                status, headers, body,
            )));
        }
    }
}
