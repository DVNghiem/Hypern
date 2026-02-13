use std::collections::HashMap;
use std::sync::Arc;
use xxhash_rust::xxh3::xxh3_64;

use dashmap::DashMap;
use parking_lot::RwLock;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict};

/// A type-erased value that can be stored in the DI context
pub enum DIValue {
    /// A string value
    String(String),
    /// An integer value
    Int(i64),
    /// A float value
    Float(f64),
    /// A boolean value
    Bool(bool),
    /// Raw bytes
    Bytes(Vec<u8>),
    /// A Python object (stored as PyObject for cross-thread safety)
    PyObject(Py<PyAny>),
    /// A nested context/dictionary
    Dict(HashMap<String, DIValue>),
    /// A list of values
    List(Vec<DIValue>),
    /// Null/None value
    None,
}

impl Clone for DIValue {
    fn clone(&self) -> Self {
        match self {
            DIValue::String(s) => DIValue::String(s.clone()),
            DIValue::Int(i) => DIValue::Int(*i),
            DIValue::Float(f) => DIValue::Float(*f),
            DIValue::Bool(b) => DIValue::Bool(*b),
            DIValue::Bytes(b) => DIValue::Bytes(b.clone()),
            DIValue::PyObject(obj) => {
                // PyO3 0.27+ requires GIL to clone Py<PyAny>
                Python::attach(|py| DIValue::PyObject(obj.clone_ref(py)))
            }
            DIValue::Dict(map) => DIValue::Dict(map.clone()),
            DIValue::List(list) => DIValue::List(list.clone()),
            DIValue::None => DIValue::None,
        }
    }
}

impl DIValue {
    pub fn as_string(&self) -> Option<&str> {
        match self {
            DIValue::String(s) => Some(s),
            _ => None,
        }
    }

    pub fn as_int(&self) -> Option<i64> {
        match self {
            DIValue::Int(i) => Some(*i),
            _ => None,
        }
    }

    pub fn as_float(&self) -> Option<f64> {
        match self {
            DIValue::Float(f) => Some(*f),
            _ => None,
        }
    }

    pub fn as_bool(&self) -> Option<bool> {
        match self {
            DIValue::Bool(b) => Some(*b),
            _ => None,
        }
    }

    pub fn into_py(self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        match self {
            DIValue::String(s) => Ok(s.into_pyobject(py)?.into_any().unbind()),
            DIValue::Int(i) => Ok(i.into_pyobject(py)?.into_any().unbind()),
            DIValue::Float(f) => Ok(f.into_pyobject(py)?.into_any().unbind()),
            DIValue::Bool(b) => {
                let py_bool = b.into_pyobject(py)?;
                Ok(py_bool.to_owned().into_any().unbind())
            }
            DIValue::Bytes(b) => Ok(pyo3::types::PyBytes::new(py, &b).into_any().unbind()),
            DIValue::PyObject(obj) => Ok(obj),
            DIValue::Dict(map) => {
                let dict = PyDict::new(py);
                for (k, v) in map {
                    dict.set_item(k, v.into_py(py)?)?;
                }
                Ok(dict.into_any().unbind())
            }
            DIValue::List(list) => {
                let py_list = pyo3::types::PyList::empty(py);
                for v in list {
                    py_list.append(v.into_py(py)?)?;
                }
                Ok(py_list.into_any().unbind())
            }
            DIValue::None => Ok(py.None()),
        }
    }

    pub fn from_py(obj: &Bound<'_, PyAny>) -> PyResult<Self> {
        if obj.is_none() {
            return Ok(DIValue::None);
        }
        if let Ok(s) = obj.extract::<String>() {
            return Ok(DIValue::String(s));
        }
        if let Ok(b) = obj.extract::<bool>() {
            return Ok(DIValue::Bool(b));
        }
        if let Ok(i) = obj.extract::<i64>() {
            return Ok(DIValue::Int(i));
        }
        if let Ok(f) = obj.extract::<f64>() {
            return Ok(DIValue::Float(f));
        }
        if let Ok(bytes) = obj.extract::<Vec<u8>>() {
            return Ok(DIValue::Bytes(bytes));
        }
        // For complex objects, store as PyObject
        Ok(DIValue::PyObject(obj.clone().unbind()))
    }
}

#[pyclass]
#[derive(Clone)]
pub struct Context {
    values: Arc<DashMap<String, DIValue>>,
    #[pyo3(get)]
    pub user_id: Option<String>,
    #[pyo3(get)]
    pub is_authenticated: bool,
    roles: Arc<RwLock<Vec<String>>>,
    #[pyo3(get)]
    pub request_id: String,
    start_time: std::time::Instant,
}

impl Default for Context {
    fn default() -> Self {
        Self::new()
    }
}

#[pymethods]
impl Context {
    #[new]
    pub fn new() -> Self {
        let now = std::time::Instant::now();
        let request_id = format!("{:016x}", xxh3_64(&now.elapsed().as_nanos().to_le_bytes()));

        Self {
            values: Arc::new(DashMap::new()),
            user_id: None,
            is_authenticated: false,
            roles: Arc::new(RwLock::new(Vec::new())),
            request_id,
            start_time: now,
        }
    }

    pub fn set(&self, key: String, value: &Bound<'_, PyAny>) -> PyResult<()> {
        let di_value = DIValue::from_py(value)?;
        self.values.insert(key, di_value);
        Ok(())
    }

    pub fn get(&self, py: Python<'_>, key: &str) -> PyResult<Py<PyAny>> {
        match self.values.get(key) {
            Some(entry) => entry.value().clone().into_py(py),
            None => Ok(py.None()),
        }
    }

    pub fn has(&self, key: &str) -> bool {
        self.values.contains_key(key)
    }

    pub fn remove(&self, key: &str) -> bool {
        self.values.remove(key).is_some()
    }

    pub fn keys(&self) -> Vec<String> {
        self.values.iter().map(|e| e.key().clone()).collect()
    }

    pub fn set_auth(&mut self, user_id: String, roles: Vec<String>) {
        self.user_id = Some(user_id);
        self.is_authenticated = true;
        *self.roles.write() = roles;
    }

    pub fn clear_auth(&mut self) {
        self.user_id = None;
        self.is_authenticated = false;
        self.roles.write().clear();
    }

    pub fn has_role(&self, role: &str) -> bool {
        self.roles.read().contains(&role.to_string())
    }

    #[getter(roles)]
    pub fn get_roles(&self) -> Vec<String> {
        self.roles.read().clone()
    }

    pub fn elapsed(&self) -> f64 {
        self.start_time.elapsed().as_secs_f64()
    }

    pub fn elapsed_ms(&self) -> f64 {
        self.start_time.elapsed().as_secs_f64() * 1000.0
    }

    pub fn to_dict(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let dict = PyDict::new(py);
        for entry in self.values.iter() {
            let key = entry.key().clone();
            let value = entry.value().clone().into_py(py)?;
            dict.set_item(key, value)?;
        }
        dict.set_item("user_id", &self.user_id)?;
        dict.set_item("is_authenticated", self.is_authenticated)?;
        dict.set_item("roles", self.get_roles())?;
        dict.set_item("request_id", &self.request_id)?;
        Ok(dict.into_any().unbind())
    }
}

impl Context {
    pub fn set_value(&self, key: impl Into<String>, value: DIValue) {
        self.values.insert(key.into(), value);
    }

    pub fn get_value(&self, key: &str) -> Option<DIValue> {
        self.values.get(key).map(|e| e.value().clone())
    }

    pub fn set_string(&self, key: impl Into<String>, value: impl Into<String>) {
        self.set_value(key, DIValue::String(value.into()));
    }

    pub fn set_int(&self, key: impl Into<String>, value: i64) {
        self.set_value(key, DIValue::Int(value));
    }

    pub fn set_bool(&self, key: impl Into<String>, value: bool) {
        self.set_value(key, DIValue::Bool(value));
    }
}

#[pyclass]
#[derive(Clone)]
pub struct DIContainer {
    /// Singleton instances
    singletons: Arc<DashMap<String, DIValue>>,
    /// Factory functions (stored as Python callables)
    factories: Arc<DashMap<String, Py<PyAny>>>,
}

impl Default for DIContainer {
    fn default() -> Self {
        Self::new()
    }
}

#[pymethods]
impl DIContainer {
    #[new]
    pub fn new() -> Self {
        Self {
            singletons: Arc::new(DashMap::new()),
            factories: Arc::new(DashMap::new()),
        }
    }

    pub fn singleton(&self, name: String, value: &Bound<'_, PyAny>) -> PyResult<()> {
        let di_value = DIValue::from_py(value)?;
        self.singletons.insert(name, di_value);
        Ok(())
    }

    pub fn factory(&self, name: String, factory: Py<PyAny>) {
        self.factories.insert(name, factory);
    }

    pub fn get_singleton(&self, py: Python<'_>, name: &str) -> PyResult<Py<PyAny>> {
        match self.singletons.get(name) {
            Some(entry) => entry.value().clone().into_py(py),
            None => Ok(py.None()),
        }
    }

    pub fn create_context(&self, py: Python<'_>) -> PyResult<Context> {
        let ctx = Context::new();

        // Inject singletons
        for entry in self.singletons.iter() {
            ctx.values
                .insert(entry.key().clone(), entry.value().clone());
        }

        // Call factories and inject results
        for entry in self.factories.iter() {
            let factory = entry.value();
            let result = factory.call0(py)?;
            let di_value = DIValue::from_py(result.bind(py))?;
            ctx.values.insert(entry.key().clone(), di_value);
        }

        Ok(ctx)
    }

    pub fn has(&self, name: &str) -> bool {
        self.singletons.contains_key(name) || self.factories.contains_key(name)
    }

    pub fn remove(&self, name: &str) -> bool {
        self.singletons.remove(name).is_some() || self.factories.remove(name).is_some()
    }
}

impl DIContainer {
    pub fn set_singleton(&self, name: impl Into<String>, value: DIValue) {
        self.singletons.insert(name.into(), value);
    }

    pub fn get_singleton_value(&self, name: &str) -> Option<DIValue> {
        self.singletons.get(name).map(|e| e.value().clone())
    }
}
