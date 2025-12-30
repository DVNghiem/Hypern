use pyo3::prelude::*;
use tokio::sync::Semaphore;
use std::sync::{Arc, OnceLock};

use crate::utils::cpu::num_cpus;

static ASYNCIO: OnceLock<Py<PyModule>> = OnceLock::new();
static EV_LOOP: OnceLock<Py<PyAny>> = OnceLock::new();
// Share single multi-threaded runtime
static SHARED_RUNTIME: OnceLock<tokio::runtime::Runtime> = OnceLock::new();
static CONN_SEMAPHORE: OnceLock<Arc<Semaphore>> = OnceLock::new();

#[derive(Clone)]
// An Executor that uses the tokio runtime.
pub struct TokioExecutor;

// Implement the `hyper::rt::Executor` trait for `TokioExecutor` so that it can be used to scan
// tasks in the hyper runtime.
impl<F> hyper::rt::Executor<F> for TokioExecutor
where
    F: std::future::Future + Send + 'static,
    F::Output: Send + 'static,
{
    fn execute(&self, fut: F) {
        tokio::task::spawn(fut);
    }
}

pub fn get_asyncio(py: Python<'_>) -> &Py<PyModule> {
    ASYNCIO.get_or_init(|| py.import("asyncio").unwrap().into())
}

pub fn get_event_loop(py: Python<'_>) -> &Py<PyAny> {
    EV_LOOP.get_or_init(|| {
        let asyncio = get_asyncio(py).bind(py);
        asyncio
            .call_method0("get_event_loop")
            .expect("Failed to get event loop")
            .into()
    })
}

pub fn get_runtime() -> &'static tokio::runtime::Runtime {
    SHARED_RUNTIME.get_or_init(|| {
        tokio::runtime::Builder::new_multi_thread()
            .worker_threads(num_cpus(1))
            .enable_all()
            .build()
            .unwrap()
    })
}

pub fn get_connection_semaphore(max_connections: usize) -> Arc<Semaphore> {
    CONN_SEMAPHORE
        .get_or_init(|| Arc::new(Semaphore::new(max_connections)))
        .clone()
}
