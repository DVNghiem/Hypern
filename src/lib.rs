#[cfg(not(any(
    target_env = "musl",
    target_os = "freebsd",
    target_os = "openbsd",
    target_os = "windows",
    feature = "mimalloc"
)))]
#[global_allocator]
static GLOBAL: tikv_jemallocator::Jemalloc = tikv_jemallocator::Jemalloc;

#[cfg(feature = "mimalloc")]
#[global_allocator]
static GLOBAL: mimalloc::MiMalloc = mimalloc::MiMalloc;

use pyo3::prelude::*;

// Helper modules (internal)
pub use crate::core::runtime;
pub use crate::core::socket;
pub use crate::http::body;
pub use crate::http::errors;

// Core performance modules
pub mod core;
pub mod fast_path;
pub mod http;
pub mod memory;
pub mod metrics;
pub mod middleware;
pub mod python;
pub mod routing;
pub mod utils;

// Re-exports for backward compatibility

pub use crate::core::server::Server;
pub use crate::http::headers::{FastHeaders, HypernHeaders};
pub use crate::http::request::{FastRequest, Request};
pub use crate::http::response::{Response, ResponseSlot, ResponseWriter};
pub use crate::middleware::Middleware;
pub use crate::routing::cache::RouteCache;
pub use crate::routing::route::Route;
pub use crate::routing::router::Router;

// Re-exports for internal use
pub use fast_path::json_cache::JsonResponseCache;
pub use fast_path::static_files::StaticFileHandler;
pub use memory::pool::{RequestPool, ResponsePool};
pub use metrics::collector::ServerMetrics;

#[pymodule(gil_used = false)]
fn hypern(_py: Python, module: &Bound<PyModule>) -> PyResult<()> {
    // Original classes (backwards compatible)
    module.add_class::<Server>()?;
    module.add_class::<Route>()?;
    module.add_class::<Router>()?;
    module.add_class::<Middleware>()?;

    module.add_class::<Response>()?;
    module.add_class::<ResponseWriter>()?;
    module.add_class::<Request>()?;
    module.add_class::<HypernHeaders>()?;
    module.add_class::<socket::SocketHeld>()?;
    module.add_class::<errors::HypernError>()?;
    module.add_class::<errors::DefaultErrorHandler>()?;
    module.add_class::<errors::ErrorContext>()?;
    module.add_class::<errors::ErrorContext>()?;

    // New performance classes
    module.add_class::<FastRequest>()?;
    module.add_class::<FastHeaders>()?;

    Ok(())
}
