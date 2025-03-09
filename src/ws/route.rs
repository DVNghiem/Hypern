use pyo3::prelude::*;

#[pyclass]
#[derive(Debug)]
pub struct WebsocketRoute {
    #[pyo3(get, set)]
    pub path: String,

    #[pyo3(get, set)]
    pub handler: PyObject,
}

#[pymethods]
impl WebsocketRoute {
    #[new]
    pub fn new(path: &str, handler: PyObject) -> Self {
        Self {
            path: path.to_string(),
            handler,
        }
    }

    // Get a formatted string representation of the route
    pub fn __str__(&self) -> PyResult<String> {
        Ok(format!("{} {}", self.handler, self.path))
    }

    // Get a formatted representation for debugging
    pub fn __repr__(&self) -> PyResult<String> {
        Ok(format!("Route(path='{}', handler='{}')", 
            self.path, self.handler))
    }

    // Create a copy of the route
    pub fn clone_route(&self) -> WebsocketRoute {
        self.clone()
    }

    // Update the route path
    pub fn update_path(&mut self, new_path: &str) {
        self.path = new_path.to_string();
    }

    // Validate if the route configuration is correct
    pub fn is_valid(&self) -> bool {
        !self.path.is_empty()
    }

    // Generate a normalized version of the path
    pub fn normalized_path(&self) -> String {
        // Remove trailing slashes and ensure leading slash
        let mut path = self.path.trim_end_matches('/').to_string();
        if !path.starts_with('/') {
            path = format!("/{}", path);
        }
        path
    }

    // Compare routes for equality based only on path and method
    fn __eq__(&self, other: &PyAny) -> PyResult<bool> {
        // Try to extract other as Route
        if let Ok(other_route) = other.extract::<PyRef<WebsocketRoute>>() {
            // Compare only path and method, not the function
            Ok(self.path == other_route.path && 
               self.path.to_uppercase() == other_route.path.to_uppercase())
        } else {
            Ok(false)
        }
    }

    // Generate hash for the route based only on path and method
    fn __hash__(&self) -> PyResult<isize> {
        use std::collections::hash_map::DefaultHasher;
        use std::hash::{Hash, Hasher};
        
        let mut hasher = DefaultHasher::new();
        self.path.hash(&mut hasher);
        Ok(hasher.finish() as isize)
    }

    // Check if routes have the same handler function
    pub fn same_handler(&self, other: &WebsocketRoute) -> PyResult<bool> {
        // Compare the Python objects using the Python 'is' operator
        Ok(self.handler.is(&other.handler))
    }
}