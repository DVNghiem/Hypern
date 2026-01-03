use ahash::AHashMap;
use hyper::HeaderMap;
use pyo3::prelude::*;

/// headers using AHashMap for O(1) lookups
#[pyclass(frozen)]
#[derive(Clone, Debug, Default)]
pub struct FastHeaders {
    headers: AHashMap<String, String>,
}

impl FastHeaders {
    pub fn new() -> Self {
        Self {
            headers: AHashMap::with_capacity(16),
        }
    }

    pub fn from_hyper(headers: &HeaderMap) -> Self {
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

    pub fn len(&self) -> usize {
        self.headers.len()
    }

    pub fn is_empty(&self) -> bool {
        self.headers.is_empty()
    }
}

#[pymethods]
impl FastHeaders {
    #[new]
    fn py_new() -> Self {
        Self::new()
    }

    /// Get header value by name (case-insensitive)
    pub fn get_header(&self, name: &str) -> Option<String> {
        self.get(name).cloned()
    }

    /// Check if header exists
    pub fn has(&self, name: &str) -> bool {
        self.headers.contains_key(&name.to_lowercase())
    }

    /// Get all header names
    pub fn keys(&self) -> Vec<String> {
        self.headers.keys().cloned().collect()
    }

    /// Get all header values
    pub fn values(&self) -> Vec<String> {
        self.headers.values().cloned().collect()
    }

    /// Get number of headers
    fn __len__(&self) -> usize {
        self.headers.len()
    }

    fn __contains__(&self, key: &str) -> bool {
        self.has(key)
    }

    fn __getitem__(&self, key: &str) -> PyResult<String> {
        self.get(key)
            .cloned()
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err(key.to_string()))
    }

    fn __repr__(&self) -> String {
        format!("FastHeaders({})", self.headers.len())
    }
}
