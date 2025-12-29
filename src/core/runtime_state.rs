use pyo3_async_runtimes::TaskLocals;
use std::sync::OnceLock;

static TASK_LOCALS: OnceLock<TaskLocals> = OnceLock::new();

pub fn set_task_locals(locals: TaskLocals) -> Result<(), TaskLocals> {
    TASK_LOCALS.set(locals)
}

pub fn get_task_locals() -> Option<&'static TaskLocals> {
    TASK_LOCALS.get()
}
