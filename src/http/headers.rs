use ahash::AHashMap;
use pyo3::prelude::*;

#[pyclass]
pub struct HeaderMap {
    headers: AHashMap<String, String>,
}

#[pymethods]
impl HeaderMap {
    #[new]
    pub fn new() -> Self {
        Self {
            headers: AHashMap::with_capacity(16),
        }
    }

    pub fn get(&self, key: &str) -> Option<&String> {
        self.headers.get(&key.to_lowercase())
    }

    pub fn insert(&mut self, key: String, value: String) {
        self.headers.insert(key.to_lowercase(), value);
    }

    pub fn get_all(&self, key: &str) -> Vec<&String> {
        let key_lower = key.to_lowercase();
        self.headers
            .iter()
            .filter_map(|(k, v)| if k == &key_lower { Some(v) } else { None })
            .collect()
    }

    pub fn keys(&self) -> Vec<&String> {
        self.headers.keys().collect()
    }

    pub fn values(&self) -> Vec<&String> {
        self.headers.values().collect()
    }

    pub fn items(&self) -> Vec<(&String, &String)> {
        self.headers.iter().collect()
    }
}

impl HeaderMap {
    pub fn from_axum(headers: &axum::http::HeaderMap) -> Self {
        let mut map = AHashMap::with_capacity(headers.len());
        for (key, value) in headers.iter() {
            if let Ok(v) = value.to_str() {
                map.insert(key.as_str().to_lowercase(), v.to_string());
            }
        }
        Self { headers: map }
    }

    pub fn iter(&self) -> impl Iterator<Item = (&String, &String)> {
        self.headers.iter()
    }
}
