use http_body_util::BodyExt;
use hyper::Request as HyperRequest;
use percent_encoding::percent_decode_str;
use pyo3::prelude::*;
use pyo3_async_runtimes::tokio::future_into_py;
use std::{collections::HashMap, sync::Mutex};

use crate::errors::{error_request, error_stream};

use super::header::HypernHeaders;
use hyper::body;
#[pyclass(frozen)]
pub struct Request {
    path: String,
    query_string: String,
    headers: HypernHeaders,
    method: String,
    path_params: HashMap<String, String>,
    query_params: HashMap<String, String>,
    body: Mutex<Option<body::Incoming>>,
    cached_body: Mutex<Option<Vec<u8>>>,
}

impl Request {
    pub async fn new(req: HyperRequest<body::Incoming>) -> Self {
        let (req_part, body_part) = req.into_parts();
        let (path, query_string) = req_part.uri.path_and_query().map_or_else(
            || (vec![], ""),
            |pq| {
                (
                    percent_decode_str(pq.path()).collect(),
                    pq.query().unwrap_or(""),
                )
            },
        );

        let headers = HypernHeaders::new(req_part.headers);
        let method = req_part.method.to_string();

        // Parse query parameters
        let query_params = if query_string.is_empty() {
            HashMap::new()
        } else {
            form_urlencoded::parse(query_string.as_bytes())
                .into_owned()
                .collect()
        };

        Self {
            path: String::from_utf8_lossy(&path).to_string(),
            query_string: query_string.to_string(),
            headers,
            method,
            path_params: HashMap::new(),
            query_params,
            body: Mutex::new(Some(body_part)),
            cached_body: Mutex::new(None),
        }
    }
}

impl Request {
    /// Helper method to get body bytes, caching the result
    async fn get_body_bytes(&self) -> PyResult<Vec<u8>> {
        // Check if body is already cached
        {
            let cached = self.cached_body.lock().unwrap();
            if let Some(bytes) = cached.as_ref() {
                return Ok(bytes.clone());
            }
        }

        // Get body from the mutex
        let body = {
            let mut body_guard = self.body.lock().unwrap();
            body_guard.take()
        };

        if let Some(body) = body {
            match body.collect().await {
                Ok(data) => {
                    let bytes = data.to_bytes().to_vec();
                    // Cache the result
                    {
                        let mut cached = self.cached_body.lock().unwrap();
                        *cached = Some(bytes.clone());
                    }
                    Ok(bytes)
                }
                Err(_) => Err(PyErr::new::<pyo3::exceptions::PyIOError, _>("Failed to read body"))
            }
        } else {
            Err(PyErr::new::<pyo3::exceptions::PyIOError, _>("Body already consumed"))
        }
    }
}

// JSON conversion will be implemented later with proper PyO3 API

#[pymethods]
impl Request {
    fn __call__<'p>(&self, py: Python<'p>) -> PyResult<Bound<'p, PyAny>> {
        let body = self.body.lock().unwrap().take();

        future_into_py(py, async move {
            if let Some(body) = body {
                return match body.collect().await {
                    Ok(data) => {
                        let bytes = data.to_bytes();
                        let bytes_vec = bytes.to_vec();
                        Ok(bytes_vec)
                    }
                    Err(_) => error_request!(),
                };
            }
            error_stream!()
        })
    }

    #[getter(path)]
    fn path(&self) -> &str {
        &self.path
    }

    #[getter(query_string)]
    fn query_string(&self) -> &str {
        &self.query_string
    }

    #[getter(headers)]
    fn headers(&self) -> HypernHeaders {
        self.headers.clone()
    }

    #[getter(method)]
    fn method(&self) -> &str {
        &self.method
    }

    #[getter(path_params)]
    fn path_params(&self) -> &HashMap<String, String> {
        &self.path_params
    }

    #[getter(query_params)]
    fn query_params(&self) -> &HashMap<String, String> {
        &self.query_params
    }

    /// Get a query parameter by name
    pub fn query(&self, name: &str) -> Option<&String> {
        self.query_params.get(name)
    }

    /// Get a path parameter by name  
    pub fn param(&self, name: &str) -> Option<&String> {
        self.path_params.get(name)
    }

    /// Get content type from headers
    pub fn content_type(&self) -> Option<String> {
        self.headers.get_header("content-type")
    }

    /// Check if request has a specific content type
    pub fn is_content_type(&self, content_type: &str) -> bool {
        if let Some(ct) = self.content_type() {
            ct.to_lowercase().contains(&content_type.to_lowercase())
        } else {
            false
        }
    }

    /// Check if request accepts JSON
    pub fn is_json(&self) -> bool {
        self.is_content_type("application/json")
    }

    /// Check if request is form data
    pub fn is_form(&self) -> bool {
        self.is_content_type("application/x-www-form-urlencoded")
    }

    /// Check if request is multipart
    pub fn is_multipart(&self) -> bool {
        self.is_content_type("multipart/")
    }
}
