use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use crossbeam_channel::{bounded, Receiver, Sender};
use dashmap::DashMap;
use pyo3::prelude::*;

/// Task status
#[pyclass(from_py_object)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TaskStatus {
    Pending,
    Running,
    Completed,
    Failed,
    Cancelled,
}

/// A background task result
#[pyclass(from_py_object)]
#[derive(Clone)]
pub struct TaskResult {
    #[pyo3(get)]
    pub task_id: String,
    #[pyo3(get)]
    pub status: TaskStatus,
    #[pyo3(get)]
    pub result: Option<String>,
    #[pyo3(get)]
    pub error: Option<String>,
    #[pyo3(get)]
    pub started_at: Option<f64>,
    #[pyo3(get)]
    pub completed_at: Option<f64>,
}

#[pymethods]
impl TaskResult {
    pub fn is_success(&self) -> bool {
        self.status == TaskStatus::Completed
    }

    pub fn is_failed(&self) -> bool {
        self.status == TaskStatus::Failed
    }

    pub fn is_pending(&self) -> bool {
        self.status == TaskStatus::Pending || self.status == TaskStatus::Running
    }
}

/// Internal task representation
struct BackgroundTask {
    id: String,
    handler: Py<PyAny>,
    args: Py<PyAny>,
    created_at: std::time::Instant,
    delay: Option<Duration>,
}

/// Background task executor
#[pyclass]
pub struct TaskExecutor {
    /// Task queue sender
    sender: Sender<BackgroundTask>,
    /// Task results storage
    results: Arc<DashMap<String, TaskResult>>,
    /// Running flag
    running: Arc<AtomicBool>,
    /// Task counter
    counter: AtomicU64,
}

impl TaskExecutor {
    /// Create a new task executor with the specified number of workers
    pub fn new(num_workers: usize, queue_size: usize) -> Self {
        let (sender, receiver) = bounded(queue_size);
        let results = Arc::new(DashMap::new());
        let running = Arc::new(AtomicBool::new(true));

        // Spawn worker threads
        for worker_id in 0..num_workers {
            let receiver = receiver.clone();
            let results = results.clone();
            let running = running.clone();

            std::thread::spawn(move || {
                task_worker(worker_id, receiver, results, running);
            });
        }

        Self {
            sender,
            results,
            running,
            counter: AtomicU64::new(0),
        }
    }

    /// Generate a unique task ID
    fn generate_id(&self) -> String {
        let count = self.counter.fetch_add(1, Ordering::SeqCst);
        let timestamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_millis();
        format!("task_{:016x}_{:08x}", timestamp, count)
    }
}

#[pymethods]
impl TaskExecutor {
    #[new]
    #[pyo3(signature = (num_workers=4, queue_size=1000))]
    pub fn py_new(num_workers: usize, queue_size: usize) -> Self {
        Self::new(num_workers, queue_size)
    }

    /// Submit a task for background execution
    #[pyo3(signature = (handler, args=None, delay_ms=None))]
    pub fn submit(
        &self,
        py: Python<'_>,
        handler: Py<PyAny>,
        args: Option<Py<PyAny>>,
        delay_ms: Option<u64>,
    ) -> PyResult<String> {
        let task_id = self.generate_id();

        let args = args.unwrap_or_else(|| py.None());

        let task = BackgroundTask {
            id: task_id.clone(),
            handler,
            args,
            created_at: std::time::Instant::now(),
            delay: delay_ms.map(Duration::from_millis),
        };

        // Initialize result as pending
        self.results.insert(
            task_id.clone(),
            TaskResult {
                task_id: task_id.clone(),
                status: TaskStatus::Pending,
                result: None,
                error: None,
                started_at: None,
                completed_at: None,
            },
        );

        // Send to queue
        self.sender.send(task).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to submit task: {}", e))
        })?;

        Ok(task_id)
    }

    /// Get task result by ID
    pub fn get_result(&self, task_id: &str) -> Option<TaskResult> {
        self.results.get(task_id).map(|r| r.value().clone())
    }

    /// Check if a task is complete
    pub fn is_complete(&self, task_id: &str) -> bool {
        self.results
            .get(task_id)
            .map(|r| {
                matches!(
                    r.status,
                    TaskStatus::Completed | TaskStatus::Failed | TaskStatus::Cancelled
                )
            })
            .unwrap_or(false)
    }

    /// Cancel a pending task
    pub fn cancel(&self, task_id: &str) -> bool {
        if let Some(mut result) = self.results.get_mut(task_id) {
            if result.status == TaskStatus::Pending {
                result.status = TaskStatus::Cancelled;
                return true;
            }
        }
        false
    }

    /// Get pending task count
    pub fn pending_count(&self) -> usize {
        self.results
            .iter()
            .filter(|r| r.status == TaskStatus::Pending || r.status == TaskStatus::Running)
            .count()
    }

    /// Get completed task count
    pub fn completed_count(&self) -> usize {
        self.results
            .iter()
            .filter(|r| r.status == TaskStatus::Completed)
            .count()
    }

    /// Clear completed results older than max_age seconds
    pub fn cleanup(&self, max_age_secs: u64) {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs_f64();
        let threshold = now - max_age_secs as f64;

        self.results.retain(|_, v| {
            if let Some(completed_at) = v.completed_at {
                completed_at > threshold
            } else {
                true
            }
        });
    }

    /// Shutdown the executor gracefully
    pub fn shutdown(&self) {
        self.running.store(false, Ordering::SeqCst);
    }
}

/// Worker function for processing background tasks
fn task_worker(
    worker_id: usize,
    receiver: Receiver<BackgroundTask>,
    results: Arc<DashMap<String, TaskResult>>,
    running: Arc<AtomicBool>,
) {
    crate::hlog_info!("Background task worker {} started", worker_id);

    while running.load(Ordering::SeqCst) {
        match receiver.recv_timeout(Duration::from_millis(100)) {
            Ok(task) => {
                // Check if task was cancelled
                if let Some(result) = results.get(&task.id) {
                    if result.status == TaskStatus::Cancelled {
                        continue;
                    }
                }

                // Handle delay if specified
                if let Some(delay) = task.delay {
                    let elapsed = task.created_at.elapsed();
                    if elapsed < delay {
                        std::thread::sleep(delay - elapsed);
                    }
                }

                // Update status to running
                let started_at = std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_secs_f64();

                if let Some(mut result) = results.get_mut(&task.id) {
                    result.status = TaskStatus::Running;
                    result.started_at = Some(started_at);
                }

                // Execute the task
                let execution_result = Python::attach(|py| {
                    let handler = task.handler.bind(py);
                    let args = task.args.bind(py);

                    // Check if it's a coroutine function
                    let asyncio = py.import("asyncio").ok();
                    let is_coro = asyncio
                        .as_ref()
                        .and_then(|m| m.call_method1("iscoroutinefunction", (handler,)).ok())
                        .map(|r| r.is_truthy().unwrap_or(false))
                        .unwrap_or(false);

                    if is_coro {
                        // Run async function
                        if let Some(ref asyncio_mod) = asyncio {
                            match handler.call1((args,)) {
                                Ok(coro) => asyncio_mod
                                    .call_method1("run", (coro,))
                                    .map(|r| r.to_string())
                                    .map_err(|e| e.to_string()),
                                Err(e) => Err(e.to_string()),
                            }
                        } else {
                            Err("asyncio not available".to_string())
                        }
                    } else {
                        // Run sync function
                        handler
                            .call1((args,))
                            .map(|r| r.to_string())
                            .map_err(|e| e.to_string())
                    }
                });

                // Update result
                let completed_at = std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_secs_f64();

                if let Some(mut result) = results.get_mut(&task.id) {
                    match execution_result {
                        Ok(res) => {
                            result.status = TaskStatus::Completed;
                            result.result = Some(res);
                        }
                        Err(err) => {
                            result.status = TaskStatus::Failed;
                            result.error = Some(err);
                        }
                    }
                    result.completed_at = Some(completed_at);
                }
            }
            Err(crossbeam_channel::RecvTimeoutError::Timeout) => continue,
            Err(crossbeam_channel::RecvTimeoutError::Disconnected) => break,
        }
    }

    crate::hlog_info!("Background task worker {} stopped", worker_id);
}

/// Async task runner for Tokio-based background tasks
pub struct AsyncTaskRunner {
    runtime: tokio::runtime::Handle,
}

impl AsyncTaskRunner {
    pub fn new(runtime: tokio::runtime::Handle) -> Self {
        Self { runtime }
    }

    /// Spawn an async task
    pub fn spawn<F>(&self, future: F) -> tokio::task::JoinHandle<F::Output>
    where
        F: std::future::Future + Send + 'static,
        F::Output: Send + 'static,
    {
        self.runtime.spawn(future)
    }

    /// Spawn a task with a delay
    pub fn spawn_delayed<F>(&self, delay: Duration, future: F) -> tokio::task::JoinHandle<F::Output>
    where
        F: std::future::Future + Send + 'static,
        F::Output: Send + 'static,
    {
        self.runtime.spawn(async move {
            tokio::time::sleep(delay).await;
            future.await
        })
    }
}
