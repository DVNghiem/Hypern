use pyo3::prelude::*;
use std::collections::HashMap;

/// ExpressJS-style response builder
#[pyclass]
pub struct ResponseBuilder {
    status_code: u16,
    headers: HashMap<String, String>,
    body: Option<ResponseBody>,
    sent: bool,
}

#[derive(Clone)]
enum ResponseBody {
    Empty,
    Text(String),
    Json(String),
    Bytes(Vec<u8>),
    Html(String),
}

#[pymethods]
impl ResponseBuilder {
    #[new]
    pub fn new() -> Self {
        Self {
            status_code: 200,
            headers: HashMap::new(),
            body: None,
            sent: false,
        }
    }

    /// Set response status code
    pub fn status(&mut self, code: u16) -> PyResult<()> {
        if self.sent {
            return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("Response already sent"));
        }
        self.status_code = code;
        Ok(())
    }

    /// Set a header
    pub fn set_header(&mut self, name: &str, value: &str) -> PyResult<()> {
        if self.sent {
            return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("Response already sent"));
        }
        self.headers.insert(name.to_string(), value.to_string());
        Ok(())
    }

    /// Set multiple headers
    pub fn set_headers(&mut self, headers: HashMap<String, String>) -> PyResult<()> {
        if self.sent {
            return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("Response already sent"));
        }
        for (name, value) in headers {
            self.headers.insert(name, value);
        }
        Ok(())
    }

    /// Get current status code
    #[getter]
    pub fn status_code(&self) -> u16 {
        self.status_code
    }

    /// Get headers
    #[getter]  
    pub fn get_headers(&self) -> HashMap<String, String> {
        self.headers.clone()
    }

    /// Send JSON response
    pub fn json(&mut self, data: PyObject) -> PyResult<()> {
        if self.sent {
            return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("Response already sent"));
        }

        // Convert Python object to JSON string
        Python::with_gil(|py| {
            let json_module = py.import("json")?;
            let json_str = json_module.call_method1("dumps", (data,))?;
            let json_string: String = json_str.extract()?;
            
            self.set_header("content-type", "application/json")?;
            self.body = Some(ResponseBody::Json(json_string));
            self.sent = true;
            Ok(())
        })
    }

    /// Send text response
    pub fn text(&mut self, text: &str) -> PyResult<()> {
        if self.sent {
            return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("Response already sent"));
        }
        
        self.set_header("content-type", "text/plain; charset=utf-8")?;
        self.body = Some(ResponseBody::Text(text.to_string()));
        self.sent = true;
        Ok(())
    }

    /// Send HTML response
    pub fn html(&mut self, html: &str) -> PyResult<()> {
        if self.sent {
            return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("Response already sent"));
        }
        
        self.set_header("content-type", "text/html; charset=utf-8")?;
        self.body = Some(ResponseBody::Html(html.to_string()));
        self.sent = true;
        Ok(())
    }

    /// Send bytes response
    pub fn bytes(&mut self, data: Vec<u8>) -> PyResult<()> {
        if self.sent {
            return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("Response already sent"));
        }
        
        self.body = Some(ResponseBody::Bytes(data));
        self.sent = true;
        Ok(())
    }

    /// Send empty response
    pub fn send(&mut self) -> PyResult<()> {
        if self.sent {
            return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("Response already sent"));
        }
        
        self.body = Some(ResponseBody::Empty);
        self.sent = true;
        Ok(())
    }

    /// Set cookie
    pub fn cookie(&mut self, name: &str, value: &str, options: Option<HashMap<String, PyObject>>) -> PyResult<()> {
        if self.sent {
            return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("Response already sent"));
        }

        let mut cookie_str = format!("{}={}", name, value);
        
        if let Some(opts) = options {
            Python::with_gil(|py| {
                for (key, val) in opts {
                    match key.as_str() {
                        "max_age" => {
                            if let Ok(age) = val.extract::<i64>(py) {
                                cookie_str.push_str(&format!("; Max-Age={}", age));
                            }
                        }
                        "expires" => {
                            if let Ok(exp) = val.extract::<String>(py) {
                                cookie_str.push_str(&format!("; Expires={}", exp));
                            }
                        }
                        "domain" => {
                            if let Ok(domain) = val.extract::<String>(py) {
                                cookie_str.push_str(&format!("; Domain={}", domain));
                            }
                        }
                        "path" => {
                            if let Ok(path) = val.extract::<String>(py) {
                                cookie_str.push_str(&format!("; Path={}", path));
                            }
                        }
                        "secure" => {
                            if let Ok(secure) = val.extract::<bool>(py) {
                                if secure {
                                    cookie_str.push_str("; Secure");
                                }
                            }
                        }
                        "http_only" => {
                            if let Ok(http_only) = val.extract::<bool>(py) {
                                if http_only {
                                    cookie_str.push_str("; HttpOnly");
                                }
                            }
                        }
                        "same_site" => {
                            if let Ok(same_site) = val.extract::<String>(py) {
                                cookie_str.push_str(&format!("; SameSite={}", same_site));
                            }
                        }
                        _ => {}
                    }
                }
                Ok::<(), PyErr>(())
            })?;
        }

        // Handle multiple cookies by checking if Set-Cookie already exists
        if let Some(existing) = self.headers.get("set-cookie") {
            self.headers.insert("set-cookie".to_string(), format!("{}, {}", existing, cookie_str));
        } else {
            self.headers.insert("set-cookie".to_string(), cookie_str);
        }
        
        Ok(())
    }

    /// Clear cookie
    pub fn clear_cookie(&mut self, name: &str, options: Option<HashMap<String, PyObject>>) -> PyResult<()> {
        let mut clear_options = options.unwrap_or_default();
        Python::with_gil(|py| {
            clear_options.insert("expires".to_string(), "Thu, 01 Jan 1970 00:00:00 GMT".into_pyobject(py)?.into_any().unbind());
            clear_options.insert("max_age".to_string(), 0i32.into_pyobject(py)?.into_any().unbind());
            Ok::<(), PyErr>(())
        })?;
        
        self.cookie(name, "", Some(clear_options))
    }

    /// Redirect response
    pub fn redirect(&mut self, location: &str, status: Option<u16>) -> PyResult<()> {
        if self.sent {
            return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("Response already sent"));
        }
        
        self.status_code = status.unwrap_or(302);
        self.set_header("location", location)?;
        self.body = Some(ResponseBody::Empty);
        self.sent = true;
        Ok(())
    }

    /// Check if response was sent
    #[getter]
    pub fn is_sent(&self) -> bool {
        self.sent
    }

    /// Convert to internal response format (for internal use) - simplified for now
    pub fn get_status(&self) -> u16 {
        self.status_code
    }
    
    pub fn get_body_string(&self) -> Option<String> {
        match &self.body {
            Some(ResponseBody::Text(text)) | Some(ResponseBody::Html(text)) | Some(ResponseBody::Json(text)) => {
                Some(text.clone())
            }
            _ => None
        }
    }
    
    pub fn get_body_bytes(&self) -> Option<Vec<u8>> {
        match &self.body {
            Some(ResponseBody::Bytes(data)) => Some(data.clone()),
            _ => None
        }
    }
    
    pub fn is_empty(&self) -> bool {
        matches!(&self.body, Some(ResponseBody::Empty))
    }

    fn __str__(&self) -> PyResult<String> {
        Ok(format!("ResponseBuilder(status={}, headers={}, sent={})", 
                  self.status_code, self.headers.len(), self.sent))
    }
}

impl Default for ResponseBuilder {
    fn default() -> Self {
        Self::new()
    }
}