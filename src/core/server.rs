use hyper::server::conn::http1;
use hyper::service::service_fn;
use hyper_util::rt::TokioIo;
use pyo3::prelude::*;
use pyo3::pycell::PyRef;
use std::sync::Arc;
use tokio::net::TcpListener;

use crate::core::interpreter_pool::InterpreterPool;
use crate::http::request::FastRequest;
use crate::routing::router::Router;
use crate::socket::SocketHeld; // Kept for API compatibility

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
        let num_workers = std::thread::available_parallelism()
            .map(|n| n.get())
            .unwrap_or(4);

        Self {
            router: Arc::new(Router::default()),
            http2: false,
            interpreter_pool: Arc::new(InterpreterPool::new(num_workers)),
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
        _workers: usize,
        _max_blocking_threads: usize,
    ) -> PyResult<()> {
        let raw_socket = socket.get_socket();

        let _addr = raw_socket
            .local_addr()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyOSError, _>(e.to_string()))?
            .as_socket()
            .ok_or_else(|| {
                PyErr::new::<pyo3::exceptions::PyValueError, _>("Invalid socket address")
            })?;

        // Register all routes in the interpreter pool
        for route in self.router.iter() {
            crate::core::interpreter_pool::register_handler(
                route.handler_hash(),
                route.function.clone_ref(py),
            );
        }

        // We need to clone the listener or create a new one from the FD
        // Since we are inside Python start, we likely need to spawn a runtime or block.
        // Usually `server.start` wraps the main future.

        // Convert std TcpListener to Tokio TcpListener
        raw_socket
            .set_nonblocking(true)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyOSError, _>(e.to_string()))?;

        let std_listener = raw_socket
            .try_clone()
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyOSError, _>(e.to_string()))?;

        // Move execution to asyncio loop or run a new runtime?
        // Typically Pyo3 async methods return a Coroutine.
        // But this `start` is synchronous in signature.
        // If it returns `PyResult<()>`, it might be expected to spawn a background thread
        // OR run the loop blocking.
        // Given previous code spawned a thread, let's do that with a Tokio runtime.

        let pool = self.interpreter_pool.clone();
        let router = self.router.clone();

        py.allow_threads(move || {
            let rt = tokio::runtime::Builder::new_multi_thread()
                .enable_all()
                .build()
                .expect("Failed to build Tokio runtime");

            rt.block_on(async move {
                let listener = TcpListener::from_std(std::net::TcpListener::from(std_listener))
                    .expect("Failed to convert listener");

                while let Ok((stream, addr)) = listener.accept().await {
                    let io = TokioIo::new(stream);
                    let pool_ref = pool.clone();
                    let router_ref = router.clone();

                    tokio::task::spawn(async move {
                        if let Err(err) = http1::Builder::new()
                            .serve_connection(
                                io,
                                service_fn(move |req| {
                                    let pool = pool_ref.clone();
                                    let router = router_ref.clone();
                                    async move {
                                        // Parse request to FastRequest
                                        let fast_req = FastRequest::from_hyper(req).await;
                                        eprintln!(
                                            "Received request: {} {}",
                                            fast_req.method().as_str(),
                                            fast_req.path()
                                        );

                                        // Match route to get pattern-based hash and params
                                        if let Some((route, params)) = router.find_matching_route(
                                            fast_req.path(),
                                            fast_req.method().as_str(),
                                        ) {
                                            eprintln!("Matched route: {}", route.path);
                                            fast_req.set_path_params(params);
                                            let route_hash = route.handler_hash();
                                            eprintln!("Route hash: {}", route_hash);

                                            Ok::<_, hyper::Error>(
                                                pool.execute(route_hash, fast_req).await,
                                            )
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
                            eprintln!("Error serving connection from {:?}: {:?}", addr, err);
                        }
                    });
                }
            });
        });

        Ok(())
    }
}
