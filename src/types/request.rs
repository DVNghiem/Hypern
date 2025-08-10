use futures::StreamExt;
use http_body_util::BodyExt;
use percent_encoding::percent_decode_str;
use pyo3::prelude::*;
use pyo3_async_runtimes::generic::future_into_py;
use std::{collections::HashMap, sync::Mutex};
use hyper::Request as HyperRequest;

use super::header::HypernHeaders;
use hyper::body;

#[derive(Default, Debug, Clone)]
#[pyclass]
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
        if let Some(body) = self.body.lock().unwrap().take() {
            return future_into_py(py, async move {
                match body.collect().await {
                    Ok(data) => data.to_bytes(),
                    _ => (),
                }
            });
        }
    }
}