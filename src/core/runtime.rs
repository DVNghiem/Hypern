use pyo3_async_runtimes::TaskLocals;
use std::sync::OnceLock;

static TASK_LOCALS: OnceLock<TaskLocals> = OnceLock::new();

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
