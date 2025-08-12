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
    body: Mutex<Option<body::Incoming>>,
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

        Self {
            path: String::from_utf8_lossy(&path).to_string(),
            query_string: query_string.to_string(),
            headers,
            method,
            path_params: HashMap::new(),
            body: Mutex::new(Some(body_part)),
        }
    }
}

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
}
