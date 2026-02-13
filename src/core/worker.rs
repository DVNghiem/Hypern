use axum::{
    Router,
    body::Body,
    extract::State,
    http::Request,
    response::IntoResponse,
};
use pyo3::prelude::*;
use std::sync::Arc;
use tokio::net::TcpListener;
use tower::ServiceBuilder;
use tower_http::{
    request_id::{MakeRequestUuid, PropagateRequestIdLayer, SetRequestIdLayer},
    trace::TraceLayer,
};
use tracing::info;

use crate::{core::global::{get_event_loop, set_global_runtime}, http::response::response_404};
use crate::core::interpreter::http_execute;
use crate::http::method::HttpMethod;
use crate::http::request::Request as HypernRequest;
use crate::middleware::{
    middleware_response_to_hyper, MiddlewareChain, MiddlewareContext, MiddlewareResult,
};
use crate::routing::router::Router as HypernRouter;
use crate::socket::SocketHeld;

/// Shared application state for Axum handlers
#[derive(Clone)]
pub struct AppState {
    pub router: Arc<HypernRouter>,
    pub middleware: Arc<MiddlewareChain>,
}

/// Convert HypernRouter routes to Axum Router
fn build_axum_router(state: AppState) -> axum::Router {
    Router::new()
        .fallback(handle_request)
        .with_state(state)
}

/// Main request handler that dispatches to Python handlers
async fn handle_request(
    State(state): State<AppState>,
    req: Request<Body>,
) -> impl IntoResponse {
    // Convert Axum request to Hypern request
    let fast_req = HypernRequest::from_axum(req).await;
    
    // Create middleware context from request
    let method = HttpMethod::from_str(fast_req.method().as_str())
        .unwrap_or(HttpMethod::GET);

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
        MiddlewareResult::Continue() => {
            // Middleware passed, continue to route handler
        }
        MiddlewareResult::Response(response) => {
            return middleware_response_to_hyper(response);
        }
        MiddlewareResult::Error(err) => {
            // Middleware returned an error
            if let Some(response) = state.middleware.execute_error(&mw_ctx, &err).await {
                return middleware_response_to_hyper(response);
            }
            return middleware_response_to_hyper(err.to_response());
        }
    }

    // Match route to get pattern-based hash and params
    let response = if let Some((route, params)) = state.router.find_matching_route(
        fast_req.path(),
        fast_req.method().as_str(),
    ) {
        // Set path params from routing
        fast_req.set_path_params(params.clone());
        mw_ctx.set_params(params);

        let route_hash = route.handler_hash();

        let res = http_execute(route_hash, fast_req).await;

        let _ = state.middleware.execute_after(&mw_ctx).await;

        // Apply middleware response headers to the actual HTTP response
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
    
    // Setup signal handler for Python event loop to stop on SIGTERM/SIGINT
    let loop_for_signal = ev_loop.clone().unbind();
    let shutdown_tx_clone = shutdown_tx.clone();
    std::thread::spawn(move || {
        use std::sync::atomic::{AtomicBool, Ordering};
        static SHUTDOWN: AtomicBool = AtomicBool::new(false);
        
        #[cfg(unix)]
        unsafe {
            extern "C" fn handle_signal(sig: libc::c_int) {
                tracing::info!("Worker received signal {}", sig);
                SHUTDOWN.store(true, Ordering::SeqCst);
            }
            
            libc::signal(libc::SIGINT, handle_signal as extern "C" fn(libc::c_int) as libc::sighandler_t);
            libc::signal(libc::SIGTERM, handle_signal as extern "C" fn(libc::c_int) as libc::sighandler_t);
        }
        
        // Wait for signal
        while !SHUTDOWN.load(Ordering::SeqCst) {
            std::thread::sleep(std::time::Duration::from_millis(50));
        }
        
        tracing::info!("Worker {} initiating shutdown", worker_id);
        
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
        .enable_all()
        .build()
        .expect("Failed to build Tokio runtime");

    rt.spawn(async move {
        let listener =
            TcpListener::from_std(std::net::TcpListener::from(socket_held.get_socket()))
                .expect("Failed to convert listener");

        // Build Axum application with state
        let state = AppState {
            router,
            middleware,
        };

        // Build the Axum router with middleware stack
        let app = build_axum_router(state)
            .layer(
                ServiceBuilder::new()
                    // Request ID propagation
                    .layer(SetRequestIdLayer::x_request_id(MakeRequestUuid))
                    .layer(PropagateRequestIdLayer::x_request_id())
                    // Tracing
                    .layer(TraceLayer::new_for_http())
            );

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

