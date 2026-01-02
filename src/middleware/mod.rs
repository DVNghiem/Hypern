//! Middleware system for Hypern framework.
//! 
//! This module provides two middleware systems:
//! 
//! 1. **Pure Rust Middleware** (recommended for performance):
//!    - Zero Python/GIL overhead
//!    - Runs entirely in Rust async runtime
//!    - Use `RustMiddleware` trait and built-in middleware from `builtin` module
//! 
//! 2. **Python-compatible Middleware** (for flexibility):
//!    - Allows Python functions as middleware
//!    - Has GIL overhead but provides Python interoperability
//!    - Use `Middleware` struct with Python callables

use pyo3::prelude::*;

pub mod builtin;
pub mod chain;

// Re-export pure Rust middleware types
pub use chain::{
    HttpMethod,
    MiddlewareChainBuilder,
    MiddlewareContext,
    MiddlewareError,
    MiddlewareResponse,
    MiddlewareResult,
    MiddlewareState,
    RustMiddleware,
    RustMiddlewareChain,
    StateValue,
    BoxedMiddleware,
};

// Re-export built-in middleware
pub use builtin::{
    BasicAuthMiddleware,
    CompressionMiddleware,
    CorsConfig,
    CorsMiddleware,
    LogConfig,
    LogLevel,
    LogMiddleware,
    LogAfterMiddleware,
    MethodMiddleware,
    PathMiddleware,
    RateLimitAlgorithm,
    RateLimitConfig,
    RateLimitMiddleware,
    RequestIdMiddleware,
    SecurityHeadersConfig,
    SecurityHeadersMiddleware,
    TimeoutMiddleware,
};

// ============================================================================
// Python-compatible Middleware (legacy, has GIL overhead)
// ============================================================================

/// Middleware function type - takes request/response and can modify them.
/// 
/// **Note**: This middleware type calls Python functions and has GIL overhead.
/// For maximum performance, use the pure Rust middleware system instead.
#[pyclass]
pub struct Middleware {
    #[pyo3(get, set)]
    pub function: Py<PyAny>,

    #[pyo3(get, set)]
    pub name: String,

    #[pyo3(get, set)]
    pub path: Option<String>, // If None, applies to all routes
}

impl Clone for Middleware {
    fn clone(&self) -> Self {
        Python::attach(|py| Self {
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
    pub fn new(function: Py<PyAny>, name: String, path: Option<String>) -> Self {
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
        Ok(format!(
            "Middleware(name='{}', path={:?})",
            self.name, self.path
        ))
    }
}

/// Collection of Python-compatible middleware organized by execution order.
/// 
/// **Note**: For pure Rust middleware, use `RustMiddlewareChain` instead.
#[derive(Clone, Default)]
pub struct MiddlewareChain {
    pub before: Vec<Middleware>, // Executed before route handler
    pub after: Vec<Middleware>,  // Executed after route handler
    pub error: Vec<Middleware>,  // Executed on error
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
