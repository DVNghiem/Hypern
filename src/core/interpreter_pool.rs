use crate::core::worker::{WorkItem, WorkerPool, WorkerPoolConfig};
use crate::http::request::FastRequest;
use crate::http::response::{ResponseSlot, ResponseWriter};
use dashmap::DashMap;
use pyo3::prelude::*;
use std::sync::Arc;
use std::sync::OnceLock;
use tracing::{error, warn};

static HANDLER_REGISTRY: OnceLock<DashMap<u64, (Py<PyAny>, bool)>> = OnceLock::new();

pub fn register_handler(hash: u64, handler: Py<PyAny>) {
    let is_async = Python::attach(|py| {
        let inspect = py.import("inspect").expect("Failed to import inspect");
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

// Work item data structure
struct RequestWork {
    route_hash: u64,
    request: FastRequest,
    response_slot: Arc<ResponseSlot>,
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

                    enum ExecutionResult {
                        SyncSuccess,
                        AsyncFuture(std::pin::Pin<Box<dyn std::future::Future<Output = PyResult<Py<PyAny>>> + Send>>),
                        NotFound,
                        Error(PyErr),
                    }

                    // Run Python logic to get the future or execution result
                    let exec_result = Python::attach(|py| {
                        let registry = HANDLER_REGISTRY.get_or_init(DashMap::new);

                        if let Some(entry) = registry.get(&work.route_hash) {
                            let (handler, is_async) = entry.value();
                            
                            let writer = ResponseWriter::new(work.response_slot.clone());
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
                                        // Convert to Rust Future
                                        match pyo3_async_runtimes::tokio::into_future(coro) {
                                            Ok(fut) => ExecutionResult::AsyncFuture(Box::pin(fut)),
                                            Err(e) => ExecutionResult::Error(e)
                                        }
                                    },
                                    Err(e) => ExecutionResult::Error(e)
                                }
                            } else {
                                match call_result {
                                    Ok(_) => ExecutionResult::SyncSuccess,
                                    Err(e) => ExecutionResult::Error(e)
                                }
                            }
                        } else {
                            ExecutionResult::NotFound
                        }
                    });

                    // Handle the result (outside GIL where possible for awaiting)
                    match exec_result {
                        ExecutionResult::SyncSuccess => {
                            if !work.response_slot.is_ready() {
                                work.response_slot.mark_ready();
                            }
                        }
                        ExecutionResult::AsyncFuture(fut) => {
                            match fut.await {
                                Ok(_) => {
                                    if !work.response_slot.is_ready() {
                                        work.response_slot.mark_ready();
                                    }
                                }
                                Err(e) => {
                                    error!("Python async handler error: {:?}", e);
                                    work.response_slot.set_status(500);
                                    work.response_slot.set_body(
                                        format!("Internal Server Error: {:?}", e).into_bytes(),
                                    );
                                    work.response_slot.mark_ready();
                                }
                            }
                        }
                        ExecutionResult::NotFound => {
                            warn!("No handler found for hash: {}", work.route_hash);
                            work.response_slot.set_status(404);
                            work.response_slot.set_body(b"Not Found".to_vec());
                            work.response_slot.mark_ready();
                        }
                        ExecutionResult::Error(e) => {
                            error!("Python handler error: {:?}", e);
                            work.response_slot.set_status(500);
                            work.response_slot.set_body(
                                format!("Internal Server Error: {:?}", e).into_bytes(),
                            );
                            work.response_slot.mark_ready();
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

        let work = RequestWork {
            route_hash,
            request,
            response_slot: response_slot.clone(),
        };

        // Submit to pool based on hash
        self.get_pool()
            .submit_affinity(WorkItem { id: 0, data: work }, route_hash)
            .expect("Worker pool closed");

        // Wait for completion (non-blocking yield)
        let mut iterations = 0;
        loop {
            if response_slot.is_ready() {
                error!("Response ready after {} iterations", iterations);
                break;
            }
            iterations += 1;
            if iterations % 1000 == 0 {
                tokio::task::yield_now().await;
            }
        }

        let res = response_slot.into_hyper_response();
        res
    }
}
