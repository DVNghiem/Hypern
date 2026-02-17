use crate::core::multiprocess::{spawn_workers, terminate_workers, wait_for_workers};
use crate::core::reload::{PyHealthCheck, PyReloadConfig, PyReloadManager, ReloadConfig, ReloadManager};
use crate::middleware::MiddlewareChain;
use crate::routing::router::Router;
use crate::socket::SocketHeld;
use pyo3::prelude::*;
use std::sync::Arc;

#[pyclass]
pub struct Server {
    router: Arc<Router>,
    http2: bool,
    rust_middleware: Arc<MiddlewareChain>,
    reload_config: ReloadConfig,
    reload_manager: Option<ReloadManager>,
}

#[pymethods]
impl Server {
    #[new]
    pub fn new() -> Self {
        Self {
            router: Arc::new(Router::default()),
            http2: false,
            rust_middleware: Arc::new(MiddlewareChain::new()),
            reload_config: ReloadConfig::default(),
            reload_manager: None,
        }
    }

    pub fn set_router(&mut self, router: Router) {
        self.router = Arc::new(router);
    }

    pub fn enable_http2(&mut self) {
        self.http2 = true;
    }

    /// Configure reload behavior.
    pub fn set_reload_config(&mut self, config: PyReloadConfig) {
        self.reload_config = config.inner;
    }

    /// Get the reload manager (created on start, available after start is called).
    pub fn get_reload_manager(&self) -> Option<PyReloadManager> {
        self.reload_manager.as_ref().map(|rm| PyReloadManager {
            inner: rm.clone(),
        })
    }

    /// Get the health check (created on start).
    pub fn get_health_check(&self) -> Option<PyHealthCheck> {
        self.reload_manager.as_ref().map(|rm| PyHealthCheck {
            inner: rm.health().clone(),
        })
    }

    /// Trigger a graceful reload (SIGUSR1 to workers).
    pub fn graceful_reload(&self) {
        if let Some(ref rm) = self.reload_manager {
            rm.signal_graceful_reload();
        }
    }

    /// Trigger a hot reload (SIGUSR2 to workers).
    pub fn hot_reload(&self) {
        if let Some(ref rm) = self.reload_manager {
            rm.signal_hot_reload();
        }
    }

    /// Register a Rust middleware to run before request handlers
    pub fn use_middleware(&mut self, middleware: &Bound<'_, PyAny>) -> PyResult<()> {
        use crate::middleware::{
            PyBasicAuthMiddleware, PyCompressionMiddleware, PyCorsMiddleware, PyLogMiddleware,
            PyRateLimitMiddleware, PyRequestIdMiddleware, PySecurityHeadersMiddleware,
            PyTimeoutMiddleware,
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
        let raw_socket = SocketHeld::new(host.clone(), port)?;
        let mut handlers: Vec<(u64, Py<PyAny>)> = Vec::new();
        for route in self.router.iter() {
            handlers.push((route.handler_hash(), route.function.clone_ref(py)));
        }

        let router = self.router.clone();
        let middleware = self.rust_middleware.clone();

        // Create the reload manager for this server instance
        let reload_manager = ReloadManager::new(self.reload_config.clone());
        self.reload_manager = Some(reload_manager.clone());

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
            reload_manager.clone(),
        );

        println!("All {} workers started", pids.len());

        // Setup signal handling in parent process
        #[cfg(unix)]
        {
            use std::sync::atomic::{AtomicBool, AtomicI32, Ordering};
            static SHUTDOWN: AtomicBool = AtomicBool::new(false);
            static GRACEFUL_RELOAD: AtomicBool = AtomicBool::new(false);
            static HOT_RELOAD: AtomicBool = AtomicBool::new(false);
            static LAST_SIGNAL: AtomicI32 = AtomicI32::new(0);

            unsafe {
                extern "C" fn handle_signal(sig: libc::c_int) {
                    tracing::info!("Parent process received signal {}", sig);
                    LAST_SIGNAL.store(sig, Ordering::SeqCst);
                    match sig {
                        libc::SIGUSR1 => GRACEFUL_RELOAD.store(true, Ordering::SeqCst),
                        libc::SIGUSR2 => HOT_RELOAD.store(true, Ordering::SeqCst),
                        _ => SHUTDOWN.store(true, Ordering::SeqCst),
                    }
                }
                libc::signal(
                    libc::SIGINT,
                    handle_signal as extern "C" fn(libc::c_int) as libc::sighandler_t,
                );
                libc::signal(
                    libc::SIGTERM,
                    handle_signal as extern "C" fn(libc::c_int) as libc::sighandler_t,
                );
                libc::signal(
                    libc::SIGUSR1,
                    handle_signal as extern "C" fn(libc::c_int) as libc::sighandler_t,
                );
                libc::signal(
                    libc::SIGUSR2,
                    handle_signal as extern "C" fn(libc::c_int) as libc::sighandler_t,
                );
            }

            // Wait for signal or worker exit
            loop {
                // Graceful reload: SIGUSR1
                if GRACEFUL_RELOAD.compare_exchange(true, false, Ordering::AcqRel, Ordering::Acquire).is_ok() {
                    println!("Received SIGUSR1: graceful reload – draining workers...");
                    reload_manager.signal_graceful_reload();

                    // Send SIGUSR1 to all workers so they start draining
                    for &pid in &pids {
                        unsafe { libc::kill(pid, libc::SIGUSR1); }
                    }

                    // Wait for drain timeout, then SIGTERM workers
                    let drain_secs = reload_manager.config().drain_timeout_secs;
                    std::thread::sleep(std::time::Duration::from_secs(drain_secs));

                    // Terminate old workers gracefully
                    terminate_workers(&pids);
                    wait_for_workers(&pids);

                    // Respawn workers
                    let new_rm = ReloadManager::new(self.reload_config.clone());
                    let new_handlers: Vec<(u64, Py<PyAny>)> = Python::attach(|py| {
                        self.router.iter().map(|r| (r.handler_hash(), r.function.clone_ref(py))).collect()
                    });
                    let new_socket = SocketHeld::new(host.clone(), port)?;
                    let new_pids = spawn_workers(
                        py,
                        new_socket,
                        num_processes,
                        workers_threads,
                        max_blocking_threads,
                        max_connections,
                        self.router.clone(),
                        self.rust_middleware.clone(),
                        new_handlers,
                        new_rm.clone(),
                    );

                    self.reload_manager = Some(new_rm.clone());
                    println!("Graceful reload complete – {} new workers started", new_pids.len());

                    // Update pids for subsequent loops (we can't reassign pids since it's
                    // borrowed; just continue looping with old pids gone – workers were waited on)
                    // In practice the parent should exit here for full reload; for simplicity
                    // we break and let the outer Python layer handle restart.
                    new_rm.reset_after_reload();
                    wait_for_workers(&new_pids);
                    break;
                }

                // Hot reload: SIGUSR2 – kill immediately, restart
                if HOT_RELOAD.compare_exchange(true, false, Ordering::AcqRel, Ordering::Acquire).is_ok() {
                    println!("Received SIGUSR2: hot reload – killing workers...");
                    reload_manager.signal_hot_reload();

                    // Immediately kill workers
                    for &pid in &pids {
                        unsafe { libc::kill(pid, libc::SIGKILL); }
                    }
                    wait_for_workers(&pids);

                    // Respawn workers
                    let new_rm = ReloadManager::new(self.reload_config.clone());
                    let new_handlers: Vec<(u64, Py<PyAny>)> = Python::attach(|py| {
                        self.router.iter().map(|r| (r.handler_hash(), r.function.clone_ref(py))).collect()
                    });
                    let new_socket = SocketHeld::new(host.clone(), port)?;
                    let new_pids = spawn_workers(
                        py,
                        new_socket,
                        num_processes,
                        workers_threads,
                        max_blocking_threads,
                        max_connections,
                        self.router.clone(),
                        self.rust_middleware.clone(),
                        new_handlers,
                        new_rm.clone(),
                    );

                    self.reload_manager = Some(new_rm.clone());
                    println!("Hot reload complete – {} new workers started", new_pids.len());
                    new_rm.reset_after_reload();
                    wait_for_workers(&new_pids);
                    break;
                }

                if SHUTDOWN.load(Ordering::SeqCst) {
                    println!("Received shutdown signal, stopping workers...");
                    // Send SIGUSR1 to workers for brief drain before termination
                    for &pid in &pids {
                        unsafe { libc::kill(pid, libc::SIGUSR1); }
                    }
                    // Brief grace period for in-flight requests
                    std::thread::sleep(std::time::Duration::from_secs(2));
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
    fn register_boxed_middleware(
        &mut self,
        middleware: Arc<dyn crate::middleware::RustMiddleware>,
    ) {
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
