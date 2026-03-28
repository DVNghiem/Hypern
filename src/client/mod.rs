use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use pyo3::prelude::*;
use pyo3::types::PyDict;

/// Response from an HTTP request
#[pyclass(name = "ClientResponse")]
pub struct ClientResponse {
    #[pyo3(get)]
    pub status: u16,
    headers: HashMap<String, String>,
    body: Vec<u8>,
}

#[pymethods]
impl ClientResponse {
    /// Get response headers as a dict
    pub fn headers(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let dict = PyDict::new(py);
        for (k, v) in &self.headers {
            dict.set_item(k, v)?;
        }
        Ok(dict.unbind())
    }

    /// Get body as text
    pub fn text(&self) -> PyResult<String> {
        String::from_utf8(self.body.clone())
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
    }

    /// Get body as JSON (returns a Python dict/list)
    pub fn json(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let text = self.text()?;
        let json_mod = py.import("json")?;
        let result = json_mod.call_method1("loads", (text,))?;
        Ok(result.unbind())
    }

    /// Get body as bytes
    pub fn bytes(&self, py: Python<'_>) -> Py<pyo3::types::PyBytes> {
        pyo3::types::PyBytes::new(py, &self.body).unbind()
    }

    fn __repr__(&self) -> String {
        format!("<ClientResponse status={}>", self.status)
    }
}

/// Async HTTP client backed by reqwest with Rust-level connection pooling
#[pyclass(name = "HttpClient")]
pub struct HttpClient {
    client: Arc<reqwest::Client>,
    base_url: Option<String>,
    rt: tokio::runtime::Runtime,
}

#[pymethods]
impl HttpClient {
    /// Create a new HTTP client
    ///
    /// Args:
    ///     base_url: Optional base URL prepended to all requests
    ///     timeout: Request timeout in seconds (default: 30)
    ///     max_connections: Max idle connections per host (default: 20)
    #[new]
    #[pyo3(signature = (base_url = None, timeout = 30, max_connections = 20))]
    pub fn new(
        base_url: Option<String>,
        timeout: u64,
        max_connections: usize,
    ) -> PyResult<Self> {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(timeout))
            .pool_max_idle_per_host(max_connections)
            .build()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
        let rt = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
        Ok(Self {
            client: Arc::new(client),
            base_url,
            rt,
        })
    }

    /// Send a GET request
    #[pyo3(signature = (url, headers = None, params = None))]
    pub fn get(
        &self,
        url: String,
        headers: Option<HashMap<String, String>>,
        params: Option<HashMap<String, String>>,
    ) -> PyResult<ClientResponse> {
        let full_url = self.build_url(&url);
        let mut req = self.client.get(&full_url);
        if let Some(h) = headers {
            for (k, v) in h {
                req = req.header(k, v);
            }
        }
        if let Some(p) = params {
            req = req.query(&p);
        }
        self.rt.block_on(send_request(req))
    }

    /// Send a POST request
    #[pyo3(signature = (url, headers = None, json = None, body = None))]
    pub fn post(
        &self,
        url: String,
        headers: Option<HashMap<String, String>>,
        json: Option<String>,
        body: Option<Vec<u8>>,
    ) -> PyResult<ClientResponse> {
        let full_url = self.build_url(&url);
        let mut req = self.client.post(&full_url);
        if let Some(h) = headers {
            for (k, v) in h {
                req = req.header(k, v);
            }
        }
        if let Some(j) = json {
            req = req.header("content-type", "application/json").body(j);
        } else if let Some(b) = body {
            req = req.body(b);
        }
        self.rt.block_on(send_request(req))
    }

    /// Send a PUT request
    #[pyo3(signature = (url, headers = None, json = None, body = None))]
    pub fn put(
        &self,
        url: String,
        headers: Option<HashMap<String, String>>,
        json: Option<String>,
        body: Option<Vec<u8>>,
    ) -> PyResult<ClientResponse> {
        let full_url = self.build_url(&url);
        let mut req = self.client.put(&full_url);
        if let Some(h) = headers {
            for (k, v) in h {
                req = req.header(k, v);
            }
        }
        if let Some(j) = json {
            req = req.header("content-type", "application/json").body(j);
        } else if let Some(b) = body {
            req = req.body(b);
        }
        self.rt.block_on(send_request(req))
    }

    /// Send a PATCH request
    #[pyo3(signature = (url, headers = None, json = None, body = None))]
    pub fn patch(
        &self,
        url: String,
        headers: Option<HashMap<String, String>>,
        json: Option<String>,
        body: Option<Vec<u8>>,
    ) -> PyResult<ClientResponse> {
        let full_url = self.build_url(&url);
        let mut req = self.client.patch(&full_url);
        if let Some(h) = headers {
            for (k, v) in h {
                req = req.header(k, v);
            }
        }
        if let Some(j) = json {
            req = req.header("content-type", "application/json").body(j);
        } else if let Some(b) = body {
            req = req.body(b);
        }
        self.rt.block_on(send_request(req))
    }

    /// Send a DELETE request
    #[pyo3(signature = (url, headers = None))]
    pub fn delete(
        &self,
        url: String,
        headers: Option<HashMap<String, String>>,
    ) -> PyResult<ClientResponse> {
        let full_url = self.build_url(&url);
        let mut req = self.client.delete(&full_url);
        if let Some(h) = headers {
            for (k, v) in h {
                req = req.header(k, v);
            }
        }
        self.rt.block_on(send_request(req))
    }

    fn __repr__(&self) -> String {
        match &self.base_url {
            Some(url) => format!("HttpClient(base_url={:?})", url),
            None => "HttpClient()".to_string(),
        }
    }
}

impl HttpClient {
    fn build_url(&self, url: &str) -> String {
        match &self.base_url {
            Some(base) => {
                let base = base.trim_end_matches('/');
                if url.starts_with('/') {
                    format!("{}{}", base, url)
                } else {
                    format!("{}/{}", base, url)
                }
            }
            None => url.to_string(),
        }
    }
}

async fn send_request(req: reqwest::RequestBuilder) -> PyResult<ClientResponse> {
    let resp = req
        .send()
        .await
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

    let status = resp.status().as_u16();
    let mut headers = HashMap::new();
    for (k, v) in resp.headers().iter() {
        if let Ok(val) = v.to_str() {
            headers.insert(k.as_str().to_string(), val.to_string());
        }
    }
    let body = resp
        .bytes()
        .await
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

    Ok(ClientResponse {
        status,
        headers,
        body: body.to_vec(),
    })
}
