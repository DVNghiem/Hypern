use crate::core::worker::{WorkItem, WorkerPool, WorkerPoolConfig};
use crate::http::request::FastRequest;
use crate::http::response::{ResponseSlot, ResponseWriter};
use dashmap::DashMap;
use pyo3::prelude::*;
use std::sync::Arc;
use std::sync::OnceLock;
use tracing::{error, warn};

static HANDLER_REGISTRY: OnceLock<DashMap<u64, Py<PyAny>>> = OnceLock::new();

pub fn register_handler(hash: u64, handler: Py<PyAny>) {
    HANDLER_REGISTRY
        .get_or_init(DashMap::new)
        .insert(hash, handler);
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
                let pool = WorkerPool::new(config, |item: WorkItem<RequestWork>| {
                    let work = item.data;

                    Python::attach(|py| {
                        let registry = HANDLER_REGISTRY.get_or_init(DashMap::new);

                        if let Some(handler) = registry.get(&work.route_hash) {
                            let writer = ResponseWriter::new(work.response_slot.clone());
                            let py_writer =
                                Bound::new(py, writer).expect("Failed to wrap ResponseWriter");
                            let py_req = Bound::new(py, work.request.clone())
                                .expect("Failed to wrap FastRequest");

                            // Direct call to Python handler
                            let args = (py_req, py_writer);
                            match handler.bind(py).call1(args) {
                                Ok(_) => {
                                    if !work.response_slot.is_ready() {
                                        work.response_slot.mark_ready();
                                    }
                                }
                                Err(e) => {
                                    error!("Python handler error: {:?}", e);
                                    work.response_slot.set_status(500);
                                    work.response_slot.set_body(
                                        format!("Internal Server Error: {:?}", e).into_bytes(),
                                    );
                                    work.response_slot.mark_ready();
                                }
                            }
                        } else {
                            warn!("No handler found for hash: {}", work.route_hash);
                            work.response_slot.set_status(404);
                            work.response_slot.set_body(b"Not Found".to_vec());
                            work.response_slot.mark_ready();
                        }
                    });
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
