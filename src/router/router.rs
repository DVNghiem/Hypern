use super::route::Route;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

/// Contains the thread safe hashmaps of different routes
#[pyclass]
#[derive(Debug, Default, FromPyObject)]
pub struct Router {
    #[pyo3(get, set)]
    path: String,

    #[pyo3(get, set)]
    routes: Vec<Route>,
}

#[pymethods]
impl Router {
    #[new]
    fn new(path: &str) -> Self {
        Self {
            path: path.to_string(),
            routes: Vec::new(),
        }
    }

    /// Add a new route to the router
    pub fn add_route(&mut self, mut route: Route) -> PyResult<()> {
        // Validate route before adding
        if !route.is_valid() {
            return Err(PyValueError::new_err("Invalid route configuration"));
        }
        // Check for duplicate routes
        if self.has_duplicate_route(&route) {
            return Err(PyValueError::new_err(format!(
                "Route {} {} already exists",
                route.method, route.path
            )));
        }

        // get full path and update to route
        let full_path = self.get_full_path(&route.path);
        route.update_path(&full_path);

        self.routes.push(route);
        self.sort_routes();
        Ok(())
    }

    // extend list route
    pub fn extend_route(&mut self, routes: Vec<Route>) -> PyResult<()> {
        for route in routes {
            let _ = self.add_route(route);
        }
        Ok(())
    }

    /// Remove a route by path and method
    pub fn remove_route(&mut self, path: &str, method: &str) -> PyResult<bool> {
        if let Some(index) = self
            .routes
            .iter()
            .position(|r| r.path == path && r.method.to_uppercase() == method.to_uppercase())
        {
            self.routes.remove(index);
            Ok(true)
        } else {
            Ok(false)
        }
    }

    /// Get route by path and method
    #[pyo3(name = "get_route")]
    pub fn get_route_py(&self, path: &str, method: &str) -> PyResult<Option<Route>> {
        Ok(self
            .routes
            .iter()
            .find(|r| r.matches(path, method))
            .cloned())
    }

    /// Get all routes for a specific path
    #[pyo3(name = "get_routes_by_path")]
    pub fn get_routes_by_path_py(&self, path: &str) -> Vec<Route> {
        self.routes
            .iter()
            .filter(|r| r.path == path)
            .cloned()
            .collect()
    }

    /// Get all routes for a specific HTTP method
    #[pyo3(name = "get_routes_by_method")]
    pub fn get_routes_by_method_py(&self, method: &str) -> Vec<Route> {
        self.routes
            .iter()
            .filter(|r| r.method.to_uppercase() == method.to_uppercase())
            .cloned()
            .collect()
    }

    /// Clear all routes
    pub fn clear_routes(&mut self) {
        self.routes.clear();
    }

    /// Get number of routes
    pub fn route_count(&self) -> usize {
        self.routes.len()
    }

    /// Check if router has any routes
    pub fn is_empty(&self) -> bool {
        self.routes.is_empty()
    }

    /// Get routes with parameters
    #[pyo3(name = "get_parameterized_routes")]
    pub fn get_parameterized_routes_py(&self) -> Vec<Route> {
        self.routes
            .iter()
            .filter(|r| r.has_parameters())
            .cloned()
            .collect()
    }

    /// Update base path for router
    pub fn update_base_path(&mut self, new_path: &str) -> PyResult<()> {
        if !new_path.starts_with('/') {
            return Err(PyValueError::new_err("Base path must start with '/'"));
        }
        self.path = new_path.to_string();
        Ok(())
    }

    /// Get full path for a route (combining base path and route path)
    pub fn get_full_path(&self, route_path: &str) -> String {
        let base = self.path.trim_end_matches('/');
        let route = route_path.trim_start_matches('/');
        if base.is_empty() {
            format!("/{}", route)
        } else if route.is_empty() {
            base.to_string()
        } else {
            format!("{}/{}", base, route)
        }
    }

    /// Check if router contains a specific route
    pub fn contains_route(&self, path: &str, method: &str) -> bool {
        self.routes.iter().any(|r| r.matches(path, method))
    }

    /// Get string representation of router
    fn __str__(&self) -> PyResult<String> {
        Ok(format!(
            "Router(base_path='{}', routes={})",
            self.path,
            self.routes.len()
        ))
    }

    /// Get detailed representation of router
    fn __repr__(&self) -> PyResult<String> {
        let routes_str: Vec<String> = self
            .routes
            .iter()
            .map(|r| format!("\n  {} {}", r.method, r.path))
            .collect();
        Ok(format!(
            "Router(base_path='{}', routes:[{}]\n])",
            self.path,
            routes_str.join("")
        ))
    }

    // Find most specific matching route for a path
    #[pyo3(name = "find_matching_route")]
    pub fn find_matching_route_py(&self, path: &str, method: &str) -> PyResult<Option<Route>> {
        Ok(self.find_matching_route(path, method).cloned())
    }
}

impl Router {
    pub fn iter(&self) -> std::slice::Iter<Route> {
        self.routes.iter()
    }

    // Helper method to check for duplicate routes
    fn has_duplicate_route(&self, new_route: &Route) -> bool {
        self.routes.iter().any(|r| {
            r.path == new_route.path && r.method.to_uppercase() == new_route.method.to_uppercase()
        })
    }

    // Sort routes by specificity and method
    fn sort_routes(&mut self) {
        self.routes.sort_by(|a, b| {
            // First compare by path length (longer paths first)
            let path_order = b.path.len().cmp(&a.path.len());
            if path_order != std::cmp::Ordering::Equal {
                return path_order;
            }

            // Then compare by method priority
            a.get_method_priority().cmp(&b.get_method_priority())
        });
    }

    // Find most specific matching route for a path (internal method)
    fn find_matching_route(&self, path: &str, method: &str) -> Option<&Route> {
        // First try exact match
        if let Some(route) = self.routes.iter().find(|r| r.matches(path, method)) {
            return Some(route);
        }

        // Then try parameterized routes
        self.routes
            .iter()
            .filter(|r| r.method.to_uppercase() == method.to_uppercase())
            .find(|r| self.path_matches_pattern(path, &r.path))
    }

    // Check if a path matches a pattern (including parameters)
    fn path_matches_pattern(&self, path: &str, pattern: &str) -> bool {
        let path_segments: Vec<&str> = path.split('/').filter(|s| !s.is_empty()).collect();
        let pattern_segments: Vec<&str> = pattern.split('/').filter(|s| !s.is_empty()).collect();

        if path_segments.len() != pattern_segments.len() {
            return false;
        }

        path_segments
            .iter()
            .zip(pattern_segments.iter())
            .all(|(path_seg, pattern_seg)| pattern_seg.starts_with(':') || path_seg == pattern_seg)
    }
}