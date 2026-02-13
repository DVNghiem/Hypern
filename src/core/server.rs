use pyo3::prelude::*;
use std::sync::Arc;
use crate::core::multiprocess::{spawn_workers, terminate_workers, wait_for_workers};
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
    
    /// Register a Rust middleware to run before request handlers
    pub fn use_middleware(&mut self, middleware: &Bound<'_, PyAny>) -> PyResult<()> {
        use crate::middleware::{
            PyRequestIdMiddleware, PyCorsMiddleware, PySecurityHeadersMiddleware, PyCompressionMiddleware, 
            PyRateLimitMiddleware, PyTimeoutMiddleware, PyLogMiddleware, PyBasicAuthMiddleware
        };
        
        // Check if it's a Rust middleware type and register it
        if let Ok(req_id) = middleware.extract::<PyRequestIdMiddleware>() {
            self.register_boxed_middleware(req_id.inner.clone());
        } else if let Ok(cors) = middleware.extract::<PyCorsMiddleware>() {
            self.register_boxed_middleware(cors.inner.clone());
        } else if let Ok(sec) = middleware.extract::<PySecurityHeadersMiddleware>() {
            self.register_boxed_middleware(sec.inner.clone());
        } else if let Ok(comp) = middleware.extract::<PyCompressionMiddleware>() {
            self.register_boxed_middleware(comp.inner.clone());
        } else if let Ok(rate) = middleware.extract::<PyRateLimitMiddleware>() {
            self.register_boxed_middleware(rate.inner.clone());
        } else if let Ok(timeout) = middleware.extract::<PyTimeoutMiddleware>() {
            self.register_boxed_middleware(timeout.inner.clone());
        } else if let Ok(log) = middleware.extract::<PyLogMiddleware>() {
            self.register_boxed_middleware(log.inner.clone());
        } else if let Ok(auth) = middleware.extract::<PyBasicAuthMiddleware>() {
            self.register_boxed_middleware(auth.inner.clone());
        } else {
            return Err(pyo3::exceptions::PyTypeError::new_err(
                "Middleware must be a Rust middleware type (CORS, SecurityHeaders, RequestId, etc.)"
            ));
        }
        
        Ok(())
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

        // Setup signal handling in parent process
        #[cfg(unix)]
        {
            use std::sync::atomic::{AtomicBool, Ordering};
            static SHUTDOWN: AtomicBool = AtomicBool::new(false);
            
            unsafe {
                extern "C" fn handle_signal(sig: libc::c_int) {
                    tracing::info!("Parent process received signal {}", sig);
                    SHUTDOWN.store(true, Ordering::SeqCst);
                }
                libc::signal(libc::SIGINT, handle_signal as extern "C" fn(libc::c_int) as libc::sighandler_t);
                libc::signal(libc::SIGTERM, handle_signal as extern "C" fn(libc::c_int) as libc::sighandler_t);
            }
            
            // Wait for signal or worker exit
            loop {
                if SHUTDOWN.load(Ordering::SeqCst) {
                    println!("Received shutdown signal, stopping workers...");
                    terminate_workers(&pids);
                    break;
                }
                
                // Check if any worker has exited
                unsafe {
                    let mut status: libc::c_int = 0;
                    let pid = libc::waitpid(-1, &mut status, libc::WNOHANG);
                    if pid > 0 {
                        // A worker exited, shutdown all workers
                        println!("Worker {} exited, shutting down...", pid);
                        terminate_workers(&pids);
                        break;
                    }
                }
                
                // Use shorter sleep for more responsive shutdown
                std::thread::sleep(std::time::Duration::from_millis(50));
            }
        }
        // Wait for all workers to finish
        wait_for_workers(&pids);

        Ok(())
    }
}

impl Server {
    /// Internal method to register a boxed middleware (not exposed to Python)
    fn register_boxed_middleware(&mut self, middleware: Arc<dyn crate::middleware::RustMiddleware>) {
        Arc::get_mut(&mut self.rust_middleware)
            .expect("Cannot modify middleware after server start")
            .use_before_boxed(middleware);
    }
    
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
