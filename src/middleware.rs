use pyo3::prelude::*;

/// Middleware function type - takes request/response and can modify them
#[pyclass]
pub struct Middleware {
    #[pyo3(get, set)]
    pub function: PyObject,
    
    #[pyo3(get, set)]
    pub name: String,
    
    #[pyo3(get, set)]
    pub path: Option<String>, // If None, applies to all routes
}

impl Clone for Middleware {
    fn clone(&self) -> Self {
        Python::with_gil(|py| Self {
            function: self.function.clone_ref(py),
            name: self.name.clone(),
            path: self.path.clone(),
        })
    }
}

#[pymethods]
impl Middleware {
    #[new]
    #[pyo3(signature = (function, name, path = None))]
    pub fn new(function: PyObject, name: String, path: Option<String>) -> Self {
        Self {
            function,
            name,
            path,
        }
    }
    
    /// Check if this middleware applies to the given path
    pub fn applies_to(&self, path: &str) -> bool {
        match &self.path {
            None => true, // Global middleware
            Some(middleware_path) => {
                // Simple path matching - could be enhanced for pattern matching
                path.starts_with(middleware_path.trim_end_matches('/'))
            }
        }
    }
    
    fn __str__(&self) -> PyResult<String> {
        Ok(format!("Middleware(name='{}', path={:?})", self.name, self.path))
    }
}

/// Collection of middleware organized by execution order
#[derive(Clone, Default)]
pub struct MiddlewareChain {
    pub before: Vec<Middleware>,  // Executed before route handler
    pub after: Vec<Middleware>,   // Executed after route handler
    pub error: Vec<Middleware>,   // Executed on error
}

impl MiddlewareChain {
    pub fn new() -> Self {
        Self::default()
    }
    
    pub fn add_before(&mut self, middleware: Middleware) {
        self.before.push(middleware);
    }
    
    pub fn add_after(&mut self, middleware: Middleware) {
        self.after.push(middleware);
    }
    
    pub fn add_error(&mut self, middleware: Middleware) {
        self.error.push(middleware);
    }
    
    /// Get all applicable middleware for a given path
    pub fn get_applicable_before(&self, path: &str) -> Vec<&Middleware> {
        self.before.iter().filter(|m| m.applies_to(path)).collect()
    }
    
    pub fn get_applicable_after(&self, path: &str) -> Vec<&Middleware> {
        self.after.iter().filter(|m| m.applies_to(path)).collect()
    }
    
    pub fn get_applicable_error(&self, path: &str) -> Vec<&Middleware> {
        self.error.iter().filter(|m| m.applies_to(path)).collect()
    }
}
