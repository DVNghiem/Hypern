use pyo3::prelude::*;
use std::sync::Arc;
use crate::core::multiprocess::{spawn_workers, wait_for_workers};
use crate::middleware::MiddlewareChain;
use crate::routing::router::Router;
use crate::socket::SocketHeld;

#[pyclass]
pub struct Server {
    router: Arc<Router>,
    http2: bool,
    rust_middleware: Arc<MiddlewareChain>,
}

#[pymethods]
impl Server {
    #[new]
    pub fn new() -> Self {
        Self {
            router: Arc::new(Router::default()),
            http2: false,
            rust_middleware: Arc::new(MiddlewareChain::new()),
        }
    }

    pub fn set_router(&mut self, router: Router) {
        self.router = Arc::new(router);
    }

    pub fn enable_http2(&mut self) {
        self.http2 = true;
    }

    #[pyo3(signature = (host, port, num_processes=1, workers_threads=1, max_blocking_threads=16, max_connections=10000))]
    pub fn start(
        &mut self,
        py: Python,
        host: String,
        port: u16,
        num_processes: usize,
        workers_threads: usize,
        max_blocking_threads: usize,
        max_connections: usize,
    ) -> PyResult<()> {

        // Setup tracing 
        tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info,hypern=debug".into()),
        )
        .with_thread_ids(true)
        .init();

        // Collect handlers before fork
        let raw_socket = SocketHeld::new(host, port)?;
        let mut handlers: Vec<(u64, Py<PyAny>)> = Vec::new();
        for route in self.router.iter() {
            handlers.push((route.handler_hash(), route.function.clone_ref(py)));
        }

        let router = self.router.clone();
        let middleware = self.rust_middleware.clone();

        // Spawn worker processes using fork
        let pids = spawn_workers(
            py,
            raw_socket,
            num_processes,
            workers_threads,
            max_blocking_threads,
            max_connections,
            router,
            middleware,
            handlers,
        );

        println!("All {} workers started", pids.len());

        // Parent process waits for all workers
        wait_for_workers(&pids);

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
