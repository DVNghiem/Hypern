use crate::http::headers::HeaderMap;
use crate::http::method::HttpMethod;
use ahash::AHashMap;
use bytes::Bytes;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};
use std::collections::HashMap;
use std::sync::Arc;
use xxhash_rust::xxh3::xxh3_64;

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

/// Zero-copy request structure for high-performance request handling.
#[pyclass(frozen)]
pub struct Request {
    path: Arc<str>,
    method: HttpMethod,
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
        method: HttpMethod,
        headers: HeaderMap,
        query_string: &str,
        body: Option<Bytes>,
    ) -> Self {
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

    pub fn method(&self) -> HttpMethod {
        self.method
    }

    #[inline]
    pub fn take_body(&self) -> Option<Bytes> {
        self.body.write().take()
    }

    #[inline]
    pub fn body_ref(&self) -> Option<Bytes> {
        self.body.read().as_ref().cloned()
    }

    #[inline]
    pub fn headers_map(&self) -> HashMap<String, String> {
        self.headers
            .iter()
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect()
    }

    #[inline]
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

    pub fn accepts(&self, types: Vec<String>) -> Option<String> {
        let accept = self.headers.get("accept")?;

        for t in types {
            let check = match t.to_lowercase().as_str() {
                "html" => "text/html",
                "json" => "application/json",
                "xml" => "application/xml",
                "text" => "text/plain",
                _ => &t,
            };

            if accept.contains(check) || accept.contains("*/*") {
                return Some(t);
            }
        }
        None
    }

    pub fn accepts_json(&self) -> bool {
        self.accepts(vec!["json".to_string()]).is_some()
    }

    pub fn accepts_html(&self) -> bool {
        self.accepts(vec!["html".to_string()]).is_some()
    }

    #[getter]
    pub fn ip(&self) -> Option<String> {
        // Check X-Forwarded-For first (for proxies)
        if let Some(forwarded) = self.headers.get("x-forwarded-for") {
            return Some(forwarded.split(',').next()?.trim().to_string());
        }
        // Check X-Real-IP
        if let Some(real_ip) = self.headers.get("x-real-ip") {
            return Some(real_ip.clone());
        }
        None
    }

    pub fn ips(&self) -> Vec<String> {
        if let Some(forwarded) = self.headers.get("x-forwarded-for") {
            return forwarded.split(',').map(|s| s.trim().to_string()).collect();
        }
        Vec::new()
    }

    #[getter]
    pub fn xhr(&self) -> bool {
        self.headers
            .get("x-requested-with")
            .map(|v| v.to_lowercase() == "xmlhttprequest")
            .unwrap_or(false)
    }

    #[getter]
    pub fn secure(&self) -> bool {
        // Check X-Forwarded-Proto header (for reverse proxies)
        if let Some(proto) = self.headers.get("x-forwarded-proto") {
            return proto.to_lowercase() == "https";
        }
        false
    }

    #[getter]
    pub fn hostname(&self) -> Option<String> {
        self.headers.get("host").map(|h| {
            // Remove port if present
            h.split(':').next().unwrap_or(h).to_string()
        })
    }

    pub fn subdomains(&self) -> Vec<String> {
        if let Some(hostname) = self.hostname() {
            let parts: Vec<&str> = hostname.split('.').collect();
            if parts.len() > 2 {
                return parts[..parts.len() - 2]
                    .iter()
                    .map(|s| s.to_string())
                    .collect();
            }
        }
        Vec::new()
    }

    /// Get the full URL
    #[getter]
    pub fn url(&self) -> String {
        if self.query_string.is_empty() {
            self.path.to_string()
        } else {
            format!("{}?{}", self.path, self.query_string)
        }
    }

    #[getter]
    pub fn original_url(&self) -> String {
        self.url()
    }

    #[getter]
    pub fn protocol(&self) -> String {
        if self.secure() {
            "https".to_string()
        } else {
            "http".to_string()
        }
    }

    pub fn fresh(&self, etag: Option<&str>, last_modified: Option<&str>) -> bool {
        // Check If-None-Match (ETag)
        if let Some(if_none_match) = self.headers.get("if-none-match") {
            if let Some(etag) = etag {
                if if_none_match == etag || if_none_match == "*" {
                    return true;
                }
            }
        }

        if let Some(if_modified) = self.headers.get("if-modified-since") {
            if let Some(lm) = last_modified {
                if if_modified == lm {
                    return true;
                }
            }
        }

        false
    }

    pub fn stale(&self, etag: Option<&str>, last_modified: Option<&str>) -> bool {
        !self.fresh(etag, last_modified)
    }

    pub fn cookie(&self, name: &str) -> Option<String> {
        let cookies = self.headers.get("cookie")?;
        for cookie in cookies.split(';') {
            let parts: Vec<&str> = cookie.trim().splitn(2, '=').collect();
            if parts.len() == 2 && parts[0] == name {
                return Some(parts[1].to_string());
            }
        }
        None
    }

    /// Get all cookies as a map
    pub fn cookies(&self) -> HashMap<String, String> {
        let mut result = HashMap::new();
        if let Some(cookies) = self.headers.get("cookie") {
            for cookie in cookies.split(';') {
                let parts: Vec<&str> = cookie.trim().splitn(2, '=').collect();
                if parts.len() == 2 {
                    result.insert(parts[0].to_string(), parts[1].to_string());
                }
            }
        }
        result
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
                let result = crate::utils::parse_json_to_py(py, bytes)?;
                Ok(result.into_bound(py))
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

    pub fn form(&self) -> PyResult<crate::http::multipart::FormData> {
        let body = self.body.read();
        let body_bytes = body
            .as_ref()
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("No body data available"))?;

        let content_type = self.content_type().unwrap_or_default();

        if content_type.contains("multipart/form-data") {
            // Parse multipart form data
            if let Some(boundary) = crate::http::multipart::extract_boundary(&content_type) {
                Ok(crate::http::multipart::parse_multipart(
                    body_bytes, &boundary,
                ))
            } else {
                Err(pyo3::exceptions::PyValueError::new_err(
                    "Missing boundary in multipart content-type",
                ))
            }
        } else if content_type.contains("application/x-www-form-urlencoded") {
            // Parse URL-encoded form data
            let mut form_data = crate::http::multipart::FormData::new();
            let body_str = String::from_utf8_lossy(body_bytes);

            for pair in form_urlencoded::parse(body_str.as_bytes()) {
                form_data.add_field(pair.0.to_string(), pair.1.to_string());
            }

            Ok(form_data)
        } else {
            Err(pyo3::exceptions::PyValueError::new_err(
                "Request content-type is not form data",
            ))
        }
    }

    pub fn file(&self, name: &str) -> PyResult<Option<crate::http::multipart::UploadedFile>> {
        let form = self.form()?;
        Ok(form.file(name))
    }

    pub fn files(&self) -> PyResult<Vec<crate::http::multipart::UploadedFile>> {
        let form = self.form()?;
        Ok(form.all_files())
    }
}

impl Request {
    pub async fn from_axum(req: axum::http::Request<axum::body::Body>) -> Self {
        use axum::body::to_bytes;
        use percent_encoding::percent_decode_str;

        let (parts, body) = req.into_parts();

        let (path, query_string) = parts.uri.path_and_query().map_or_else(
            || ("/".to_string(), String::new()),
            |pq| {
                let raw_path = pq.path();
                // Fast path: if no percent-encoded chars, avoid allocation
                let path = if raw_path.contains('%') {
                    let path_bytes: Vec<u8> = percent_decode_str(raw_path).collect();
                    String::from_utf8_lossy(&path_bytes).into_owned()
                } else {
                    raw_path.to_string()
                };
                (path, pq.query().unwrap_or("").to_string())
            },
        );

        let method = HttpMethod::from_axum(&parts.method);
        let headers = HeaderMap::from_axum(&parts.headers);

        // Skip body reading for methods that typically don't have a body
        // This avoids an unnecessary await + allocation for GET/HEAD/DELETE/OPTIONS
        let body_bytes = match method {
            HttpMethod::GET | HttpMethod::HEAD | HttpMethod::OPTIONS | HttpMethod::DELETE => {
                // Check Content-Length to see if there actually is a body
                let has_body = parts
                    .headers
                    .get(axum::http::header::CONTENT_LENGTH)
                    .and_then(|v| v.to_str().ok())
                    .and_then(|v| v.parse::<usize>().ok())
                    .map(|len| len > 0)
                    .unwrap_or(false);
                if has_body {
                    to_bytes(body, 10 * 1024 * 1024).await.ok()
                } else {
                    None
                }
            }
            _ => {
                // POST, PUT, PATCH - read body
                to_bytes(body, 10 * 1024 * 1024).await.ok()
            }
        };

        Self::new(&path, method, headers, &query_string, body_bytes)
    }
}
