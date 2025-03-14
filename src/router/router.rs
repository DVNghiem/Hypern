use std::collections::HashMap;

use super::radix::RadixNode;
use super::route::Route;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

/// Contains the thread safe hashmaps of different routes
#[pyclass]
#[derive(Debug, Default)]
pub struct Router {
    #[pyo3(get, set)]
    path: String,
    radix_tree: RadixNode,
}

#[pymethods]
impl Router {
    #[new]
    fn new(path: &str) -> Self {
        Self {
            path: path.to_string(),
            radix_tree: RadixNode::new(),
        }
    }

    /// Add a new route to the router
    pub fn add_route(&mut self, route: Route) -> PyResult<()> {
        // Validate route
        if !route.is_valid() {
            return Err(PyValueError::new_err("Invalid route configuration"));
        }

        let full_path = self.get_full_path(&route.path);

        // Add to radix tree
        self.radix_tree.insert(&full_path, route);
        
        // Keep the routes vector for backwards compatibility and iteration
        // self.routes.push(route);
        
        Ok(())
    }

    // extend list route
    pub fn extend_route(&mut self, routes: Vec<Route>) -> PyResult<()> {
        for route in routes {
            let _ = self.add_route(route);
        }
        Ok(())
    }

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
}

impl Router {
    // Find most specific matching route for a path
    pub fn find_matching_route(&mut self, path: &str, method: &str) -> Option<(&Route, HashMap<String, String>)> {
        if let Some((route, params)) = self.radix_tree.find(path, method) {
            return Some((route, params));
        }
        None
    }
}