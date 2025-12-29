use pyo3::{create_exception, exceptions::PyRuntimeError};

use pyo3::prelude::*;
use pyo3::types::PyType;
use std::fmt;

create_exception!(hypern, RequestError, PyRuntimeError);
create_exception!(hypern, RequestClosed, PyRuntimeError);

macro_rules! error_request {
    () => {
        Err(crate::http::errors::RequestError::new_err("Request protocol error").into())
    };
}

macro_rules! error_stream {
    () => {
        Err(crate::http::errors::RequestClosed::new_err("Request transport is closed").into())
    };
}

pub(crate) use error_request;
pub(crate) use error_stream;

/// Custom error types for the framework
#[pyclass]
#[derive(Debug, Clone)]
pub struct HypernError {
    message: String,
    status_code: u16,
    error_type: ErrorType,
}

#[derive(Debug, Clone)]
pub enum ErrorType {
    BadRequest,
    Unauthorized,
    Forbidden,
    NotFound,
    MethodNotAllowed,
    InternalServerError,
    BadGateway,
    ServiceUnavailable,
    Custom(String),
}

impl ErrorType {
    pub fn status_code(&self) -> u16 {
        match self {
            ErrorType::BadRequest => 400,
            ErrorType::Unauthorized => 401,
            ErrorType::Forbidden => 403,
            ErrorType::NotFound => 404,
            ErrorType::MethodNotAllowed => 405,
            ErrorType::InternalServerError => 500,
            ErrorType::BadGateway => 502,
            ErrorType::ServiceUnavailable => 503,
            ErrorType::Custom(_) => 500,
        }
    }

    pub fn error_name(&self) -> &str {
        match self {
            ErrorType::BadRequest => "BadRequest",
            ErrorType::Unauthorized => "Unauthorized",
            ErrorType::Forbidden => "Forbidden",
            ErrorType::NotFound => "NotFound",
            ErrorType::MethodNotAllowed => "MethodNotAllowed",
            ErrorType::InternalServerError => "InternalServerError",
            ErrorType::BadGateway => "BadGateway",
            ErrorType::ServiceUnavailable => "ServiceUnavailable",
            ErrorType::Custom(name) => name,
        }
    }
}

#[pymethods]
impl HypernError {
    #[new]
    #[pyo3(signature = (message, status_code = None, error_type = None))]
    pub fn new(message: String, status_code: Option<u16>, error_type: Option<String>) -> Self {
        let error_type = match error_type.as_deref() {
            Some("BadRequest") => ErrorType::BadRequest,
            Some("Unauthorized") => ErrorType::Unauthorized,
            Some("Forbidden") => ErrorType::Forbidden,
            Some("NotFound") => ErrorType::NotFound,
            Some("MethodNotAllowed") => ErrorType::MethodNotAllowed,
            Some("InternalServerError") => ErrorType::InternalServerError,
            Some("BadGateway") => ErrorType::BadGateway,
            Some("ServiceUnavailable") => ErrorType::ServiceUnavailable,
            Some(custom) => ErrorType::Custom(custom.to_string()),
            None => ErrorType::InternalServerError,
        };

        let status_code = status_code.unwrap_or_else(|| error_type.status_code());

        Self {
            message,
            status_code,
            error_type,
        }
    }

    /// Create a 400 Bad Request error
    #[classmethod]
    pub fn bad_request(_cls: &Bound<PyType>, message: String) -> Self {
        Self {
            message,
            status_code: 400,
            error_type: ErrorType::BadRequest,
        }
    }

    /// Create a 401 Unauthorized error
    #[classmethod]
    pub fn unauthorized(_cls: &Bound<PyType>, message: String) -> Self {
        Self {
            message,
            status_code: 401,
            error_type: ErrorType::Unauthorized,
        }
    }

    /// Create a 403 Forbidden error
    #[classmethod]
    pub fn forbidden(_cls: &Bound<PyType>, message: String) -> Self {
        Self {
            message,
            status_code: 403,
            error_type: ErrorType::Forbidden,
        }
    }

    /// Create a 404 Not Found error
    #[classmethod]
    pub fn not_found(_cls: &Bound<PyType>, message: String) -> Self {
        Self {
            message,
            status_code: 404,
            error_type: ErrorType::NotFound,
        }
    }

    /// Create a 500 Internal Server Error
    #[classmethod]
    pub fn internal_server_error(_cls: &Bound<PyType>, message: String) -> Self {
        Self {
            message,
            status_code: 500,
            error_type: ErrorType::InternalServerError,
        }
    }

    #[getter]
    pub fn message(&self) -> &str {
        &self.message
    }

    #[getter]
    pub fn status_code(&self) -> u16 {
        self.status_code
    }

    #[getter]
    pub fn error_type(&self) -> &str {
        self.error_type.error_name()
    }

    fn __str__(&self) -> String {
        format!(
            "{}: {} ({})",
            self.error_type.error_name(),
            self.message,
            self.status_code
        )
    }

    fn __repr__(&self) -> String {
        format!(
            "HypernError('{}', {}, '{}')",
            self.message,
            self.status_code,
            self.error_type.error_name()
        )
    }
}

impl fmt::Display for HypernError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{}: {} ({})",
            self.error_type.error_name(),
            self.message,
            self.status_code
        )
    }
}

impl std::error::Error for HypernError {}

/// Default error handler that formats errors as JSON
#[pyclass]
pub struct DefaultErrorHandler;

#[pymethods]
impl DefaultErrorHandler {
    #[new]
    pub fn new() -> Self {
        Self
    }

    pub fn handle<'py>(&self, py: Python<'py>, error: &HypernError) -> PyResult<Bound<'py, PyAny>> {
        let error_dict = pyo3::types::PyDict::new(py);
        error_dict.set_item("error", error.error_type.error_name())?;
        error_dict.set_item("message", &error.message)?;
        error_dict.set_item("status_code", error.status_code)?;
        Ok(error_dict.into_any())
    }
}

impl Default for DefaultErrorHandler {
    fn default() -> Self {
        Self::new()
    }
}

/// Global error context for handling different types of errors
#[pyclass]
pub struct ErrorContext {
    handlers: std::collections::HashMap<String, Py<PyAny>>,
    default_handler: DefaultErrorHandler,
}

#[pymethods]
impl ErrorContext {
    #[new]
    pub fn new() -> Self {
        Self {
            handlers: std::collections::HashMap::new(),
            default_handler: DefaultErrorHandler::new(),
        }
    }

    /// Register a custom error handler for a specific error type
    pub fn register_handler(&mut self, error_type: String, handler: Py<PyAny>) -> PyResult<()> {
        self.handlers.insert(error_type, handler);
        Ok(())
    }

    /// Handle an error using the appropriate handler
    pub fn handle_error<'py>(
        &self,
        py: Python<'py>,
        error: &HypernError,
    ) -> PyResult<Bound<'py, PyAny>> {
        let error_type_name = error.error_type.error_name();

        if let Some(handler) = self.handlers.get(error_type_name) {
            handler.bind(py).call1((error.clone(),))
        } else {
            self.default_handler.handle(py, error)
        }
    }

    /// Get all registered error types
    pub fn get_registered_types(&self) -> Vec<String> {
        self.handlers.keys().cloned().collect()
    }
}

impl Default for ErrorContext {
    fn default() -> Self {
        Self::new()
    }
}

/// Macro to create different error types easily
#[macro_export]
macro_rules! hypern_error {
    ($error_type:ident, $message:expr) => {
        HypernError::new(
            $message.to_string(),
            None,
            Some(stringify!($error_type).to_string()),
        )
    };
    ($error_type:ident, $message:expr, $status:expr) => {
        HypernError::new(
            $message.to_string(),
            Some($status),
            Some(stringify!($error_type).to_string()),
        )
    };
}

// Convenience functions for common errors
pub fn bad_request(message: &str) -> HypernError {
    HypernError::new(
        message.to_string(),
        Some(400),
        Some("BadRequest".to_string()),
    )
}

pub fn unauthorized(message: &str) -> HypernError {
    HypernError::new(
        message.to_string(),
        Some(401),
        Some("Unauthorized".to_string()),
    )
}

pub fn forbidden(message: &str) -> HypernError {
    HypernError::new(
        message.to_string(),
        Some(403),
        Some("Forbidden".to_string()),
    )
}

pub fn not_found(message: &str) -> HypernError {
    HypernError::new(message.to_string(), Some(404), Some("NotFound".to_string()))
}

pub fn internal_server_error(message: &str) -> HypernError {
    HypernError::new(
        message.to_string(),
        Some(500),
        Some("InternalServerError".to_string()),
    )
}
