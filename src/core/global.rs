use pyo3::prelude::*;
use std::sync::{Arc, OnceLock};
use tokio::sync::Semaphore;

use crate::{
    runtime::{init_runtime_mt, RuntimeWrapper},
    utils::cpu::num_cpus,
};

static ASYNCIO: OnceLock<Py<PyModule>> = OnceLock::new();
static EV_LOOP: OnceLock<Py<PyAny>> = OnceLock::new();
// Share single multi-threaded runtime
static SHARED_RUNTIME: OnceLock<tokio::runtime::Runtime> = OnceLock::new();
static CONN_SEMAPHORE: OnceLock<Arc<Semaphore>> = OnceLock::new();
static RUNTIME: OnceLock<Arc<RuntimeWrapper>> = OnceLock::new();

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

pub fn set_global_runtime(
    threads: usize,
    blocking_threads: usize,
    py_threads: usize,
    py_threads_idle_timeout: u64,
    py_loop: Arc<Py<PyAny>>,
) {
    let wrapper = init_runtime_mt(
        threads,
        blocking_threads,
        py_threads,
        py_threads_idle_timeout,
        py_loop,
    );
    RUNTIME
        .set(Arc::new(wrapper))
        .expect("Global runtime already set");
}

pub(crate) fn get_global_runtime() -> Arc<RuntimeWrapper> {
    RUNTIME
        .get()
        .expect("Global runtime not initialized")
        .clone()
}
