use std::collections::HashMap;

use super::route::Route;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

/// :param -> {param}
/// *wildcard -> {*wildcard}
fn convert_to_matchit_path(path: &str) -> String {
    let mut result = String::with_capacity(path.len() + 4);
    let mut chars = path.chars().peekable();

    while let Some(c) = chars.next() {
        if c == ':' {
            // Convert :param to {param}
            result.push('{');
            while let Some(&next) = chars.peek() {
                if next == '/' || next == '-' || next == '.' {
                    break;
                }
                result.push(chars.next().unwrap());
            }
            result.push('}');
        } else if c == '*' {
            // Convert *wildcard to {*wildcard}
            result.push('{');
            result.push('*');
            while let Some(&next) = chars.peek() {
                if next == '/' {
                    break;
                }
                result.push(chars.next().unwrap());
            }
            result.push('}');
        } else {
            result.push(c);
        }
    }

    result
}

/// Contains routers for each HTTP method using matchit
#[pyclass]
#[derive(Clone)]
pub struct Router {
    #[pyo3(get, set)]
    path: String,

    #[pyo3(get)]
    routes: Vec<Route>,

    // One matchit router per HTTP method for efficient lookups
    #[pyo3(get)]
    get_router: MatchitRouter,
    #[pyo3(get)]
    post_router: MatchitRouter,
    #[pyo3(get)]
    put_router: MatchitRouter,
    #[pyo3(get)]
    delete_router: MatchitRouter,
    #[pyo3(get)]
    patch_router: MatchitRouter,
    #[pyo3(get)]
    head_router: MatchitRouter,
    #[pyo3(get)]
    options_router: MatchitRouter,
}

/// Wrapper around matchit::Router to make it Clone and PyO3 compatible
#[derive(Clone, Default)]
#[pyclass]
pub struct MatchitRouter {
    inner: matchit::Router<Route>,
}

impl MatchitRouter {
    fn new() -> Self {
        Self {
            inner: matchit::Router::new(),
        }
    }

    fn insert(&mut self, path: &str, route: Route) -> Result<(), matchit::InsertError> {
        let matchit_path = convert_to_matchit_path(path);
        self.inner.insert(&matchit_path, route)
    }

    fn at(&self, path: &str) -> Option<(Route, HashMap<String, String>)> {
        match self.inner.at(path) {
            Ok(matched) => {
                let params: HashMap<String, String> = matched
                    .params
                    .iter()
                    .map(|(k, v)| (k.to_string(), v.to_string()))
                    .collect();
                Some((matched.value.clone(), params))
            }
            Err(_) => None,
        }
    }
}

impl Default for Router {
    fn default() -> Self {
        Self {
            path: String::new(),
            routes: Vec::new(),
            get_router: MatchitRouter::new(),
            post_router: MatchitRouter::new(),
            put_router: MatchitRouter::new(),
            delete_router: MatchitRouter::new(),
            patch_router: MatchitRouter::new(),
            head_router: MatchitRouter::new(),
            options_router: MatchitRouter::new(),
        }
    }
}

#[pymethods]
impl Router {
    #[new]
    pub fn new(path: &str) -> Self {
        Self {
            path: path.to_string(),
            ..Default::default()
        }
    }

    /// Add a new route to the router
    pub fn add_route(&mut self, route: Route) -> PyResult<()> {
        // Validate route
        if !route.is_valid() {
            return Err(PyValueError::new_err("Invalid route configuration"));
        }

        let full_path = self.get_full_path(&route.path);
        let method = route.method.to_uppercase();

        // Add to appropriate matchit router
        let router = match method.as_str() {
            "GET" => &mut self.get_router,
            "POST" => &mut self.post_router,
            "PUT" => &mut self.put_router,
            "DELETE" => &mut self.delete_router,
            "PATCH" => &mut self.patch_router,
            "HEAD" => &mut self.head_router,
            "OPTIONS" => &mut self.options_router,
            _ => {
                return Err(PyValueError::new_err(format!(
                    "Unknown HTTP method: {}",
                    method
                )))
            }
        };

        router
            .insert(&full_path, route.clone())
            .map_err(|e| PyValueError::new_err(format!("Failed to add route: {}", e)))?;

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
    pub fn find_matching_route(
        &self,
        path: &str,
        method: &str,
    ) -> Option<(Route, HashMap<String, String>)> {
        // Fast method dispatch without allocation - methods from HTTP are already uppercase
        let router = match method {
            "GET" => &self.get_router,
            "POST" => &self.post_router,
            "PUT" => &self.put_router,
            "DELETE" => &self.delete_router,
            "PATCH" => &self.patch_router,
            "HEAD" => &self.head_router,
            "OPTIONS" => &self.options_router,
            _ => {
                // Fallback for non-standard methods - do the uppercase conversion
                let method = method.to_uppercase();
                return match method.as_str() {
                    "GET" => self.get_router.at(path),
                    "POST" => self.post_router.at(path),
                    "PUT" => self.put_router.at(path),
                    "DELETE" => self.delete_router.at(path),
                    "PATCH" => self.patch_router.at(path),
                    "HEAD" => self.head_router.at(path),
                    "OPTIONS" => self.options_router.at(path),
                    _ => None,
                };
            }
        };

        router.at(path)
    }
}

impl Router {
    pub fn iter(&'_ self) -> std::slice::Iter<'_, Route> {
        self.routes.iter()
    }

    pub fn routes_count(&self) -> usize {
        self.routes.len()
    }
}
