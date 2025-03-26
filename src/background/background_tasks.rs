use super::background_task::BackgroundTask;
use pyo3::prelude::*;
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use tokio::task::JoinHandle;
use crate::instants::get_runtime;
use crate::runtime::asyncio::asyncio;
use crate::runtime::future::RuntimeWrapper;

#[pyclass]
struct TaskResult {
    #[pyo3(get)]
    success: bool,
    #[pyo3(get)]
    result: Option<PyObject>,
    #[pyo3(get)]
    error: Option<String>,
}

#[pyclass]
pub struct BackgroundTasks {
    tasks: Arc<Mutex<HashMap<String, BackgroundTask>>>,
    running_tasks: Arc<Mutex<HashMap<String, JoinHandle<TaskResult>>>>,
}

#[pymethods]
impl BackgroundTasks {
    #[new]
    fn new() -> Self {
        BackgroundTasks {
            tasks: Arc::new(Mutex::new(HashMap::new())),
            running_tasks: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    fn add_task(&self, task: BackgroundTask) -> PyResult<String> {
        let task_id = task.get_id();
        let mut tasks = self.tasks.lock().unwrap();
        tasks.insert(task_id.clone(), task);
        Ok(task_id)
    }

    fn cancel_task(&self, task_id: &str) -> PyResult<bool> {
        // Try to cancel running task first
        if let Some(handle) = self.running_tasks.lock().unwrap().remove(task_id) {
            handle.abort();
            return Ok(true);
        }

        // If not running, remove from pending tasks
        let mut tasks = self.tasks.lock().unwrap();
        if let Some(task) = tasks.remove(task_id) {
            task.cancel()?;
            Ok(true)
        } else {
            Ok(false)
        }
    }

    fn execute_all(&self) -> PyResult<()> {
        let tasks = Arc::clone(&self.tasks);
        let running_tasks = Arc::clone(&self.running_tasks);

        let runtime = get_runtime();

        // Move tasks to running_tasks and spawn them
        let mut tasks_lock = tasks.lock().unwrap();
        let mut running_tasks_lock = running_tasks.lock().unwrap();

        for (task_id, task) in tasks_lock.drain() {
            let handle = runtime.spawn(async move {
                Python::with_gil(|py| match task.execute(py, runtime) {
                    Ok(result) => TaskResult {
                        success: true,
                        result: Some(result),
                        error: None,
                    },
                    Err(err) => TaskResult {
                        success: false,
                        result: None,
                        error: Some(err.to_string()),
                    },
                })
            });
            running_tasks_lock.insert(task_id, handle);
        }

        Ok(())
    }

    fn execute_task(&self, task_id: &str) -> PyResult<()> {
        let mut tasks = self.tasks.lock().unwrap();
        if let Some(task) = tasks.remove(task_id) {
            let runtime = get_runtime();
            let running_tasks = Arc::clone(&self.running_tasks);

            let handle = runtime.spawn(async move {
                Python::with_gil(|py| match task.execute(py, runtime) {
                    Ok(result) => TaskResult {
                        success: true,
                        result: Some(result),
                        error: None,
                    },
                    Err(err) => TaskResult {
                        success: false,
                        result: None,
                        error: Some(err.to_string()),
                    },
                })
            });

            running_tasks
                .lock()
                .unwrap()
                .insert(task_id.to_string(), handle);
            Ok(())
        } else {
            Ok(())
        }
    }

    fn get_task_result(&self, task_id: &str) -> PyResult<Option<TaskResult>> {
        let mut running_tasks = self.running_tasks.lock().unwrap();
        let runtime = get_runtime();

        if let Some(handle) = running_tasks.remove(task_id) {
            if handle.is_finished() {
                // Task completed, get result
                match runtime.block_on(handle) {
                    Ok(result) => Ok(Some(result)),
                    Err(_) => Ok(Some(TaskResult {
                        success: false,
                        result: None,
                        error: Some("Task was cancelled".to_string()),
                    })),
                }
            } else {
                // Task still running, put it back
                running_tasks.insert(task_id.to_string(), handle);
                Ok(None)
            }
        } else {
            Ok(None)
        }
    }

    fn is_task_complete(&self, task_id: &str) -> PyResult<bool> {
        let running_tasks = self.running_tasks.lock().unwrap();
        if let Some(handle) = running_tasks.get(task_id) {
            Ok(handle.is_finished())
        } else {
            Ok(false)
        }
    }
}
