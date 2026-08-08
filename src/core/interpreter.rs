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

pub async fn http_execute(route_hash: u64, request: Request) -> axum::response::Response {
    let response_slot = ResponseSlot::new();
    let (tx, rx) = tokio::sync::oneshot::channel();

    // Check if handler exists and get is_async flag (no GIL needed)
    let is_async = match get_handler_info(route_hash) {
        Some(is_async) => is_async,
        None => {
            log::warn!("No handler found for hash: {}", route_hash);
            response_slot.set_status(404);
            response_slot.set_body(b"Not Found".to_vec());
            return response_slot.into_response();
        }
    };

    let response = Response::new(response_slot.clone());
    let rt_ref = get_global_runtime().handler();

    // Direct call to blocking runner - minimized GIL scope
    let enqueue_result = future_into_py(
        &rt_ref,
        is_async,
        move |py| {
            // This closure runs under GIL - minimize work here
            let handler = get_handler(py, route_hash).expect("Handler must exist");

            // Use raw PyO3 API to avoid intermediate conversions
            let req_any = request
                .into_bound_py_any(py)
                .expect("Failed to convert request")
                .unbind();
            let res_any = response
                .into_bound_py_any(py)
                .expect("Failed to convert response")
                .unbind();

            // Create tuple using raw C API for speed - avoids PyTuple::new allocation overhead
            unsafe {
                let tuple = pyo3::ffi::PyTuple_New(2);
                pyo3::ffi::PyTuple_SetItem(tuple, 0, req_any.into_ptr());
                pyo3::ffi::PyTuple_SetItem(tuple, 1, res_any.into_ptr());
                // Safety: we just created a valid tuple above
                let args = <pyo3::Bound<'_, PyTuple> as Clone>::clone(
                    &Bound::from_owned_ptr(py, tuple).cast::<PyTuple>().unwrap(),
                )
                .unbind();
                (handler, args)
            }
        },
        move |result| {
            if result.is_ok() {
                // The arena belongs to the worker thread and is only used by
                // tasks that actually started executing.
                reset_arena();
            }
            let _ = tx.send(result);
        },
    );
    if let Err(error) = enqueue_result {
        log::warn!("Python worker rejected request: {:?}", error);
    }

    // Accepted work can still be rejected while queued during shutdown, so
    // completion must carry the runner result rather than merely wake us.
    match rx.await {
        Ok(Ok(())) => {}
        Ok(Err(error)) => {
            log::warn!(
                "Python worker stopped before executing request: {:?}",
                error
            );
            response_slot.set_status(503);
            if matches!(error, crate::core::blocking::BlockingRunnerError::QueueFull) {
                response_slot.add_header("Retry-After".to_string(), "1".to_string());
                response_slot.set_body(b"Service Busy".to_vec());
            } else {
                response_slot.set_body(b"Service Unavailable".to_vec());
            }
        }
        Err(error) => {
            log::warn!("Python worker completion channel closed: {}", error);
            response_slot.set_status(503);
            response_slot.set_body(b"Service Unavailable".to_vec());
        }
    }

    response_slot.into_response()
}
