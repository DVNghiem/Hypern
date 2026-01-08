use pyo3::prelude::*;
use std::sync::Arc;
use tracing::info;

use crate::middleware::MiddlewareChain;
use crate::routing::router::Router;
use crate::socket::SocketHeld;

/// Spawn worker processes using fork()
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
                    // Child process
                    use crate::core::worker::run_worker;

                    // Run the worker (this blocks forever)
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
                    );
                    // Should never reach here
                    process::exit(0);
                }
                child_pid => {
                    // Parent process
                    child_pids.push(child_pid);
                    info!("Spawned worker {} with PID {}", worker_id + 1, child_pid);
                }
            }
        }
    }

    child_pids
}

/// Wait for all worker processes
#[cfg(unix)]
pub fn wait_for_workers(pids: &[libc::pid_t]) {
    for &pid in pids {
        unsafe {
            let mut status: libc::c_int = 0;
            libc::waitpid(pid, &mut status, 0);
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

/// Non-Unix stub for spawn_workers
#[cfg(not(unix))]
pub fn spawn_workers(
    socket_held: SocketHeld,
    num_workers: usize,
    worker_threads: usize,
    max_blocking_threads: usize,
    max_connections: usize,
    router: Arc<Router>,
    middleware: Arc<MiddlewareChain>,
    handlers: Vec<(u64, Py<PyAny>)>,
) -> Vec<i32> {
    panic!("Multiprocess mode is only supported on Unix systems");
}

/// Non-Unix stub for wait_for_workers  
#[cfg(not(unix))]
pub fn wait_for_workers(pids: &[i32]) {
    panic!("Multiprocess mode is only supported on Unix systems");
}

/// Non-Unix stub for terminate_workers
#[cfg(not(unix))]
pub fn terminate_workers(pids: &[i32]) {
    panic!("Multiprocess mode is only supported on Unix systems");
}
