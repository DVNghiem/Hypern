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

    // Check if routes have the same handler function
    pub fn same_handler(&self, other: &WebsocketRoute) -> PyResult<bool> {
        // Compare the Python objects using the Python 'is' operator
        Ok(self.handler.is(&other.handler))
    }
}