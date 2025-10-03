use crate::{route::Route, router::Router, middleware::Middleware};
use pyo3::prelude::*;

/// ExpressJS-inspired application structure
#[pyclass]
pub struct Application {
    #[pyo3(get)]
    router: Router,
    
    /// Application-level middleware
    middleware: Vec<Middleware>,
    
    /// Application settings
    settings: std::collections::HashMap<String, PyObject>,
}

#[pymethods]
impl Application {
    #[new]
    pub fn new() -> Self {
        Self {
            router: Router::new(""),
            middleware: Vec::new(),
            settings: std::collections::HashMap::new(),
        }
    }

    /// Express-style app.get() method
    #[pyo3(signature = (path, handler, **_kwargs))]
    pub fn get(&mut self, path: &str, handler: PyObject, _kwargs: Option<std::collections::HashMap<String, PyObject>>) -> PyResult<()> {
        let route = Route::new(path, handler, "GET".to_string(), None);
        self.router.add_route(route)
    }

    /// Express-style app.post() method
    #[pyo3(signature = (path, handler, **_kwargs))]
    pub fn post(&mut self, path: &str, handler: PyObject, _kwargs: Option<std::collections::HashMap<String, PyObject>>) -> PyResult<()> {
        let route = Route::new(path, handler, "POST".to_string(), None);
        self.router.add_route(route)
    }

    /// Express-style app.put() method
    #[pyo3(signature = (path, handler, **_kwargs))]
    pub fn put(&mut self, path: &str, handler: PyObject, _kwargs: Option<std::collections::HashMap<String, PyObject>>) -> PyResult<()> {
        let route = Route::new(path, handler, "PUT".to_string(), None);
        self.router.add_route(route)
    }

    /// Express-style app.delete() method
    #[pyo3(signature = (path, handler, **_kwargs))]
    pub fn delete(&mut self, path: &str, handler: PyObject, _kwargs: Option<std::collections::HashMap<String, PyObject>>) -> PyResult<()> {
        let route = Route::new(path, handler, "DELETE".to_string(), None);
        self.router.add_route(route)
    }

    /// Express-style app.patch() method
    #[pyo3(signature = (path, handler, **_kwargs))]
    pub fn patch(&mut self, path: &str, handler: PyObject, _kwargs: Option<std::collections::HashMap<String, PyObject>>) -> PyResult<()> {
        let route = Route::new(path, handler, "PATCH".to_string(), None);
        self.router.add_route(route)
    }

    /// Express-style app.head() method
    #[pyo3(signature = (path, handler, **_kwargs))]
    pub fn head(&mut self, path: &str, handler: PyObject, _kwargs: Option<std::collections::HashMap<String, PyObject>>) -> PyResult<()> {
        let route = Route::new(path, handler, "HEAD".to_string(), None);
        self.router.add_route(route)
    }

    /// Express-style app.options() method
    #[pyo3(signature = (path, handler, **_kwargs))]
    pub fn options(&mut self, path: &str, handler: PyObject, _kwargs: Option<std::collections::HashMap<String, PyObject>>) -> PyResult<()> {
        let route = Route::new(path, handler, "OPTIONS".to_string(), None);
        self.router.add_route(route)
    }

    /// Express-style app.all() method - matches all HTTP methods
    #[pyo3(signature = (path, handler, **_kwargs))]
    pub fn all(&mut self, path: &str, handler: PyObject, _kwargs: Option<std::collections::HashMap<String, PyObject>>) -> PyResult<()> {
        let methods = vec!["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"];
        Python::with_gil(|py| {
            for method in methods {
                let route = Route::new(path, handler.clone_ref(py), method.to_string(), None);
                self.router.add_route(route)?;
            }
            Ok(())
        })
    }

    /// Express-style app.use() method for middleware
    #[pyo3(signature = (middleware_or_path, middleware = None))]
    pub fn use_(&mut self, middleware_or_path: PyObject, middleware: Option<PyObject>) -> PyResult<()> {
        Python::with_gil(|py| {
            if let Some(middleware_fn) = middleware {
                // app.use('/path', middleware)
                let path = middleware_or_path.extract::<String>(py)?;
                let middleware_obj = Middleware::new(middleware_fn, "custom".to_string(), Some(path));
                self.router.use_middleware(middleware_obj)
            } else {
                // app.use(middleware) - global middleware
                let middleware_obj = Middleware::new(middleware_or_path, "custom".to_string(), None);
                self.router.use_middleware(middleware_obj)
            }
        })
    }

    /// Express-style app.set() method for application settings
    pub fn set(&mut self, name: &str, value: PyObject) -> PyResult<()> {
        self.settings.insert(name.to_string(), value);
        Ok(())
    }

    /// Express-style app.get() method for application settings (overloaded)
    pub fn get_setting(&self, name: &str) -> PyResult<Option<PyObject>> {
        Ok(self.settings.get(name).map(|v| Python::with_gil(|py| v.clone_ref(py))))
    }

    /// Express-style app.enable() method
    pub fn enable(&mut self, name: &str) -> PyResult<()> {
        Python::with_gil(|py| {
            self.settings.insert(name.to_string(), pyo3::types::PyBool::new(py, true).to_owned().into());
            Ok(())
        })
    }

    /// Express-style app.disable() method
    pub fn disable(&mut self, name: &str) -> PyResult<()> {
        Python::with_gil(|py| {
            self.settings.insert(name.to_string(), pyo3::types::PyBool::new(py, false).to_owned().into());
            Ok(())
        })
    }

    /// Express-style app.enabled() method
    pub fn enabled(&self, name: &str) -> PyResult<bool> {
        Python::with_gil(|py| {
            match self.settings.get(name) {
                Some(value) => value.extract::<bool>(py).or(Ok(false)),
                None => Ok(false)
            }
        })
    }

    /// Express-style app.disabled() method
    pub fn disabled(&self, name: &str) -> PyResult<bool> {
        Ok(!self.enabled(name)?)
    }

    /// Mount a sub-application or router
    pub fn mount(&mut self, path: &str, sub_router: Router) -> PyResult<()> {
        // Copy routes from sub-router with path prefix
        for route in sub_router.iter() {
            let full_path = if path == "/" { 
                route.path.clone() 
            } else { 
                format!("{}{}", path.trim_end_matches('/'), &route.path) 
            };
            
            let new_route = Python::with_gil(|py| {
                Route::new(&full_path, route.function.clone_ref(py), route.method.clone(), route.doc.clone())
            });
            self.router.add_route(new_route)?;
        }
        Ok(())
    }

    /// Get the underlying router
    pub fn get_router(&self) -> Router {
        self.router.clone()
    }

    /// Set custom error handler
    pub fn error_handler(&mut self, handler: PyObject) -> PyResult<()> {
        let error_middleware = Middleware::new(handler, "error_handler".to_string(), None);
        self.router.use_error_middleware(error_middleware)
    }

    /// Express-style app.listen() equivalent
    pub fn listen(&mut self, host: &str, port: u16) -> PyResult<String> {
        Ok(format!("Application configured to listen on {}:{}", host, port))
    }

    fn __str__(&self) -> PyResult<String> {
        Ok(format!("Application(routes={})", self.router.routes_count()))
    }

    fn __repr__(&self) -> PyResult<String> {
        Ok(format!("Application(routes={}, middleware={}, settings={})", 
                  self.router.routes_count(), 
                  self.middleware.len(),
                  self.settings.len()))
    }
}

impl Default for Application {
    fn default() -> Self {
        Self::new()
    }
}