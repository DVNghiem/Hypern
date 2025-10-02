use hyper::header::HeaderMap;
use pyo3::prelude::*;
use pyo3::types::{PyIterator, PyList, PyString};

#[pyclass(frozen)]
#[derive(Clone)]
pub(crate) struct HypernHeaders {
    inner: HeaderMap,
}

impl HypernHeaders {
    pub fn new(map: HeaderMap) -> Self {
        Self { inner: map }
    }
    
    /// Public method to get header value
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
    fn get(&self, py: Python, key: &str, default: Option<PyObject>) -> Option<PyObject> {
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
