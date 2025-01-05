use std::collections::HashMap;

use hyper::HeaderMap;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyString};

// Custom Multimap class
#[pyclass(name = "Header")]
#[derive(Clone, Debug, Default)]
pub struct Header {
    pub headers: HashMap<String, String>,
}

#[pymethods]
impl Header {
    #[new]
    pub fn new(default_headers: Option<&PyDict>) -> Self {
        match default_headers {
            Some(default_headers) => {
                let mut headers = HashMap::new();
                for (key, value) in default_headers {
                    let key = key.to_string().to_lowercase();
                    let value = value.to_string();
                    headers.insert(key, value);
                }
                Header { headers }
            }
            None => Header {
                headers: HashMap::new(),
            },
        }
    }

    pub fn set(&mut self, key: String, value: String) {
        self.headers.insert(key.to_lowercase(), value);
    }

    pub fn get(&self, key: String) -> Option<String> {
        self.headers.get(&key.to_lowercase()).cloned()
    }

    pub fn get_headers(&self, py: Python) -> Py<PyDict> {
        // return as a dict of lists
        let dict = PyDict::new(py);
        for (key, value) in &self.headers {
            let key = PyString::new(py, key);
            let value = PyString::new(py, value);
            dict.set_item(key, value).unwrap();

        }
        dict.into()
    }

    pub fn contains(&self, key: String) -> bool {
        self.headers.contains_key(&key.to_lowercase())
    }

    pub fn populate_from_dict(&mut self, headers: &PyDict) {
        for (key, value) in headers {
            let key = key.to_string().to_lowercase();
            let value = value.to_string();
            self.headers.insert(key, value);
        }
    }

    pub fn update(&mut self, headers: Py<PyDict>) {
        Python::with_gil(|py| {
            let headers = headers.as_ref(py);
            self.populate_from_dict(headers);
        });
    }

    pub fn is_empty(&self) -> bool {
        self.headers.is_empty()
    }

    pub fn __contains__(&self, key: String) -> bool {
        self.contains(key)
    }

    pub fn __repr__(&self) -> String {
        format!("{:?}", self.headers)
    }

    pub fn __setitem__(&mut self, key: String, value: String) {
        self.set(key, value);
    }

    pub fn __getitem__(&self, key: String) -> Option<String> {
        self.get(key)
    }
}

impl Header {
    pub fn remove(&mut self, key: &str) {
        self.headers.remove(&key.to_lowercase());
    }

    pub fn extend(&mut self, headers: &Header) {
        for (key, value) in &headers.headers {
            self.headers.insert(key.clone(), value.clone());
        }
    }

    pub fn from_hyper_headers(req_headers: &HeaderMap) -> Self {
        let mut headers = HashMap::new();
        for (key, value) in req_headers.iter() {
            headers.insert(
                key.as_str().to_lowercase(),
                value.to_str().unwrap().to_string(),
            );
        }
        Header { headers }
    }
}
