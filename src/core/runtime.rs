use pyo3::prelude::*;
use pyo3_async_runtimes::TaskLocals;
use std::sync::OnceLock;

use crate::utils::cpu::num_cpus;

static TASK_LOCALS: OnceLock<TaskLocals> = OnceLock::new();
static ASYNCIO: OnceLock<Py<PyModule>> = OnceLock::new();
// Share single multi-threaded runtime
static SHARED_RUNTIME: OnceLock<tokio::runtime::Runtime> = OnceLock::new();


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

pub fn set_task_locals(locals: TaskLocals) -> Result<(), TaskLocals> {
    TASK_LOCALS.set(locals)
}

pub fn get_task_locals() -> Option<&'static TaskLocals> {
    TASK_LOCALS.get()
}

pub fn get_asyncio(py: Python<'_>) -> &Py<PyModule> {
    ASYNCIO.get_or_init(|| py.import("asyncio").unwrap().into())
}


fn get_runtime() -> &'static tokio::runtime::Runtime {
    SHARED_RUNTIME.get_or_init(|| {
        tokio::runtime::Builder::new_multi_thread()
            .worker_threads(num_cpus(1))
            .enable_all()
            .build()
            .unwrap()
    })
}