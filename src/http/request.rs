use ahash::AHashMap;
use bytes::Bytes;
use http_body_util::BodyExt;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};
use std::collections::HashMap;
use std::sync::{Arc};


/// HTTP method enum for fast comparison (no string allocation)
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Method {
    GET,
    POST,
    PUT,
    DELETE,
    PATCH,
    HEAD,
    OPTIONS,
    CONNECT,
    TRACE,
}

impl Method {
    #[inline]
    pub fn from_bytes(bytes: &[u8]) -> Option<Self> {
        match bytes {
            b"GET" => Some(Method::GET),
            b"POST" => Some(Method::POST),
            b"PUT" => Some(Method::PUT),
            b"DELETE" => Some(Method::DELETE),
            b"PATCH" => Some(Method::PATCH),
            b"HEAD" => Some(Method::HEAD),
            b"OPTIONS" => Some(Method::OPTIONS),
            b"CONNECT" => Some(Method::CONNECT),
            b"TRACE" => Some(Method::TRACE),
            _ => None,
        }
    }

    #[inline]
    pub fn as_str(&self) -> &'static str {
        match self {
            Method::GET => "GET",
            Method::POST => "POST",
            Method::PUT => "PUT",
            Method::DELETE => "DELETE",
            Method::PATCH => "PATCH",
            Method::HEAD => "HEAD",
            Method::OPTIONS => "OPTIONS",
            Method::CONNECT => "CONNECT",
            Method::TRACE => "TRACE",
        }
    }
}

impl From<&hyper::Method> for Method {
    fn from(method: &hyper::Method) -> Self {
        match *method {
            hyper::Method::GET => Method::GET,
            hyper::Method::POST => Method::POST,
            hyper::Method::PUT => Method::PUT,
            hyper::Method::DELETE => Method::DELETE,
            hyper::Method::PATCH => Method::PATCH,
            hyper::Method::HEAD => Method::HEAD,
            hyper::Method::OPTIONS => Method::OPTIONS,
            hyper::Method::CONNECT => Method::CONNECT,
            hyper::Method::TRACE => Method::TRACE,
            _ => Method::GET, // Fallback
        }
    }
}

/// Query parameters with lazy parsing
#[derive(Clone, Debug, Default)]
pub struct QueryParams {
    raw: Arc<str>,
    parsed: Option<AHashMap<String, String>>,
}

impl QueryParams {
    pub fn new(raw: &str) -> Self {
        Self {
            raw: Arc::from(raw),
            parsed: None,
        }
    }

    pub fn parse(&mut self) -> &AHashMap<String, String> {
        if self.parsed.is_none() {
            let map: AHashMap<String, String> = if self.raw.is_empty() {
                AHashMap::new()
            } else {
                form_urlencoded::parse(self.raw.as_bytes())
                    .into_owned()
                    .collect()
            };
            self.parsed = Some(map);
        }
        self.parsed.as_ref().unwrap()
    }

    pub fn get(&mut self, key: &str) -> Option<&String> {
        self.parse().get(key)
    }
}

/// Fast header map using AHashMap for O(1) lookups
#[derive(Clone, Debug, Default)]
pub struct HeaderMap {
    headers: AHashMap<String, String>,
}

impl HeaderMap {
    pub fn new() -> Self {
        Self {
            headers: AHashMap::with_capacity(16),
        }
    }

    pub fn from_hyper(headers: &hyper::HeaderMap) -> Self {
        let mut map = AHashMap::with_capacity(headers.len());
        for (key, value) in headers.iter() {
            if let Ok(v) = value.to_str() {
                map.insert(key.as_str().to_lowercase(), v.to_string());
            }
        }
        Self { headers: map }
    }

    #[inline]
    pub fn get(&self, key: &str) -> Option<&String> {
        self.headers.get(&key.to_lowercase())
    }

    #[inline]
    pub fn insert(&mut self, key: String, value: String) {
        self.headers.insert(key.to_lowercase(), value);
    }

    pub fn iter(&self) -> impl Iterator<Item = (&String, &String)> {
        self.headers.iter()
    }
}

/// Zero-copy request structure for high-performance request handling.
#[pyclass(frozen)]
pub struct Request {
    path: Arc<str>,
    method: Method,
    headers: Arc<HeaderMap>,
    #[pyo3(get)]
    query_string: String,
    query_params: parking_lot::RwLock<QueryParams>,
    path_params: parking_lot::RwLock<HashMap<String, String>>,
    body: parking_lot::RwLock<Option<Bytes>>,
    route_hash: u64,
}

impl Clone for Request {
    fn clone(&self) -> Self {
        Self {
            path: self.path.clone(),
            method: self.method,
            headers: self.headers.clone(),
            query_string: self.query_string.clone(),
            query_params: parking_lot::RwLock::new(self.query_params.read().clone()),
            path_params: parking_lot::RwLock::new(self.path_params.read().clone()),
            body: parking_lot::RwLock::new(self.body.read().clone()),
            route_hash: self.route_hash,
        }
    }
}

impl Request {
    pub fn new(
        path: &str,
        method: Method,
        headers: HeaderMap,
        query_string: &str,
        body: Option<Bytes>,
    ) -> Self {
        use xxhash_rust::xxh3::xxh3_64;

        let path_arc = Arc::from(path);
        let route_hash = xxh3_64(path.as_bytes()) ^ (method as u64);

        Self {
            path: path_arc,
            method,
            headers: Arc::new(headers),
            query_string: query_string.to_string(),
            query_params: parking_lot::RwLock::new(QueryParams::new(query_string)),
            path_params: parking_lot::RwLock::new(HashMap::new()),
            body: parking_lot::RwLock::new(body),
            route_hash,
        }
    }

    pub async fn from_hyper(req: hyper::Request<hyper::body::Incoming>) -> Self {
        use percent_encoding::percent_decode_str;

        let (parts, body) = req.into_parts();

        let (path, query_string) = parts.uri.path_and_query().map_or_else(
            || ("/".to_string(), String::new()),
            |pq| {
                let path_bytes: Vec<u8> = percent_decode_str(pq.path()).collect();
                (
                    String::from_utf8_lossy(&path_bytes).to_string(),
                    pq.query().unwrap_or("").to_string(),
                )
            },
        );

        let method = Method::from(&parts.method);
        let headers = HeaderMap::from_hyper(&parts.headers);

        let body_bytes = match body.collect().await {
            Ok(collected) => Some(collected.to_bytes()),
            Err(_) => None,
        };

        Self::new(&path, method, headers, &query_string, body_bytes)
    }

    #[inline]
    pub fn route_hash(&self) -> u64 {
        self.route_hash
    }

    pub fn set_path_params(&self, params: HashMap<String, String>) {
        *self.path_params.write() = params;
    }

    pub fn path(&self) -> &str {
        &self.path
    }

    pub fn method(&self) -> Method {
        self.method
    }

    pub fn take_body(&self) -> Option<Bytes> {
        self.body.write().take()
    }

    /// Get all headers as a HashMap (for middleware context)
    pub fn headers_map(&self) -> HashMap<String, String> {
        self.headers.iter().map(|(k, v)| (k.clone(), v.clone())).collect()
    }

    /// Get body reference (for middleware context)
    pub fn body_ref(&self) -> Option<Bytes> {
        self.body.read().clone()
    }

    /// Get query string
    pub fn query_string(&self) -> &str {
        &self.query_string
    }
}

#[pymethods]
impl Request {
    #[getter(path)]
    fn py_path(&self) -> &str {
        &self.path
    }

    #[getter(method)]
    fn py_method(&self) -> &str {
        self.method.as_str()
    }

    #[getter(query_string)]
    fn py_query_string(&self) -> &str {
        &self.query_string
    }

    #[getter(path_params)]
    fn py_path_params(&self) -> HashMap<String, String> {
        self.path_params.read().clone()
    }

    #[getter(query_params)]
    fn py_query_params(&self) -> HashMap<String, String> {
        let mut qp = self.query_params.write();
        qp.parse()
            .iter()
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect()
    }

    pub fn query(&self, name: &str) -> Option<String> {
        self.query_params.write().get(name).cloned()
    }

    pub fn param(&self, name: &str) -> Option<String> {
        self.path_params.read().get(name).cloned()
    }

    pub fn header(&self, name: &str) -> Option<String> {
        self.headers.get(name).cloned()
    }

    #[getter(headers)]
    fn py_headers(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let dict = PyDict::new(py);
        for (k, v) in self.headers.iter() {
            dict.set_item(k, v)?;
        }
        Ok(dict.into())
    }

    fn body_bytes<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyBytes>> {
        let body = self.body.read();
        match body.as_ref() {
            Some(bytes) => Ok(PyBytes::new(py, bytes)),
            None => Ok(PyBytes::new(py, &[])),
        }
    }

    fn json<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let body = self.body.read();
        match body.as_ref() {
            Some(bytes) => {
                let mut data = bytes.to_vec();
                let json_str = Python::detach(py, move || {
                    match simd_json::serde::from_slice::<serde_json::Value>(&mut data) {
                        Ok(value) => {
                            serde_json::to_string(&value).map_err(|e| e.to_string())
                        }
                        Err(e) => Err(format!("JSON parse error: {}", e)),
                    }
                });

                match json_str {
                     Ok(s) => {
                        let json_mod = py.import("json")?;
                        json_mod.call_method1("loads", (s,))
                     },
                     Err(e) => Err(pyo3::exceptions::PyValueError::new_err(e)),
                }
            }
            None => Ok(py.None().into_bound(py)),
        }
    }

    pub fn content_type(&self) -> Option<String> {
        self.headers.get("content-type").cloned()
    }

    pub fn is_content_type(&self, content_type: &str) -> bool {
        self.content_type()
            .map(|ct| ct.to_lowercase().contains(&content_type.to_lowercase()))
            .unwrap_or(false)
    }

    pub fn is_json(&self) -> bool {
        self.is_content_type("application/json")
    }

    pub fn is_form(&self) -> bool {
        self.is_content_type("application/x-www-form-urlencoded")
    }

    pub fn is_multipart(&self) -> bool {
        self.is_content_type("multipart/")
    }
}
