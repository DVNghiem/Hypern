#![allow(dead_code)]
//! gRPC server support — bridges Python handlers via tonic.
//!
//! Provides a `GrpcServer` pyclass that can be started on a separate port
//! and routes incoming gRPC unary calls to Python handler functions.

use pyo3::prelude::*;
use std::sync::OnceLock;

static GRPC_RT: OnceLock<tokio::runtime::Runtime> = OnceLock::new();

fn grpc_runtime() -> &'static tokio::runtime::Runtime {
    GRPC_RT.get_or_init(|| {
        tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
            .enable_all()
            .build()
            .expect("failed to create gRPC runtime")
    })
}

/// Configuration for a gRPC server.
#[pyclass(from_py_object)]
#[derive(Clone)]
pub struct GrpcConfig {
    /// Host to bind (default: "0.0.0.0")
    #[pyo3(get, set)]
    pub host: String,
    /// Port to bind (default: 50051)
    #[pyo3(get, set)]
    pub port: u16,
}

#[pymethods]
impl GrpcConfig {
    #[new]
    #[pyo3(signature = (host = "0.0.0.0".to_string(), port = 50051))]
    pub fn new(host: String, port: u16) -> Self {
        Self { host, port }
    }

    fn __repr__(&self) -> String {
        format!("GrpcConfig(host='{}', port={})", self.host, self.port)
    }
}

/// A gRPC server that routes unary calls to Python handlers.
///
/// The server is started on a background thread and listens on the configured
/// address. This is a thin wrapper — the actual gRPC service routing is handled
/// at the Python level via ``hypern.grpc.GrpcRoute``.
#[pyclass]
pub struct GrpcServer {
    config: GrpcConfig,
    running: std::sync::atomic::AtomicBool,
}

#[pymethods]
impl GrpcServer {
    #[new]
    #[pyo3(signature = (config = None))]
    pub fn new(config: Option<GrpcConfig>) -> Self {
        Self {
            config: config.unwrap_or_else(|| GrpcConfig::new("0.0.0.0".to_string(), 50051)),
            running: std::sync::atomic::AtomicBool::new(false),
        }
    }

    /// Get the configured address string.
    pub fn address(&self) -> String {
        format!("{}:{}", self.config.host, self.config.port)
    }

    /// Check if the server is running.
    pub fn is_running(&self) -> bool {
        self.running.load(std::sync::atomic::Ordering::Relaxed)
    }

    fn __repr__(&self) -> String {
        format!(
            "GrpcServer(address='{}', running={})",
            self.address(),
            self.is_running()
        )
    }
}
