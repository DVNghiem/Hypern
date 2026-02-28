use pyo3::prelude::*;
use std::sync::Arc;

use crate::core::reload::ReloadManager;
use crate::middleware::MiddlewareChain;
use crate::routing::router::Router;
use crate::socket::SocketHeld;

/// Spawn worker processes using fork() - Now uses Axum
#[cfg(unix)]
pub fn spawn_workers(
    py: Python<'_>,
    socket_held: SocketHeld,
    num_workers: usize,
    worker_threads: usize,
    max_blocking_threads: usize,
    max_connections: usize,
    router: Arc<Router>,
    middleware: Arc<MiddlewareChain>,
    handlers: Vec<(u64, Py<PyAny>)>,
    reload_manager: ReloadManager,
) -> Vec<libc::pid_t> {
    use std::process;

    let mut child_pids = Vec::with_capacity(num_workers);

    for worker_id in 0..num_workers {
        // Clone handlers with GIL before fork
        let handlers_clone: Vec<(u64, Py<PyAny>)> = Python::attach(|py| {
            handlers
                .iter()
                .map(|(h, p)| (*h, p.clone_ref(py)))
                .collect()
        });

        unsafe {
            let pid = libc::fork();

            match pid {
                -1 => {
                    panic!("Failed to fork worker {}", worker_id);
                }
                0 => {
                    // Child process - use Axum worker
                    use crate::core::worker::run_worker;
                    use crate::logging::LogQueue;

                    // Re-initialize the log queue for this child process
                    // (the parent's consumer thread doesn't survive fork)
                    LogQueue::reinit_after_fork();

                    // Each child gets its own ReloadManager instance
                    let child_reload = ReloadManager::new(reload_manager.config().clone());

                    // Run the Axum worker (this blocks forever)
                    let _ = run_worker(
                        py,
                        socket_held.try_clone().expect("Failed to open socket"),
                        worker_threads,
                        max_blocking_threads,
                        max_connections,
                        router.clone(),
                        middleware.clone(),
                        handlers_clone,
                        worker_id,
                        child_reload,
                    );
                    // Should never reach here
                    process::exit(0);
                }
                child_pid => {
                    // Parent process
                    child_pids.push(child_pid);
                    crate::hlog_info!(
                        "Spawned Axum worker {} with PID {}",
                        worker_id + 1,
                        child_pid
                    );
                }
            }
        }
    }

    child_pids
}

#[cfg(unix)]
pub fn wait_for_workers(pids: &[libc::pid_t]) {
    use std::time::{Duration, Instant};

    let start = Instant::now();
    let timeout = Duration::from_secs(5); // 5 second timeout

    for &pid in pids {
        let remaining = timeout.saturating_sub(start.elapsed());

        if remaining.is_zero() {
            crate::hlog_warn!("Timeout waiting for worker {}, force killing", pid);
            unsafe {
                libc::kill(pid, libc::SIGKILL);
                let mut status: libc::c_int = 0;
                libc::waitpid(pid, &mut status, 0);
            }
        } else {
            // Try to wait with remaining time
            let mut waited = false;
            let check_start = Instant::now();

            while check_start.elapsed() < remaining {
                unsafe {
                    let mut status: libc::c_int = 0;
                    let result = libc::waitpid(pid, &mut status, libc::WNOHANG);
                    if result == pid {
                        waited = true;
                        break;
                    } else if result == -1 {
                        waited = true;
                        break;
                    }
                }
                std::thread::sleep(Duration::from_millis(10));
            }

            if !waited {
                crate::hlog_warn!("Worker {} did not exit gracefully, force killing", pid);
                unsafe {
                    libc::kill(pid, libc::SIGKILL);
                    let mut status: libc::c_int = 0;
                    libc::waitpid(pid, &mut status, 0);
                }
            }
        }
    }
}

/// Signal all workers to terminate
#[cfg(unix)]
pub fn terminate_workers(pids: &[libc::pid_t]) {
    for &pid in pids {
        unsafe {
            libc::kill(pid, libc::SIGTERM);
        }
    }
}

/// Non-Unix implementation for spawn_workers using threads
/// On Windows and other non-Unix platforms, we use threads instead of fork()
#[cfg(not(unix))]
pub fn spawn_workers(
    py: Python<'_>,
    socket_held: SocketHeld,
    num_workers: usize,
    worker_threads: usize,
    max_blocking_threads: usize,
    max_connections: usize,
    router: Arc<Router>,
    middleware: Arc<MiddlewareChain>,
    handlers: Vec<(u64, Py<PyAny>)>,
    reload_manager: ReloadManager,
) -> Vec<std::thread::JoinHandle<()>> {
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::thread;

    crate::hlog_info!(
        "Starting {} thread-based workers (non-Unix mode)",
        num_workers
    );

    // Shared counter for load balancing
    static WORKER_COUNTER: AtomicUsize = AtomicUsize::new(0);

    let mut handles = Vec::with_capacity(num_workers);

    for worker_id in 0..num_workers {
        // Clone all necessary data for the thread
        let socket = socket_held.try_clone().expect("Failed to clone socket");
        let router = router.clone();
        let middleware = middleware.clone();
        let rm = ReloadManager::new(reload_manager.config().clone());

        // Clone handlers with GIL
        let handlers_clone: Vec<(u64, Py<PyAny>)> = Python::attach(|inner_py| {
            handlers
                .iter()
                .map(|(h, p)| (*h, p.clone_ref(inner_py)))
                .collect()
        });

        let handle = thread::Builder::new()
            .name(format!("hypern-worker-{}", worker_id))
            .spawn(move || {
                // Register handlers for this thread
                for (hash, handler) in handlers_clone {
                    crate::core::interpreter::register_handler(hash, handler);
                }

                // Build and run the Tokio runtime for this worker
                let rt = tokio::runtime::Builder::new_multi_thread()
                    .worker_threads(worker_threads)
                    .max_blocking_threads(max_blocking_threads)
                    .enable_all()
                    .thread_name(format!("hypern-{}-tokio", worker_id))
                    .build()
                    .expect("Failed to create Tokio runtime");

                rt.block_on(async {
                    use std::net::TcpListener;
                    use tokio::net::TcpListener as TokioListener;

                    // Convert socket to TcpListener
                    let std_listener: TcpListener = socket.get_socket().into();
                    std_listener
                        .set_nonblocking(true)
                        .expect("Failed to set non-blocking");

                    let listener = TokioListener::from_std(std_listener)
                        .expect("Failed to create Tokio listener");

                    crate::hlog_info!("Thread worker {} listening", worker_id);

                    // Build Axum router using the standard AppState path
                    let state = crate::core::worker::AppState {
                        router: router.clone(),
                        middleware: middleware.clone(),
                        reload_manager: rm.clone(),
                    };

                    let app = crate::core::worker::build_axum_router_public(state);

                    // Mark healthy after grace period
                    let rm_startup = rm.clone();
                    let startup_grace = rm.config().startup_grace_secs;
                    tokio::spawn(async move {
                        tokio::time::sleep(std::time::Duration::from_secs(startup_grace)).await;
                        rm_startup.health().mark_healthy();
                        crate::hlog_info!("Thread worker {} marked healthy", worker_id);
                    });

                    // Serve with connection limits
                    let server = axum::serve(listener, app).with_graceful_shutdown(async {
                        // Wait for shutdown signal
                        tokio::signal::ctrl_c()
                            .await
                            .expect("Failed to install Ctrl+C handler");
                        crate::hlog_info!("Worker {} received shutdown signal", worker_id);
                    });

                    if let Err(e) = server.await {
                        crate::hlog_error!("Worker {} server error: {}", worker_id, e);
                    }
                });
            })
            .expect("Failed to spawn worker thread");

        handles.push(handle);
        crate::hlog_info!("Spawned thread worker {} (thread-based)", worker_id + 1);
    }

    handles
}

/// Wait for all worker threads to complete
#[cfg(not(unix))]
pub fn wait_for_workers(handles: Vec<std::thread::JoinHandle<()>>) {
    for handle in handles {
        let _ = handle.join();
    }
}

/// On non-Unix platforms, we use a different type for worker handles
#[cfg(not(unix))]
pub fn terminate_workers(_handles: &[std::thread::JoinHandle<()>]) {
    // Threads don't support external termination in the same way as processes
    // The graceful shutdown will be handled by the Ctrl+C handler
    crate::hlog_info!("Requesting graceful shutdown of thread workers");
}
