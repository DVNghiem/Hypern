use pyo3::{prelude::*, types::{PyDict, PyAny}};
use std::sync::{Arc, Mutex};

// Wrapper for thread-safe Python dependencies
#[derive(Clone, Debug)]
#[pyclass]
pub struct DependencyInjection(Arc<Mutex<Py<PyDict>>>);

impl Default for DependencyInjection {
    fn default() -> Self {
        Python::with_gil(|py| {
            let deps = PyDict::new(py);
            DependencyInjection(Arc::new(Mutex::new(deps.into_py(py))))
        })
    }
}

// Implement methods for DependencyInjection
impl DependencyInjection {

    pub fn new() -> Self {
        Python::with_gil(|py| {
            let deps = PyDict::new(py);
            DependencyInjection(Arc::new(Mutex::new(deps.into_py(py))))
        })
    }

    // Add a new dependency
    pub fn add_dependency(&self, key: &str, value: Py<PyAny>) -> PyResult<()> {
        Python::with_gil(|py| {
            let deps = self.0.lock().unwrap();
            deps.as_ref(py).set_item(key, value)?;
            Ok(())
        })
    }

    // Get a dependency
    pub fn get_dependency(&self, key: &str) -> Option<Py<PyAny>> {
        Python::with_gil(|py| {
            let deps = self.0.lock().unwrap();
            deps.as_ref(py).get_item(key).ok().map(|x| x.into_py(py))
        })
    }

    // Remove a dependency
    pub fn remove_dependency(&self, key: &str) -> PyResult<()> {
        Python::with_gil(|py| {
            let deps = self.0.lock().unwrap();
            deps.as_ref(py).del_item(key)?;
            Ok(())
        })
    }

    // Convert DependencyInjection to a Python object
    pub fn to_object(&self, py: Python) -> Py<PyDict> {
        self.0.lock().unwrap().clone().extract(py).unwrap()
    }

    // Convert a Python object to DependencyInjection
    pub fn from_object(obj: Py<PyDict>) -> Self {
        DependencyInjection(Arc::new(Mutex::new(obj)))
    }

}