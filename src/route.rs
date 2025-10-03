use pyo3::prelude::*;

#[pyclass]
pub struct Route {
    #[pyo3(get, set)]
    pub path: String,

    #[pyo3(get, set)]
    pub function: PyObject,

    #[pyo3(get, set)]
    pub method: String,

    #[pyo3(get, set)]
    pub doc: Option<String>,
}

impl Clone for Route {
    fn clone(&self) -> Self {
        Python::with_gil(|py| {
            Self {
                path: self.path.clone(),
                function: self.function.clone_ref(py),
                method: self.method.clone(),
                doc: self.doc.clone(),
            }
        })
    }
}

#[pymethods]
impl Route {
    #[new]
    #[pyo3(signature = (path, function, method, doc = None))]
    pub fn new(path: &str, function: PyObject, method: String, doc: Option<String>) -> Self {
        Self {
            path: path.to_string(),
            function,
            method,
            doc
        }
    }

    // Get a formatted string representation of the route
    pub fn __str__(&self) -> PyResult<String> {
        Ok(format!("{} {}", self.method, self.path))
    }

    // Get a formatted representation for debugging
    pub fn __repr__(&self) -> PyResult<String> {
        Ok(format!("Route(path='{}', method='{}')", 
            self.path, self.method))
    }

    // Update the route path
    pub fn update_path(&mut self, new_path: &str) {
        self.path = new_path.to_string();
    }

    // Update the route method
    pub fn update_method(&mut self, new_method: &str) {
        self.method = new_method.to_uppercase();
    }

    // Validate if the route configuration is correct
    pub fn is_valid(&self) -> bool {
        // Path should start with '/'
        if !self.path.starts_with('/') {
            return false;
        }

        // Method should be a valid HTTP method
        let valid_methods = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"];
        if !valid_methods.contains(&self.method.to_uppercase().as_str()) {
            return false;
        }

        true
    }

    // Get route parameters from path
    pub fn get_path_params(&self) -> Vec<String> {
        self.path
            .split('/')
            .filter(|segment| segment.starts_with(':'))
            .map(|param| param[1..].to_string())
            .collect()
    }

    // Check if route has path parameters
    pub fn has_parameters(&self) -> bool {
        self.path.contains(':')
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

    // Get method name for sorting and comparison
    pub fn get_method_priority(&self) -> u8 {
        match self.method.to_uppercase().as_str() {
            "GET" => 1,
            "POST" => 2,
            "PUT" => 3,
            "PATCH" => 4,
            "DELETE" => 5,
            "HEAD" => 6,
            "OPTIONS" => 7,
            _ => 99
        }
    }

    pub fn matches(&self, path: &str, method: &str) -> bool {
        if self.method.to_uppercase() != method.to_uppercase() {
            return false;
        }

        let route_parts: Vec<&str> = self.path.split('/')
            .filter(|s| !s.is_empty())
            .collect();
        let path_parts: Vec<&str> = path.split('/')
            .filter(|s| !s.is_empty())
            .collect();

        if route_parts.len() != path_parts.len() {
            return false;
        }

        for (route_part, path_part) in route_parts.iter().zip(path_parts.iter()) {
            if !route_part.starts_with(':') && route_part != path_part {
                return false;
            }
        }

        true
    }
}