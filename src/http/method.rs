use axum::http::Method;
use pyo3::prelude::*;

/// HTTP Method enum for fast matching
#[pyclass]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum HttpMethod {
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

#[pymethods]
impl HttpMethod {
    #[staticmethod]
    pub fn from_str(s: &str) -> Option<Self> {
        match s.to_uppercase().as_str() {
            "GET" => Some(HttpMethod::GET),
            "POST" => Some(HttpMethod::POST),
            "PUT" => Some(HttpMethod::PUT),
            "DELETE" => Some(HttpMethod::DELETE),
            "PATCH" => Some(HttpMethod::PATCH),
            "HEAD" => Some(HttpMethod::HEAD),
            "OPTIONS" => Some(HttpMethod::OPTIONS),
            "CONNECT" => Some(HttpMethod::CONNECT),
            "TRACE" => Some(HttpMethod::TRACE),
            _ => None,
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            HttpMethod::GET => "GET",
            HttpMethod::POST => "POST",
            HttpMethod::PUT => "PUT",
            HttpMethod::DELETE => "DELETE",
            HttpMethod::PATCH => "PATCH",
            HttpMethod::HEAD => "HEAD",
            HttpMethod::OPTIONS => "OPTIONS",
            HttpMethod::CONNECT => "CONNECT",
            HttpMethod::TRACE => "TRACE",
        }
    }

    fn __str__(&self) -> &'static str {
        self.as_str()
    }

    fn __repr__(&self) -> String {
        format!("HttpMethod.{}", self.as_str())
    }
}

impl HttpMethod {
    #[inline]
    pub fn from_bytes(bytes: &[u8]) -> Option<Self> {
        match bytes {
            b"GET" => Some(HttpMethod::GET),
            b"POST" => Some(HttpMethod::POST),
            b"PUT" => Some(HttpMethod::PUT),
            b"DELETE" => Some(HttpMethod::DELETE),
            b"PATCH" => Some(HttpMethod::PATCH),
            b"HEAD" => Some(HttpMethod::HEAD),
            b"OPTIONS" => Some(HttpMethod::OPTIONS),
            b"CONNECT" => Some(HttpMethod::CONNECT),
            b"TRACE" => Some(HttpMethod::TRACE),
            _ => None,
        }
    }
}

impl From<&Method> for HttpMethod {
    fn from(method: &axum::http::Method) -> Self {
        match *method {
            axum::http::Method::GET => HttpMethod::GET,
            axum::http::Method::POST => HttpMethod::POST,
            axum::http::Method::PUT => HttpMethod::PUT,
            axum::http::Method::DELETE => HttpMethod::DELETE,
            axum::http::Method::PATCH => HttpMethod::PATCH,
            axum::http::Method::HEAD => HttpMethod::HEAD,
            axum::http::Method::OPTIONS => HttpMethod::OPTIONS,
            axum::http::Method::CONNECT => HttpMethod::CONNECT,
            axum::http::Method::TRACE => HttpMethod::TRACE,
            _ => HttpMethod::GET, // Fallback
        }
    }
}

impl HttpMethod {
    /// Create HttpMethod from Axum's http::Method
    pub fn from_axum(method: &axum::http::Method) -> Self {
        match *method {
            axum::http::Method::GET => HttpMethod::GET,
            axum::http::Method::POST => HttpMethod::POST,
            axum::http::Method::PUT => HttpMethod::PUT,
            axum::http::Method::DELETE => HttpMethod::DELETE,
            axum::http::Method::PATCH => HttpMethod::PATCH,
            axum::http::Method::HEAD => HttpMethod::HEAD,
            axum::http::Method::OPTIONS => HttpMethod::OPTIONS,
            axum::http::Method::CONNECT => HttpMethod::CONNECT,
            axum::http::Method::TRACE => HttpMethod::TRACE,
            _ => HttpMethod::GET, // Fallback
        }
    }
}
