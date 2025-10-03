use std::collections::HashMap;

use crate::radix::RadixNode;
use crate::route::Route;
use crate::middleware::{Middleware, MiddlewareChain};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

/// Contains the thread safe hashmaps of different routes
#[pyclass]
#[derive(Default, Clone)]
pub struct Router {
    #[pyo3(get, set)]
    path: String,

    #[pyo3(get)]
    routes: Vec<Route>,

    radix_tree: RadixNode,
    
    middleware_chain: MiddlewareChain,
}

#[pymethods]
impl Router {
    #[new]
    pub fn new(path: &str) -> Self {
        Self {
            path: path.to_string(),
            routes: Vec::new(),
            radix_tree: RadixNode::new(),
            middleware_chain: MiddlewareChain::new(),
        }
    }

    /// Add middleware that runs before route handlers
    pub fn use_middleware(&mut self, middleware: Middleware) -> PyResult<()> {
        self.middleware_chain.add_before(middleware);
        Ok(())
    }
    
    /// Add middleware that runs after route handlers
    pub fn use_after_middleware(&mut self, middleware: Middleware) -> PyResult<()> {
        self.middleware_chain.add_after(middleware);
        Ok(())
    }
    
    /// Add error handling middleware
    pub fn use_error_middleware(&mut self, middleware: Middleware) -> PyResult<()> {
        self.middleware_chain.add_error(middleware);
        Ok(())
    }
    
    /// Get applicable middleware for a path (Python accessible)
    pub fn get_middleware_for_path(&self, path: &str) -> (Vec<Middleware>, Vec<Middleware>, Vec<Middleware>) {
        (
            self.middleware_chain.get_applicable_before(path).into_iter().cloned().collect(),
            self.middleware_chain.get_applicable_after(path).into_iter().cloned().collect(),
            self.middleware_chain.get_applicable_error(path).into_iter().cloned().collect(),
        )
    }

    /// Add a new route to the router
    pub fn add_route(&mut self, route: Route) -> PyResult<()> {
        // Validate route
        if !route.is_valid() {
            return Err(PyValueError::new_err("Invalid route configuration"));
        }

        let full_path = self.get_full_path(&route.path);

        // Add to radix tree
        self.radix_tree.insert(&full_path, route.clone());
        
        // Keep the routes vector for backwards compatibility and iteration
        self.routes.push(route);
        
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
            .map(|r| r.clone()))
    }

    /// Get all routes for a specific path
    #[pyo3(name = "get_routes_by_path")]
    pub fn get_routes_by_path_py(&self, path: &str) -> Vec<Route> {
        self.routes
            .iter()
            .filter(|r| r.path == path)
            .map(|r| r.clone())
            .collect()
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
    pub fn find_matching_route(&self, path: &str, method: &str) -> Option<(Route, HashMap<String, String>)> {
        if let Some((route, params)) = self.radix_tree.find(path, method) {
            return Some((route.clone(), params));
        }
        None
    }
    
}

impl Router {
    pub fn iter(&self) -> std::slice::Iter<Route> {
        self.routes.iter()
    }
    
    pub fn routes_count(&self) -> usize {
        self.routes.len()
    }
    
    /// Internal method to get middleware references (for performance)
    pub fn get_middleware_refs_for_path(&self, path: &str) -> (Vec<&Middleware>, Vec<&Middleware>, Vec<&Middleware>) {
        (
            self.middleware_chain.get_applicable_before(path),
            self.middleware_chain.get_applicable_after(path),
            self.middleware_chain.get_applicable_error(path),
        )
    }
}