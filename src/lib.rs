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

// Core performance modules
pub mod core;
pub mod database;
pub mod fast_path;
pub mod http;
pub mod memory;
pub mod middleware;
pub mod realtime;
pub mod routing;
pub mod utils;

// Re-exports for backward compatibility
pub use crate::core::server::Server;
pub use crate::http::headers::HeaderMap;
pub use crate::http::multipart::{FormData, UploadedFile};
pub use crate::http::request::Request;
pub use crate::http::response::{Response, ResponseSlot};
pub use crate::routing::cache::RouteCache;
pub use crate::routing::route::Route;
pub use crate::routing::router::Router;

pub use crate::core::context::{Context, DIContainer};

pub use crate::core::tasks::{TaskExecutor, TaskResult, TaskStatus};

pub use crate::http::streaming::{SSEEvent, SSEGenerator, SSEStream, StreamingResponse};

// Realtime exports
pub use crate::realtime::broadcast::{
    BackpressurePolicy, BroadcastConfig, BroadcastStats, BroadcastSubscriber, RealtimeBroadcast,
};
pub use crate::realtime::channel::{ChannelManager, ChannelStats, Subscriber, TopicMatcher};
pub use crate::realtime::heartbeat::{HeartbeatConfig, HeartbeatMonitor, HeartbeatStats};
pub use crate::realtime::presence::{PresenceDiff, PresenceInfo, PresenceTracker};
pub use crate::core::reload::{PyHealthCheck, PyReloadConfig, PyReloadManager};

pub use crate::middleware::{
    PyBasicAuthMiddleware, PyCompressionMiddleware, PyCorsMiddleware, PyLogMiddleware,
    PyRateLimitMiddleware, PyRequestIdMiddleware, PySecurityHeadersMiddleware, PyTimeoutMiddleware,
};

// Database exports
pub use crate::database::{
    finalize_db, finalize_db_all, get_db, ConnectionPool, DbSession, PoolConfig, PoolStatus,
    RowStream,
};

// Re-exports for internal use
pub use fast_path::json_cache::JsonResponseCache;
pub use fast_path::static_files::StaticFileHandler;
pub use memory::pool::{RequestPool, ResponsePool};

#[pymodule(gil_used = false)]
fn _hypern(_py: Python, module: &Bound<PyModule>) -> PyResult<()> {
    // Original classes (backwards compatible)
    module.add_class::<Server>()?;
    module.add_class::<Route>()?;
    module.add_class::<Router>()?;
    module.add_class::<Response>()?;

    // Request handling
    module.add_class::<Request>()?;
    module.add_class::<HeaderMap>()?;

    // File uploads
    module.add_class::<FormData>()?;
    module.add_class::<UploadedFile>()?;

    // Dependency Injection
    module.add_class::<Context>()?;
    module.add_class::<DIContainer>()?;

    // Background Tasks
    module.add_class::<TaskExecutor>()?;
    module.add_class::<TaskResult>()?;
    module.add_class::<TaskStatus>()?;

    // Streaming/SSE
    module.add_class::<SSEEvent>()?;
    module.add_class::<SSEStream>()?;
    module.add_class::<SSEGenerator>()?;
    module.add_class::<StreamingResponse>()?;

    // Realtime: Channel/Topic
    module.add_class::<ChannelManager>()?;
    module.add_class::<ChannelStats>()?;
    module.add_class::<Subscriber>()?;
    module.add_class::<TopicMatcher>()?;

    // Realtime: Presence
    module.add_class::<PresenceTracker>()?;
    module.add_class::<PresenceInfo>()?;
    module.add_class::<PresenceDiff>()?;

    // Realtime: Broadcast
    module.add_class::<RealtimeBroadcast>()?;
    module.add_class::<BroadcastConfig>()?;
    module.add_class::<BroadcastStats>()?;
    module.add_class::<BroadcastSubscriber>()?;
    module.add_class::<BackpressurePolicy>()?;

    // Realtime: Heartbeat
    module.add_class::<HeartbeatMonitor>()?;
    module.add_class::<HeartbeatConfig>()?;
    module.add_class::<HeartbeatStats>()?;

    // Reload / Health
    module.add_class::<PyHealthCheck>()?;
    module.add_class::<PyReloadConfig>()?;
    module.add_class::<PyReloadManager>()?;

    // Rust Middleware
    module.add_class::<PyCorsMiddleware>()?;
    module.add_class::<PyRateLimitMiddleware>()?;
    module.add_class::<PySecurityHeadersMiddleware>()?;
    module.add_class::<PyTimeoutMiddleware>()?;
    module.add_class::<PyCompressionMiddleware>()?;
    module.add_class::<PyRequestIdMiddleware>()?;
    module.add_class::<PyLogMiddleware>()?;
    module.add_class::<PyBasicAuthMiddleware>()?;

    // Database
    module.add_class::<ConnectionPool>()?;
    module.add_class::<PoolConfig>()?;
    module.add_class::<PoolStatus>()?;
    module.add_class::<DbSession>()?;
    module.add_class::<RowStream>()?;
    module.add_function(wrap_pyfunction!(get_db, module)?)?;
    module.add_function(wrap_pyfunction!(finalize_db, module)?)?;
    module.add_function(wrap_pyfunction!(finalize_db_all, module)?)?;

    Ok(())
}
