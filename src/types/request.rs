use futures::StreamExt;
use http_body_util::BodyExt;
use percent_encoding::percent_decode_str;
use pyo3::prelude::*;
use std::collections::HashMap;

use super::header::HypernHeaders;
use hyper::http::request;

#[derive(Default, Debug, Clone)]
#[pyclass]
pub struct Request {
    pub path: String,
    pub query_string: String,
    pub headers: HypernHeaders,
    pub method: String,
    pub path_params: HashMap<String, String>,
    pub body: Vec<u8>,
}

impl Request {
    pub async fn from_request(req: request::Parts) -> Self {

        let (path, query_string) = req.uri.path_and_query().map_or_else(
            || (vec![], ""),
            |pq| {
                (
                    percent_decode_str(pq.path()).collect(),
                    pq.query().unwrap_or(""),
                )
            },
        );

        let headers = HypernHeaders::new(req.headers);

        let method = req.method.to_string();

        Self {
            path: String::from_utf8_lossy(&path).to_string(),
            query_string: query_string.to_string(),
            headers,
            method,
            path_params: HashMap::new(),
            body: Vec::new(),
        }
    }
}
