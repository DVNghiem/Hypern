use crate::core::worker::{WorkItem, WorkerPool, WorkerPoolConfig};
use crate::http::request::FastRequest;
use crate::http::response::{ResponseSlot, ResponseWriter};
use crate::runtime::{get_asyncio, get_inspect};
use dashmap::DashMap;
use pyo3::prelude::*;
use std::sync::Arc;
use std::sync::OnceLock;
use tracing::{error, warn};

static HANDLER_REGISTRY: OnceLock<DashMap<u64, (Py<PyAny>, bool)>> = OnceLock::new();

pub fn register_handler(hash: u64, handler: Py<PyAny>) {
    let is_async = Python::attach(|py| {
        let inspect = get_inspect(py).bind(py);
        inspect
            .call_method1("iscoroutinefunction", (&handler,))
            .expect("Failed to call iscoroutinefunction")
            .is_truthy()
            .unwrap_or(false)
    });

    HANDLER_REGISTRY
        .get_or_init(DashMap::new)
        .insert(hash, (handler, is_async));
}

pub struct InterpreterPool {
    pool: OnceLock<Arc<WorkerPool<RequestWork>>>,
    num_workers: usize,
}

enum ExecutionResult {
    SyncSuccess(Option<tokio::sync::oneshot::Sender<()>>),
    AsyncFuture(
        std::pin::Pin<
            Box<dyn std::future::Future<Output = PyResult<Py<PyAny>>> + Send>,
        >,
        Option<tokio::sync::oneshot::Sender<()>>,
    ),
    Callback,
    NotFound(Option<tokio::sync::oneshot::Sender<()>>),
    Error(PyErr),
}

// Work item data structure
struct RequestWork {
    route_hash: u64,
    request: FastRequest,
    response_slot: Arc<ResponseSlot>,
    completion_tx: tokio::sync::oneshot::Sender<()>,
}

impl InterpreterPool {
    pub fn new(num_workers: usize) -> Self {
        Self {
            pool: OnceLock::new(),
            num_workers,
        }
    }

    fn get_pool(&self) -> Arc<WorkerPool<RequestWork>> {
        self.pool
            .get_or_init(|| {
                let config = WorkerPoolConfig::new(self.num_workers);
                // Handler is now an async closure
                let pool = WorkerPool::new(config, |item: WorkItem<RequestWork>| async move {
                    let work = item.data;

                    
                    // registry lookup (no GIL needed - DashMap is lock-free)
                    let handler_entry = {
                        let registry = HANDLER_REGISTRY.get_or_init(DashMap::new);
                        registry.get(&work.route_hash)
                    };
                    let writer = ResponseWriter::new(work.response_slot.clone());
                    // Run Python logic to get the future or execution result
                    let exec_result = Python::attach(|py| {

                        if let Some(handler_entry) = handler_entry {
                            let (handler, is_async) = &*handler_entry;

                            // Handle errors during wrapping
                            let py_writer = match Bound::new(py, writer) {
                                Ok(w) => w,
                                Err(e) => return ExecutionResult::Error(e),
                            };
                            let py_req = match Bound::new(py, work.request.clone()) {
                                Ok(r) => r,
                                Err(e) => return ExecutionResult::Error(e),
                            };

                            let args = (py_req, py_writer);
                            let call_result = handler.bind(py).call1(args);

                            if *is_async {
                                match call_result {
                                    Ok(coro) => {
                                        if let Some(locals) = crate::core::runtime::get_task_locals() {
                                            // Granian-inspired Push Model
                                            // 1. Get the event loop
                                            let loop_ = locals.event_loop(py);
                                            
                                            // 2. Schedule the coroutine on the loop using thread-safe generic
                                            let asyncio  = get_asyncio(py).bind(py);
                                            match asyncio.call_method1("run_coroutine_threadsafe", (coro, loop_)) {
                                                Ok(future) => {
                                                    // 3. Attach our callback
                                                    let callback = crate::http::callback::PyResponseCallback::new(
                                                        work.completion_tx,
                                                    );
                                                    match Bound::new(py, callback) {
                                                        Ok(bound_cb) => {
                                                            match future.call_method1(
                                                                "add_done_callback",
                                                                (bound_cb.getattr("done").unwrap(),),
                                                            ) {
                                                                Ok(_) => ExecutionResult::Callback,
                                                                Err(e) => ExecutionResult::Error(e),
                                                            }
                                                        }
                                                        Err(e) => ExecutionResult::Error(e),
                                                    }
                                                }
                                                Err(e) => ExecutionResult::Error(e),
                                            }
                                        } else {
                                            // Fallback logic if TaskLocals are not initialized
                                            match pyo3_async_runtimes::tokio::into_future(coro) {
                                                Ok(fut) => ExecutionResult::AsyncFuture(
                                                    Box::pin(fut),
                                                    Some(work.completion_tx),
                                                ),
                                                Err(e) => ExecutionResult::Error(e),
                                            }
                                        }
                                    }
                                    Err(e) => ExecutionResult::Error(e),
                                }
                            } else {
                                match call_result {
                                    Ok(_) => ExecutionResult::SyncSuccess(Some(work.completion_tx)),
                                    Err(e) => ExecutionResult::Error(e),
                                }
                            }
                        } else {
                            ExecutionResult::NotFound(Some(work.completion_tx))
                        }
                    });

                    // Handle the result (outside GIL where possible for awaiting)
                    match exec_result {
                        ExecutionResult::Callback => {
                            // Do nothing, the callback will trigger the oneshot
                        }
                        ExecutionResult::SyncSuccess(tx) => {
                            if let Some(tx) = tx {
                                let _ = tx.send(());
                            }
                        }
                        ExecutionResult::AsyncFuture(fut, tx) => match fut.await {
                            Ok(_) => {
                                if let Some(tx) = tx {
                                    println!("Async future finished for hash: {}", work.route_hash);
                                    let _ = tx.send(());
                                }
                            }
                            Err(e) => {
                                error!(
                                    "Python async handler error for hash {}: {:?}",
                                    work.route_hash, e
                                );
                                work.response_slot.set_status(500);
                                work.response_slot.set_body(
                                    format!("Internal Server Error: {:?}", e).into_bytes(),
                                );
                                if let Some(tx) = tx {
                                    let _ = tx.send(());
                                }
                            }
                        },
                        ExecutionResult::NotFound(tx) => {
                            warn!("No handler found for hash: {}", work.route_hash);
                            work.response_slot.set_status(404);
                            work.response_slot.set_body(b"Not Found".to_vec());
                            if let Some(tx) = tx {
                                let _ = tx.send(());
                            }
                        }
                        ExecutionResult::Error(e) => {
                            error!("Python handler error for hash {}: {:?}", work.route_hash, e);
                            work.response_slot.set_status(500);
                            work.response_slot
                                .set_body(format!("Internal Server Error: {:?}", e).into_bytes());
                        }
                    }
                });
                Arc::new(pool)
            })
            .clone()
    }

    pub async fn execute(
        &self,
        route_hash: u64,
        request: FastRequest,
    ) -> hyper::Response<crate::body::HTTPResponseBody> {
        let response_slot = ResponseSlot::new();
        let (tx, rx) = tokio::sync::oneshot::channel();

        let pool = self.get_pool();
        pool.submit_affinity(
            WorkItem {
                id: 0,
                data: RequestWork {
                    route_hash,
                    request,
                    response_slot: response_slot.clone(),
                    completion_tx: tx,
                },
            },
            route_hash,
        ).await
        .expect("Worker pool closed");

        // Wait for completion via oneshot
        let _ = rx.await;

        response_slot.into_hyper_response()
    }
}
