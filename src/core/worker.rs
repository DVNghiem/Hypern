//! Multiprocess server implementation using fork()
//! Each worker process has its own Python interpreter and GIL

use hyper::server::conn::http1;
use hyper::service::service_fn;
use hyper_util::rt::TokioIo;
use pyo3::prelude::*;
use std::sync::Arc;
use tokio::net::TcpListener;
use tracing::{error, info};

use crate::core::global::{get_connection_semaphore, get_event_loop, set_global_runtime};
use crate::core::interpreter::http_execute;
use crate::http::method::HttpMethod;
use crate::http::request::Request;
use crate::http::response::RESPONSE_404;
use crate::middleware::{
    middleware_response_to_hyper, MiddlewareChain, MiddlewareContext, MiddlewareResult,
};
use crate::routing::router::Router;
use crate::socket::SocketHeld;

/// Run the worker process event loop
pub fn run_worker(
    py: Python<'_>,
    socket_held: SocketHeld,
    worker_threads: usize,
    max_blocking_threads: usize,
    max_connections: usize,
    router: Arc<Router>,
    middleware: Arc<MiddlewareChain>,
    handlers: Vec<(u64, Py<PyAny>)>,
    worker_id: usize,
) -> PyResult<()> {
    // Register handlers in this process's interpreter pool
    for (hash, handler) in handlers {
        crate::core::interpreter::register_handler(hash, handler);
    }

    let ev_loop = get_event_loop(py).bind(py);
    // Use max_blocking_threads for py_threads to maximize Python concurrency
    set_global_runtime(
        worker_threads,
        max_blocking_threads,
        max_blocking_threads, // py_threads = max_blocking_threads
        60,
        Arc::new(ev_loop.clone().unbind()),
    );

    std::thread::spawn(move || {
        let rt = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(worker_threads)
            .max_blocking_threads(max_blocking_threads)
            .enable_all()
            .build()
            .expect("Failed to build Tokio runtime");

        rt.block_on(async move {
            let listener =
                TcpListener::from_std(std::net::TcpListener::from(socket_held.get_socket()))
                    .expect("Failed to convert listener");

            while let Ok((stream, addr)) = listener.accept().await {
                let permit = match get_connection_semaphore(max_connections).try_acquire_owned() {
                    Ok(p) => p,
                    Err(_) => {
                        // Drop connection if at capacity
                        drop(stream);
                        continue;
                    }
                };

                let io = TokioIo::new(stream);
                let router_ref = router.clone();
                let middleware_ref = middleware.clone();

                tokio::task::spawn(async move {
                    let _permit = permit; // Hold permit until done
                    if let Err(err) = http1::Builder::new()
                        .serve_connection(
                            io,
                            service_fn(move |req| {
                                let router = router_ref.clone();
                                let middleware = middleware_ref.clone();
                                async move {
                                    let fast_req = Request::from_hyper(req).await;

                                    // Create middleware context from request
                                    let method = HttpMethod::from_str(fast_req.method().as_str())
                                        .unwrap_or(HttpMethod::GET);

                                    // Build headers map for middleware context
                                    let headers_map = fast_req.headers_map();

                                    let mw_ctx = MiddlewareContext::new(
                                        fast_req.path(),
                                        method,
                                        headers_map,
                                        fast_req.query_string(),
                                        fast_req.body_ref(),
                                    );

                                    // Execute "before" middleware (pure Rust, no GIL)
                                    match middleware.execute_before(&mw_ctx).await {
                                        MiddlewareResult::Continue() => {
                                            // Middleware passed, continue to route handler
                                        }
                                        MiddlewareResult::Response(response) => {
                                            // Middleware short-circuited with a response
                                            return Ok::<_, hyper::Error>(
                                                middleware_response_to_hyper(response),
                                            );
                                        }
                                        MiddlewareResult::Error(err) => {
                                            // Middleware returned an error
                                            if let Some(response) =
                                                middleware.execute_error(&mw_ctx, &err).await
                                            {
                                                return Ok(middleware_response_to_hyper(response));
                                            }
                                            return Ok(middleware_response_to_hyper(
                                                err.to_response(),
                                            ));
                                        }
                                    }

                                    // Match route to get pattern-based hash and params
                                    if let Some((route, params)) = router.find_matching_route(
                                        fast_req.path(),
                                        fast_req.method().as_str(),
                                    ) {
                                        // Set path params from routing
                                        fast_req.set_path_params(params.clone());
                                        mw_ctx.set_params(params);

                                        let route_hash = route.handler_hash();

                                        // Execute Python handler (this is where GIL is acquired)
                                        let res = http_execute(route_hash, fast_req).await;

                                        // Execute "after" middleware (pure Rust, no GIL)
                                        let _ = middleware.execute_after(&mw_ctx).await;

                                        Ok::<_, hyper::Error>(res)
                                    } else {
                                        Ok(RESPONSE_404.clone())
                                    }
                                }
                            }),
                        )
                        .await
                    {
                        error!("Error serving connection from {:?}: {:?}", addr, err);
                    }
                });
            }
        });
    });
    info!("Worker {} started", worker_id);

    // Keep event loop alive in this worker process
    let _ = ev_loop.call_method0("run_forever");

    Ok(())
}
