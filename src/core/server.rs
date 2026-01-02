use hyper::server::conn::http1;
use hyper::service::service_fn;
use hyper_util::rt::TokioIo;
use pyo3::prelude::*;
use pyo3::pycell::PyRef;
use std::sync::Arc;
use std::thread;
use tokio::net::TcpListener;
use tracing::error;

use crate::core::interpreter_pool::InterpreterPool;
use crate::http::method::HttpMethod;
use crate::http::request::Request;
use crate::http::response::RESPONSE_404;
use crate::middleware::{MiddlewareChain, MiddlewareContext, MiddlewareResponse, MiddlewareResult};
use crate::routing::router::Router;
use crate::core::global::{get_connection_semaphore, get_event_loop};
use crate::socket::SocketHeld;
use crate::utils::cpu::num_cpus;

/// Convert a MiddlewareResponse to a hyper Response
fn middleware_response_to_hyper(
    response: MiddlewareResponse,
) -> hyper::Response<crate::body::HTTPResponseBody> {
    let mut builder = hyper::Response::builder().status(response.status);

    for (key, value) in &response.headers {
        builder = builder.header(key.as_str(), value.as_str());
    }

    builder
        .body(crate::body::full_http(response.body))
        .unwrap_or_else(|_| {
            hyper::Response::builder()
                .status(500)
                .body(crate::body::full_http(b"Internal Server Error".to_vec()))
                .unwrap()
        })
}

#[pyclass]
pub struct Server {
    router: Arc<Router>,
    http2: bool,
    interpreter_pool: Arc<InterpreterPool>,
    rust_middleware: Arc<MiddlewareChain>,
}

#[pymethods]
impl Server {
    #[new]
    pub fn new() -> Self {
        Self {
            router: Arc::new(Router::default()),
            http2: false,
            interpreter_pool: Arc::new(InterpreterPool::new(num_cpus(4))),
            rust_middleware: Arc::new(MiddlewareChain::new()),
        }
    }

    pub fn set_router(&mut self, router: Router) {
        self.router = Arc::new(router);
    }

    pub fn enable_http2(&mut self) {
        self.http2 = true;
    }

    pub fn start(
        &mut self,
        py: Python,
        socket: PyRef<SocketHeld>,
        workers: usize,
        max_blocking_threads: usize,
        max_connections: usize,
    ) -> PyResult<()> {
        let raw_socket = socket.get_socket();

        // Register all routes in the interpreter pool
        for route in self.router.iter() {
            crate::core::interpreter_pool::register_handler(
                route.handler_hash(),
                route.function.clone_ref(py),
            );
        }

        // Convert std TcpListener to Tokio TcpListener
        raw_socket
            .set_nonblocking(true)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyOSError, _>(e.to_string()))?;

        let std_listener = raw_socket
            .try_clone()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyOSError, _>(e.to_string()))?;

        let pool = self.interpreter_pool.clone();
        let router = self.router.clone();
        let rust_middleware = self.rust_middleware.clone();
        let ev_loop = get_event_loop(py).bind(py);

        thread::spawn(move || {
            let rt = tokio::runtime::Builder::new_multi_thread()
                .worker_threads(workers)
                .max_blocking_threads(max_blocking_threads)
                .enable_all()
                .build()
                .expect("Failed to build Tokio runtime");

            rt.block_on(async move {
                let listener = TcpListener::from_std(std::net::TcpListener::from(std_listener))
                    .expect("Failed to convert listener");

                while let Ok((stream, addr)) = listener.accept().await {
                    let permit = match get_connection_semaphore(max_connections).try_acquire_owned()
                    {
                        Ok(p) => p,
                        Err(_) => {
                            // Drop connection if at capacity
                            drop(stream);
                            continue;
                        }
                    };

                    let io = TokioIo::new(stream);
                    let pool_ref = pool.clone();
                    let router_ref = router.clone();
                    let middleware_ref = rust_middleware.clone();

                    tokio::task::spawn(async move {
                        let _permit = permit; // Hold permit until done
                        if let Err(err) = http1::Builder::new()
                            .serve_connection(
                                io,
                                service_fn(move |req| {
                                    let pool = pool_ref.clone();
                                    let router = router_ref.clone();
                                    let middleware = middleware_ref.clone();
                                    async move {
                                        let fast_req = Request::from_hyper(req).await;

                                        // Create middleware context from request
                                        let method =
                                            HttpMethod::from_str(fast_req.method().as_str())
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
                                                    return Ok(middleware_response_to_hyper(
                                                        response,
                                                    ));
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
                                            let res = pool.execute(route_hash, fast_req).await;

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
        println!("Server is running...");
        // Keep event loop alive
        let _ = ev_loop.call_method0("run_forever");

        Ok(())
    }
}

impl Server {
    /// Add a pure Rust middleware that runs before handlers (no GIL overhead)
    pub fn use_rust_middleware<M: crate::middleware::RustMiddleware + 'static>(
        &mut self,
        middleware: M,
    ) {
        Arc::get_mut(&mut self.rust_middleware)
            .expect("Cannot modify middleware after server start")
            .use_before(middleware);
    }

    /// Add a pure Rust middleware that runs after handlers (no GIL overhead)
    pub fn use_rust_middleware_after<M: crate::middleware::RustMiddleware + 'static>(
        &mut self,
        middleware: M,
    ) {
        Arc::get_mut(&mut self.rust_middleware)
            .expect("Cannot modify middleware after server start")
            .use_after(middleware);
    }

    /// Set the full Rust middleware chain
    pub fn set_rust_middleware_chain(&mut self, chain: MiddlewareChain) {
        self.rust_middleware = Arc::new(chain);
    }

    /// Get middleware statistics
    pub fn middleware_stats(&self) -> (usize, usize, usize) {
        self.rust_middleware.stats()
    }
}
