use ahash::AHashMap;
use hyper::HeaderMap;
use pyo3::prelude::*;
use pyo3::types::{PyIterator, PyList, PyString};

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

/// Legacy header support for backwards compatibility
#[pyclass(frozen)]
#[derive(Clone)]
pub struct HypernHeaders {
    pub(crate) inner: HeaderMap,
}

impl HypernHeaders {
    pub fn new(map: HeaderMap) -> Self {
        Self { inner: map }
    }

    pub fn get_header(&self, key: &str) -> Option<String> {
        if let Some(value) = self.inner.get(key) {
            value.to_str().ok().map(|s| s.to_string())
        } else {
            None
        }
    }
}

#[pymethods]
impl HypernHeaders {
    fn keys(&self) -> Vec<&str> {
        let mut ret = Vec::with_capacity(self.inner.keys_len());
        for key in self.inner.keys() {
            ret.push(key.as_str());
        }
        ret
    }

    fn values(&self) -> Vec<&str> {
        let mut ret = Vec::with_capacity(self.inner.len());
        for val in self.inner.values() {
            if let Ok(v) = val.to_str() {
                ret.push(v);
            }
        }
        ret
    }

    fn items(&self) -> Vec<(&str, &str)> {
        let mut ret = Vec::with_capacity(self.inner.len());
        for (key, val) in &self.inner {
            if let Ok(v) = val.to_str() {
                ret.push((key.as_str(), v));
            }
        }
        ret
    }

    fn __contains__(&self, key: &str) -> bool {
        self.inner.contains_key(key)
    }

    fn __getitem__(&self, key: &str) -> PyResult<&str> {
        if let Some(value) = self.inner.get(key) {
            return Ok(value.to_str().unwrap_or(""));
        }
        Err(pyo3::exceptions::PyKeyError::new_err(key.to_owned()).into())
    }

    fn __iter__<'p>(&self, py: Python<'p>) -> PyResult<Bound<'p, PyIterator>> {
        PyIterator::from_object(PyList::new(py, self.keys())?.as_any())
    }

    fn __len__(&self) -> usize {
        self.inner.keys_len()
    }

    #[pyo3(signature = (key, default=None))]
    fn get(&self, py: Python, key: &str, default: Option<Py<PyAny>>) -> Option<Py<PyAny>> {
        if let Some(val) = self.inner.get(key) {
            if let Ok(v) = val.to_str() {
                return Some(PyString::new(py, v).into());
            }
        }
        default
    }

    #[pyo3(signature = (key))]
    fn get_all<'p>(&self, py: Python<'p>, key: &'p str) -> PyResult<Bound<'p, PyList>> {
        PyList::new(
            py,
            self.inner
                .get_all(key)
                .iter()
                .flat_map(|v| v.to_str())
                .map(|v| PyString::new(py, v))
                .collect::<Vec<Bound<PyString>>>(),
        )
    }
}
