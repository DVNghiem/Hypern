use crate::core::global::{get_asyncio, get_global_runtime};
use crate::core::worker::{WorkItem, WorkerPool, WorkerPoolConfig};
use crate::http::request::Request;
use crate::http::response::{Response, ResponseSlot};
use crate::runtime::future_into_py_handler;
use dashmap::DashMap;
use pyo3::prelude::*;
use pyo3::IntoPyObjectExt;
use pyo3::types::PyTuple;
use std::sync::Arc;
use std::sync::OnceLock;
use tracing::warn;

static HANDLER_REGISTRY: OnceLock<DashMap<u64, (Py<PyAny>, bool)>> = OnceLock::new();

pub fn register_handler(hash: u64, handler: Py<PyAny>) {
    let is_async = Python::attach(|py| {
        let inspect = get_asyncio(py).bind(py);
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
    request: Request,
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

                    // Registry lookup (no GIL needed - DashMap is lock-free)
                    let handler_data = {
                        let registry = HANDLER_REGISTRY.get_or_init(DashMap::new);
                        registry.get(&work.route_hash).map(|entry| {
                            Python::attach(|py| (entry.0.clone_ref(py), entry.1))
                        })
                    };

                    if let Some((handler, is_async)) = handler_data {
                        let response = Response::new(work.response_slot.clone());
                        let rt_ref = get_global_runtime().handler();
                        
                        // Use closure to build args with GIL
                        future_into_py_handler(
                            &rt_ref,
                            handler,
                            is_async,
                            move |py| {
                                let req_any = work.request.into_bound_py_any(py).expect("Failed to convert request").unbind();
                                let res_any = response.into_bound_py_any(py).expect("Failed to convert response").unbind();
                                PyTuple::new(py, vec![req_any, res_any])
                                    .expect("Failed to create tuple")
                                    .unbind()
                            },
                            move || {
                                let _ = work.completion_tx.send(());
                            },
                        );
                    } else {
                        warn!("No handler found for hash: {}", work.route_hash);
                        work.response_slot.set_status(404);
                        work.response_slot.set_body(b"Not Found".to_vec());
                        let _ = work.completion_tx.send(());
                    }
                });
                Arc::new(pool)
            })
            .clone()
    }

    pub async fn execute(
        &self,
        route_hash: u64,
        request: Request,
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
        )
        .await
        .expect("Worker pool closed");

        // Wait for completion via oneshot
        let _ = rx.await;

        response_slot.into_hyper_response()
    }
}
