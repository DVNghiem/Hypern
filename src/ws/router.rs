use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use super::route::WebsocketRoute;

#[derive(Default)]
pub struct WebsocketRouter {
    pub path: String,
    pub routes: Vec<WebsocketRoute>,
}

impl WebsocketRouter {
    pub fn iter(&self) -> std::slice::Iter<WebsocketRoute> {
        self.routes.iter()
    }

    pub fn find_route(&self, path: &str) -> Option<&WebsocketRoute> {
        self.routes.iter().find(|r| r.path == path)
    }
}

impl ToPyObject for WebsocketRouter {
    fn to_object(&self, py: Python) -> PyObject {
        let router = PyWebsocketRouter {
            path: self.path.to_string(),
            routes: self.routes.clone(),
        };
        Py::new(py, router).unwrap().as_ref(py).into()
    }
}

impl FromPyObject<'_> for WebsocketRouter {
    fn extract(ob: &PyAny) -> PyResult<Self> {
        let router = ob.extract::<PyWebsocketRouter>()?;
        Ok(Self {
            path: router.path,
            routes: router.routes,
        })
    }
}

/// Contains the thread safe hashmaps of different routes
#[pyclass(name = "WebsocketRouter")]
#[derive(Debug, Default, FromPyObject)]
pub struct PyWebsocketRouter {
    #[pyo3(get, set)]
    path: String,

    #[pyo3(get, set)]
    routes: Vec<WebsocketRoute>,
}

#[pymethods]
impl PyWebsocketRouter {
    #[new]
    fn new(path: &str) -> Self {
        Self {
            path: path.to_string(),
            routes: Vec::new(),
        }
    }

    // Helper method to check for duplicate routes
    fn has_duplicate_route(&self, new_route: &WebsocketRoute) -> bool {
        self.routes.iter().any(|r| r.path == new_route.path)
    }

    /// Add a new route to the router
    pub fn add_route(&mut self, mut route: WebsocketRoute) -> PyResult<()> {
        // Validate route before adding
        if !route.is_valid() {
            return Err(PyValueError::new_err("Invalid route configuration"));
        }

        // Check for duplicate routes
        if self.has_duplicate_route(&route) {
            return Err(PyValueError::new_err(format!(
                "Route {} {} already exists",
                route.handler, route.path
            )));
        }

        // get full path and update to route
        let full_path = self.get_full_path(&route.path);
        route.update_path(&full_path);

        self.routes.push(route);

        Ok(())
    }

    // extend list route
    pub fn extend_route(&mut self, routes: Vec<WebsocketRoute>) -> PyResult<()> {
        for route in routes {
            let _ = self.add_route(route);
        }
        Ok(())
    }

    /// Remove a route by path and method
    pub fn remove_route(&mut self, path: &str) -> PyResult<bool> {
        if let Some(index) = self.routes.iter().position(|r| r.path == path) {
            self.routes.remove(index);
            Ok(true)
        } else {
            Ok(false)
        }
    }

    /// Get all routes for a specific path
    #[pyo3(name = "get_routes_by_path")]
    pub fn get_routes_by_path_py(&self, path: &str) -> Vec<WebsocketRoute> {
        self.routes
            .iter()
            .filter(|r| r.path == path)
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

    /// Get string representation of router
    fn __str__(&self) -> PyResult<String> {
        Ok(format!(
            "Router(base_path='{}', routes={})",
            self.path,
            self.routes.len()
        ))
    }
}
