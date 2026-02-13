use crate::core::global::{get_asyncio, get_global_runtime};
use crate::http::request::Request;
use crate::http::response::{Response, ResponseSlot};
use crate::memory::arena::reset_arena;
use crate::runtime::future_into_py;
use dashmap::DashMap;
use pyo3::prelude::*;
use pyo3::types::PyTuple;
use pyo3::IntoPyObjectExt;
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

/// Get handler data without GIL - just returns a reference
#[inline(always)]
fn get_handler_info(route_hash: u64) -> Option<bool> {
    let registry = HANDLER_REGISTRY.get_or_init(DashMap::new);
    registry.get(&route_hash).map(|entry| entry.1)
}

/// Get handler with GIL
#[inline(always)]
fn get_handler(py: Python, route_hash: u64) -> Option<Py<PyAny>> {
    let registry = HANDLER_REGISTRY.get_or_init(DashMap::new);
    registry.get(&route_hash).map(|entry| entry.0.clone_ref(py))
}

pub async fn http_execute(
    route_hash: u64,
    request: Request,
) -> axum::response::Response {
    let response_slot = ResponseSlot::new();
    let (tx, rx) = tokio::sync::oneshot::channel();

    // Check if handler exists and get is_async flag (no GIL needed)
    let is_async = match get_handler_info(route_hash) {
        Some(is_async) => is_async,
        None => {
            warn!("No handler found for hash: {}", route_hash);
            response_slot.set_status(404);
            response_slot.set_body(b"Not Found".to_vec());
            return response_slot.into_response();
        }
    };

    let response = Response::new(response_slot.clone());
    let rt_ref = get_global_runtime().handler();

    // Direct call to blocking runner - no WorkerPool overhead
    future_into_py(
        &rt_ref,
        is_async,
        move |py| {
            // Get handler with GIL
            let handler = get_handler(py, route_hash).expect("Handler must exist");
            let req_any = request
                .into_bound_py_any(py)
                .expect("Failed to convert request")
                .unbind();
            let res_any = response
                .into_bound_py_any(py)
                .expect("Failed to convert response")
                .unbind();
            let args = PyTuple::new(py, vec![req_any, res_any])
                .expect("Failed to create tuple")
                .unbind();
            (handler, args)
        },
        move || {
            // Reset the thread-local arena after each request
            // This releases all temporary allocations efficiently
            reset_arena();
            let _ = tx.send(());
        },
    );

    // Wait for completion via oneshot
    let _ = rx.await;

    response_slot.into_response()
}
