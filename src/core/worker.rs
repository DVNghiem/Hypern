use axum::{body::Body, extract::State, http::Request, response::IntoResponse, Router};
use pyo3::prelude::*;
use std::sync::Arc;
use tokio::net::TcpListener;
use tracing::info;

use crate::core::interpreter::http_execute;
use crate::core::reload::ReloadManager;
use crate::http::method::HttpMethod;
use crate::http::request::Request as HypernRequest;
use crate::middleware::{
    middleware_response_to_hyper, MiddlewareChain, MiddlewareContext, MiddlewareResult,
};
use crate::routing::router::Router as HypernRouter;
use crate::socket::SocketHeld;
use crate::{
    core::global::{get_event_loop, set_global_runtime},
    http::response::response_404,
};

/// Shared application state for Axum handlers
#[derive(Clone)]
pub struct AppState {
    pub router: Arc<HypernRouter>,
    pub middleware: Arc<MiddlewareChain>,
    pub reload_manager: ReloadManager,
}

/// Public wrapper for building Axum router (used from multiprocess.rs non-unix path)
pub fn build_axum_router_public(state: AppState) -> axum::Router {
    build_axum_router(state)
}

/// Convert HypernRouter routes to Axum Router with health probe routes
fn build_axum_router(state: AppState) -> axum::Router {
    let health_prefix = state.reload_manager.config().health_path_prefix.clone();
    let probes_enabled = state.reload_manager.config().health_probes_enabled;

    let mut router = Router::new();

    if probes_enabled {
        // Health probe routes
        let live_path = format!("{}/live", health_prefix);
        let ready_path = format!("{}/ready", health_prefix);
        let startup_path = format!("{}/startup", health_prefix);
        let status_path = health_prefix.clone();

        router = router
            .route(
                &live_path,
                axum::routing::get({
                    let rm = state.reload_manager.clone();
                    move || {
                        let rm = rm.clone();
                        async move { health_liveness(rm) }
                    }
                }),
            )
            .route(
                &ready_path,
                axum::routing::get({
                    let rm = state.reload_manager.clone();
                    move || {
                        let rm = rm.clone();
                        async move { health_readiness(rm) }
                    }
                }),
            )
            .route(
                &startup_path,
                axum::routing::get({
                    let rm = state.reload_manager.clone();
                    move || {
                        let rm = rm.clone();
                        async move { health_startup(rm) }
                    }
                }),
            )
            .route(
                &status_path,
                axum::routing::get({
                    let rm = state.reload_manager.clone();
                    move || {
                        let rm = rm.clone();
                        async move { health_status(rm) }
                    }
                }),
            );
    }

    router.fallback(handle_request).with_state(state)
}

// -- health probe handlers --

fn health_liveness(rm: ReloadManager) -> impl IntoResponse {
    let code = rm.health().liveness_code();
    let body = rm.health().to_json();
    (
        axum::http::StatusCode::from_u16(code).unwrap_or(axum::http::StatusCode::INTERNAL_SERVER_ERROR),
        [(axum::http::header::CONTENT_TYPE, "application/json")],
        body,
    )
}

fn health_readiness(rm: ReloadManager) -> impl IntoResponse {
    let code = rm.health().readiness_code();
    let body = rm.health().to_json();
    (
        axum::http::StatusCode::from_u16(code).unwrap_or(axum::http::StatusCode::INTERNAL_SERVER_ERROR),
        [(axum::http::header::CONTENT_TYPE, "application/json")],
        body,
    )
}

fn health_startup(rm: ReloadManager) -> impl IntoResponse {
    let code = rm.health().startup_code();
    let body = rm.health().to_json();
    (
        axum::http::StatusCode::from_u16(code).unwrap_or(axum::http::StatusCode::INTERNAL_SERVER_ERROR),
        [(axum::http::header::CONTENT_TYPE, "application/json")],
        body,
    )
}

fn health_status(rm: ReloadManager) -> impl IntoResponse {
    let code = if rm.health().status().is_live() { 200u16 } else { 503u16 };
    let body = rm.health().to_json();
    (
        axum::http::StatusCode::from_u16(code).unwrap_or(axum::http::StatusCode::INTERNAL_SERVER_ERROR),
        [(axum::http::header::CONTENT_TYPE, "application/json")],
        body,
    )
}

/// Main request handler that dispatches to Python handlers
async fn handle_request(State(state): State<AppState>, req: Request<Body>) -> impl IntoResponse {
    // If draining, reject new requests with 503
    if state.reload_manager.is_draining() {
        return axum::http::Response::builder()
            .status(503)
            .header("Content-Type", "application/json")
            .header("Connection", "close")
            .header("Retry-After", "5")
            .body(Body::from(r#"{"error":"service_draining","message":"Server is reloading, please retry"}"#))
            .unwrap();
    }

    // Track in-flight request
    state.reload_manager.health().increment_in_flight();
    let rm = state.reload_manager.clone();

    // Execute the actual handler and ensure we decrement on exit
    let response = handle_request_inner(&state, req).await;

    // Decrement in-flight and notify drain if needed
    rm.on_request_complete();

    response
}

/// Inner request handler logic (separated for clean in-flight tracking)
async fn handle_request_inner(state: &AppState, req: Request<Body>) -> axum::http::Response<Body> {
    // Convert Axum request to Hypern request
    let fast_req = HypernRequest::from_axum(req).await;

    // Fast path: if no middleware, skip middleware context creation entirely
    let has_before_middleware = !state.middleware.is_empty_before();
    let has_after_middleware = !state.middleware.is_empty_after();

    if has_before_middleware {
        // Create middleware context only when middleware exists
        let method = HttpMethod::from_str(fast_req.method().as_str()).unwrap_or(HttpMethod::GET);
        let headers_map = fast_req.headers_map();
        let mw_ctx = MiddlewareContext::new(
            fast_req.path(),
            method,
            headers_map,
            fast_req.query_string(),
            fast_req.body_ref(),
        );

        // Execute "before" middleware (pure Rust, no GIL)
        match state.middleware.execute_before(&mw_ctx).await {
            MiddlewareResult::Continue() => {}
            MiddlewareResult::Response(response) => {
                return middleware_response_to_hyper(response);
            }
            MiddlewareResult::Error(err) => {
                if let Some(response) = state.middleware.execute_error(&mw_ctx, &err).await {
                    return middleware_response_to_hyper(response);
                }
                return middleware_response_to_hyper(err.to_response());
            }
        }

        // Match route and execute handler
        let response = if let Some((route, params)) = state
            .router
            .find_matching_route(fast_req.path(), fast_req.method().as_str())
        {
            fast_req.set_path_params(params.clone());
            mw_ctx.set_params(params);

            let route_hash = route.handler_hash();
            let res = http_execute(route_hash, fast_req).await;

            if has_after_middleware {
                let _ = state.middleware.execute_after(&mw_ctx).await;
            }

            // Apply middleware response headers
            let headers_to_add = mw_ctx.get_response_headers();
            if !headers_to_add.is_empty() {
                let (mut parts, body) = res.into_parts();
                for (name, value) in headers_to_add {
                    if let (Ok(name), Ok(value)) = (
                        axum::http::HeaderName::from_bytes(name.as_bytes()),
                        axum::http::HeaderValue::from_str(&value),
                    ) {
                        parts.headers.insert(name, value);
                    }
                }
                axum::http::Response::from_parts(parts, body)
            } else {
                res
            }
        } else {
            response_404()
        };

        response
    } else {
        // Fast path: no middleware - go straight to route handler
        if let Some((route, params)) = state
            .router
            .find_matching_route(fast_req.path(), fast_req.method().as_str())
        {
            fast_req.set_path_params(params);
            let route_hash = route.handler_hash();
            http_execute(route_hash, fast_req).await
        } else {
            response_404()
        }
    }
}

/// Run the Axum-based worker process
pub fn run_worker(
    py: Python<'_>,
    socket_held: SocketHeld,
    worker_threads: usize,
    max_blocking_threads: usize,
    _max_connections: usize,
    router: Arc<HypernRouter>,
    middleware: Arc<MiddlewareChain>,
    handlers: Vec<(u64, Py<PyAny>)>,
    worker_id: usize,
    reload_manager: ReloadManager,
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
        max_blocking_threads,
        60,
        Arc::new(ev_loop.clone().unbind()),
    );

    // Setup graceful shutdown coordination
    let (shutdown_tx, shutdown_rx) = tokio::sync::oneshot::channel::<()>();
    let shutdown_tx = Arc::new(std::sync::Mutex::new(Some(shutdown_tx)));

    // Clone reload_manager for the signal thread and the async runtime
    let rm_for_signal = reload_manager.clone();
    let rm_for_drain = reload_manager.clone();

    // Setup signal handler for Python event loop to stop on SIGTERM/SIGINT/SIGUSR1/SIGUSR2
    let loop_for_signal = ev_loop.clone().unbind();
    let shutdown_tx_clone = shutdown_tx.clone();
    std::thread::spawn(move || {
        use std::sync::atomic::{AtomicBool, AtomicI32, Ordering};
        static SHUTDOWN: AtomicBool = AtomicBool::new(false);
        static LAST_SIGNAL: AtomicI32 = AtomicI32::new(0);

        #[cfg(unix)]
        unsafe {
            extern "C" fn handle_signal(sig: libc::c_int) {
                tracing::info!("Worker received signal {}", sig);
                LAST_SIGNAL.store(sig, Ordering::SeqCst);
                SHUTDOWN.store(true, Ordering::SeqCst);
            }

            libc::signal(
                libc::SIGINT,
                handle_signal as extern "C" fn(libc::c_int) as libc::sighandler_t,
            );
            libc::signal(
                libc::SIGTERM,
                handle_signal as extern "C" fn(libc::c_int) as libc::sighandler_t,
            );
            // SIGUSR1 = graceful reload
            libc::signal(
                libc::SIGUSR1,
                handle_signal as extern "C" fn(libc::c_int) as libc::sighandler_t,
            );
            // SIGUSR2 = hot reload (dev)
            libc::signal(
                libc::SIGUSR2,
                handle_signal as extern "C" fn(libc::c_int) as libc::sighandler_t,
            );
        }

        // Wait for signal
        while !SHUTDOWN.load(Ordering::SeqCst) {
            std::thread::sleep(std::time::Duration::from_millis(50));
        }

        let sig = LAST_SIGNAL.load(Ordering::SeqCst);
        tracing::info!("Worker {} initiating shutdown (signal={})", worker_id, sig);

        #[cfg(unix)]
        {
            // SIGUSR1 = graceful: drain in-flight first
            if sig == libc::SIGUSR1 {
                rm_for_signal.start_drain();
                // We don't block the signal thread; the async runtime handles drain.
                // Just give it a brief moment, then signal shutdown.
                std::thread::sleep(std::time::Duration::from_secs(
                    rm_for_signal.config().drain_timeout_secs,
                ));
            } else if sig == libc::SIGUSR2 {
                // Hot reload: immediate
                rm_for_signal.signal_hot_reload();
            } else {
                // SIGINT/SIGTERM: normal shutdown with brief drain
                rm_for_signal.start_drain();
                std::thread::sleep(std::time::Duration::from_secs(2));
            }
        }

        // Signal the async runtime to shutdown
        if let Ok(mut tx) = shutdown_tx_clone.lock() {
            if let Some(sender) = tx.take() {
                let _ = sender.send(());
            }
        }

        std::thread::sleep(std::time::Duration::from_millis(100));
        Python::attach(|py| {
            let loop_ref = loop_for_signal.bind(py);
            let _ = loop_ref.call_method0("stop");
        });
    });

    let rt = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(worker_threads)
        .max_blocking_threads(max_blocking_threads)
        .thread_name_fn(|| {
            static ATOMIC_ID: std::sync::atomic::AtomicUsize =
                std::sync::atomic::AtomicUsize::new(0);
            let id = ATOMIC_ID.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
            format!("hypern-worker-{}", id)
        })
        .enable_all()
        .build()
        .expect("Failed to build Tokio runtime");

    // Mark healthy after startup grace period
    let rm_startup = reload_manager.clone();
    let startup_grace = reload_manager.config().startup_grace_secs;
    rt.spawn(async move {
        tokio::time::sleep(std::time::Duration::from_secs(startup_grace)).await;
        rm_startup.health().mark_healthy();
        info!("Worker {} marked healthy after {}s grace period", worker_id, startup_grace);
    });

    rt.spawn(async move {
        let listener = TcpListener::from_std(std::net::TcpListener::from(socket_held.get_socket()))
            .expect("Failed to convert listener");

        // Build Axum application with state including reload manager
        let state = AppState {
            router,
            middleware,
            reload_manager: rm_for_drain,
        };

        // Build the Axum router with health probe routes
        let app = build_axum_router(state);

        info!("Axum worker {} started", worker_id);

        // Serve with Axum
        axum::serve(listener, app)
            .with_graceful_shutdown(async {
                shutdown_rx.await.ok();
            })
            .await
            .expect("Server error");

        info!("Worker {} Axum server stopped", worker_id);
    });

    info!("Worker {} started", worker_id);

    // Keep event loop alive in this worker process until stopped by signal
    let _ = ev_loop.call_method0("run_forever");

    info!("Worker {} stopped", worker_id);
    Ok(())
}

/// Public helper for non-unix thread-based workers (used from multiprocess.rs)
pub async fn handle_request_standalone(
    req: Request<Body>,
    router: Arc<HypernRouter>,
    middleware: Arc<MiddlewareChain>,
    reload_manager: ReloadManager,
) -> axum::http::Response<Body> {
    let state = AppState {
        router,
        middleware,
        reload_manager,
    };
    handle_request_inner(&state, req).await
}
