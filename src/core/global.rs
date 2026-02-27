use pyo3::prelude::*;
use std::sync::{Arc, OnceLock};
use tokio::sync::Semaphore;

use crate::{
    memory::pool::{RequestPool, ResponsePool},
    runtime::{init_runtime_mt, RuntimeWrapper},
    utils::cpu::num_cpus,
};

static ASYNCIO: OnceLock<Py<PyModule>> = OnceLock::new();
static EV_LOOP: OnceLock<Py<PyAny>> = OnceLock::new();
static BUILTINS: OnceLock<Py<PyModule>> = OnceLock::new();
// Share single multi-threaded runtime
static SHARED_RUNTIME: OnceLock<tokio::runtime::Runtime> = OnceLock::new();
static CONN_SEMAPHORE: OnceLock<Arc<Semaphore>> = OnceLock::new();
static RUNTIME: OnceLock<Arc<RuntimeWrapper>> = OnceLock::new();

// Global memory pools for request/response buffer reuse
static REQUEST_POOL: OnceLock<Arc<RequestPool>> = OnceLock::new();
static RESPONSE_POOL: OnceLock<Arc<ResponsePool>> = OnceLock::new();

pub fn get_asyncio(py: Python<'_>) -> &Py<PyModule> {
    ASYNCIO.get_or_init(|| py.import("asyncio").unwrap().into())
}

pub fn get_builtins(py: Python<'_>) -> &Py<PyModule> {
    BUILTINS.get_or_init(|| py.import("builtins").unwrap().into())
}

pub fn get_event_loop(py: Python<'_>) -> &Py<PyAny> {
    EV_LOOP.get_or_init(|| {
        let asyncio = get_asyncio(py).bind(py);
        // Python 3.12+ raises RuntimeError from get_event_loop() when no
        // current event loop exists.  Fall back to creating a new one.
        match asyncio.call_method0("get_event_loop") {
            Ok(loop_obj) => loop_obj.into(),
            Err(_) => {
                let new_loop = asyncio
                    .call_method0("new_event_loop")
                    .expect("Failed to create new event loop");
                asyncio
                    .call_method1("set_event_loop", (&new_loop,))
                    .expect("Failed to set event loop");
                new_loop.into()
            }
        }
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

/// Get the global request buffer pool for zero-allocation request parsing.
/// Pool is initialized with sensible defaults on first access.
pub fn get_request_pool() -> Arc<RequestPool> {
    REQUEST_POOL
        .get_or_init(|| {
            let pool = RequestPool::new(
                2048,  // max_size: 2K pooled buffers
                16384, // buffer_capacity: 16KB each
            );
            // Warm up the pool with some pre-allocated buffers
            pool.buffers.warm(256);
            Arc::new(pool)
        })
        .clone()
}

/// Get the global response buffer pool for zero-allocation response building.
/// Pool is initialized with sensible defaults on first access.
pub fn get_response_pool() -> Arc<ResponsePool> {
    RESPONSE_POOL
        .get_or_init(|| {
            let pool = ResponsePool::new(
                2048, // max_size: 2K pooled buffers
                8192, // buffer_capacity: 8KB each
            );
            // Warm up the pool
            pool.buffers.warm(256);
            pool.header_buffers.warm(256);
            Arc::new(pool)
        })
        .clone()
}

/// Initialize memory pools with custom sizes.
/// Call this during application startup for optimal performance.
pub fn init_memory_pools(
    request_pool_size: usize,
    request_buffer_capacity: usize,
    response_pool_size: usize,
    response_buffer_capacity: usize,
) {
    // Request pool
    let _ = REQUEST_POOL.get_or_init(|| {
        let pool = RequestPool::new(request_pool_size, request_buffer_capacity);
        pool.buffers.warm(request_pool_size / 4);
        Arc::new(pool)
    });

    // Response pool
    let _ = RESPONSE_POOL.get_or_init(|| {
        let pool = ResponsePool::new(response_pool_size, response_buffer_capacity);
        pool.buffers.warm(response_pool_size / 4);
        pool.header_buffers.warm(response_pool_size / 4);
        Arc::new(pool)
    });
}
