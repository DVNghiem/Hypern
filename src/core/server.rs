use hyper::server::conn::http1;
use hyper::service::service_fn;
use hyper_util::rt::TokioIo;
use pyo3::prelude::*;
use pyo3::pycell::PyRef;
// use std::process::exit; // Removed unused import
use std::sync::Arc;
use std::thread;
use tokio::net::TcpListener;
use tracing::error;

use crate::core::interpreter_pool::InterpreterPool;
use crate::http::request::FastRequest;
use crate::routing::router::Router;
use crate::runtime::{get_connection_semaphore, get_event_loop};
use crate::socket::SocketHeld;
use crate::utils::cpu::num_cpus; // Kept for API compatibility

#[pyclass]
pub struct Server {
    router: Arc<Router>, // Kept for API, used by Python side to register routes
    http2: bool,
    interpreter_pool: Arc<InterpreterPool>,
}

#[pymethods]
impl Server {
    #[new]
    pub fn new() -> Self {
        Self {
            router: Arc::new(Router::default()),
            http2: false,
            interpreter_pool: Arc::new(InterpreterPool::new(num_cpus(4))),
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
                    let permit = match get_connection_semaphore(max_connections).try_acquire_owned() {
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

                    tokio::task::spawn(async move {
                        let _permit = permit; // Hold permit until done
                        if let Err(err) = http1::Builder::new()
                            .serve_connection(
                                io,
                                service_fn(move |req| {
                                    let pool = pool_ref.clone();
                                    let router = router_ref.clone();
                                    async move {
                                        // Parse request to FastRequest
                                        let fast_req = FastRequest::from_hyper(req).await;
                                        // Match route to get pattern-based hash and params
                                        if let Some((route, params)) = router.find_matching_route(
                                            fast_req.path(),
                                            fast_req.method().as_str(),
                                        ) {
                                            fast_req.set_path_params(params);
                                            let route_hash = route.handler_hash();
                                            let res = pool.execute(route_hash, fast_req).await;
                                            Ok::<_, hyper::Error>(res)
                                        } else {
                                            // 404 Not Found
                                            let mut res = hyper::Response::new(
                                                crate::http::body::full_http(b"Not Found".to_vec()),
                                            );
                                            *res.status_mut() = hyper::StatusCode::NOT_FOUND;
                                            Ok(res)
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
        // Only run_forever if we are the main thread or if requested.
        // In the original code it was here.
        let _ = ev_loop.call_method0("run_forever");

        Ok(())
    }
}
