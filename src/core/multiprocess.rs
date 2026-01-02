//! Multiprocess server implementation using fork()
//! Each worker process has its own Python interpreter and GIL

use hyper::server::conn::http1;
use hyper::service::service_fn;
use hyper_util::rt::TokioIo;
use pyo3::prelude::*;
use std::sync::Arc;
use tokio::net::TcpListener;
use tracing::{error, info};

use crate::http::method::HttpMethod;
use crate::http::request::Request;
use crate::http::response::RESPONSE_404;
use crate::middleware::{MiddlewareChain, MiddlewareContext, MiddlewareResponse, MiddlewareResult};
use crate::routing::router::Router;

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

/// Worker configuration
#[derive(Clone)]
pub struct WorkerConfig {
    pub worker_id: usize,
    pub host: String,
    pub port: u16,
    pub tokio_workers: usize,
    pub max_blocking_threads: usize,
    pub max_connections: usize,
}

/// Run the worker process event loop
pub fn run_worker(
    config: WorkerConfig,
    router: Arc<Router>,
    middleware: Arc<MiddlewareChain>,
    handlers: Vec<(u64, Py<PyAny>)>,
) {
    use std::net::{IpAddr, SocketAddr};
    use socket2::{Domain, Protocol, Socket, Type};
    use std::time::Duration;

    info!("Worker {} starting with PID {}", config.worker_id, std::process::id());

    // Create socket with SO_REUSEPORT for load balancing
    let ip: IpAddr = config.host.parse().expect("Invalid IP");
    let socket = if ip.is_ipv4() {
        Socket::new(Domain::IPV4, Type::STREAM, Some(Protocol::TCP)).unwrap()
    } else {
        Socket::new(Domain::IPV6, Type::STREAM, Some(Protocol::TCP)).unwrap()
    };

    let address = SocketAddr::new(ip, config.port);

    // Socket options for high performance
    #[cfg(not(target_os = "windows"))]
    socket.set_reuse_port(true).unwrap();
    socket.set_reuse_address(true).unwrap();
    socket.set_tcp_nodelay(true).unwrap();
    
    let keepalive = socket2::TcpKeepalive::new().with_time(Duration::from_secs(60));
    socket.set_keepalive(true).unwrap();
    let _ = socket.set_tcp_keepalive(&keepalive);
    socket.set_linger(Some(Duration::from_secs(0))).unwrap();
    
    // Increase buffer sizes
    let _ = socket.set_recv_buffer_size(256 * 1024);
    let _ = socket.set_send_buffer_size(256 * 1024);

    // Linux-specific optimizations
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::io::AsRawFd;
        let fd = socket.as_raw_fd();
        unsafe {
            let enable: libc::c_int = 5;
            libc::setsockopt(
                fd,
                libc::IPPROTO_TCP,
                libc::TCP_FASTOPEN,
                &enable as *const _ as *const libc::c_void,
                std::mem::size_of::<libc::c_int>() as libc::socklen_t,
            );
            let enable: libc::c_int = 1;
            libc::setsockopt(
                fd,
                libc::IPPROTO_TCP,
                libc::TCP_QUICKACK,
                &enable as *const _ as *const libc::c_void,
                std::mem::size_of::<libc::c_int>() as libc::socklen_t,
            );
        }
    }

    socket.set_nonblocking(true).unwrap();
    socket.bind(&address.into()).unwrap();
    socket.listen(8192).unwrap();

    // Build tokio runtime for this worker
    let rt = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(config.tokio_workers)
        .max_blocking_threads(config.max_blocking_threads)
        .enable_all()
        .build()
        .expect("Failed to build Tokio runtime");

    // Register handlers in this process's interpreter pool
    for (hash, handler) in handlers {
        crate::core::interpreter_pool::register_handler(hash, handler);
    }

    // Create interpreter pool for this worker
    let pool = Arc::new(crate::core::interpreter_pool::InterpreterPool::new(
        config.max_blocking_threads,
    ));

    // Connection semaphore
    let semaphore = Arc::new(tokio::sync::Semaphore::new(config.max_connections));

    rt.block_on(async move {
        let listener = TcpListener::from_std(std::net::TcpListener::from(socket))
            .expect("Failed to convert listener");

        info!("Worker {} listening on {}:{}", config.worker_id, config.host, config.port);

        loop {
            match listener.accept().await {
                Ok((stream, _addr)) => {
                    let permit = match semaphore.clone().try_acquire_owned() {
                        Ok(p) => p,
                        Err(_) => {
                            drop(stream);
                            continue;
                        }
                    };

                    let io = TokioIo::new(stream);
                    let pool_ref = pool.clone();
                    let router_ref = router.clone();
                    let middleware_ref = middleware.clone();

                    tokio::task::spawn(async move {
                        let _permit = permit;
                        let _ = http1::Builder::new()
                            .serve_connection(
                                io,
                                service_fn(move |req| {
                                    let pool = pool_ref.clone();
                                    let router = router_ref.clone();
                                    let middleware = middleware_ref.clone();
                                    async move {
                                        let fast_req = Request::from_hyper(req).await;

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

                                        match middleware.execute_before(&mw_ctx).await {
                                            MiddlewareResult::Continue() => {}
                                            MiddlewareResult::Response(response) => {
                                                return Ok::<_, hyper::Error>(
                                                    middleware_response_to_hyper(response),
                                                );
                                            }
                                            MiddlewareResult::Error(err) => {
                                                if let Some(response) =
                                                    middleware.execute_error(&mw_ctx, &err).await
                                                {
                                                    return Ok(middleware_response_to_hyper(response));
                                                }
                                                return Ok(middleware_response_to_hyper(err.to_response()));
                                            }
                                        }

                                        if let Some((route, params)) = router.find_matching_route(
                                            fast_req.path(),
                                            fast_req.method().as_str(),
                                        ) {
                                            fast_req.set_path_params(params.clone());
                                            mw_ctx.set_params(params);

                                            let route_hash = route.handler_hash();
                                            let res = pool.execute(route_hash, fast_req).await;

                                            let _ = middleware.execute_after(&mw_ctx).await;

                                            Ok::<_, hyper::Error>(res)
                                        } else {
                                            Ok(RESPONSE_404.clone())
                                        }
                                    }
                                }),
                            )
                            .await;
                    });
                }
                Err(e) => {
                    error!("Worker {} accept error: {:?}", config.worker_id, e);
                }
            }
        }
    });
}

/// Spawn worker processes using fork()
#[cfg(unix)]
pub fn spawn_workers(
    num_workers: usize,
    config: WorkerConfig,
    router: Arc<Router>,
    middleware: Arc<MiddlewareChain>,
    handlers: Vec<(u64, Py<PyAny>)>,
) -> Vec<libc::pid_t> {
    use std::process;
    
    let mut child_pids = Vec::with_capacity(num_workers);

    for worker_id in 0..num_workers {
        // Clone handlers with GIL before fork
        let handlers_clone: Vec<(u64, Py<PyAny>)> = Python::attach(|py| {
            handlers.iter().map(|(h, p)| (*h, p.clone_ref(py))).collect()
        });
        
        unsafe {
            let pid = libc::fork();
            
            match pid {
                -1 => {
                    panic!("Failed to fork worker {}", worker_id);
                }
                0 => {
                    // Child process
                    let mut worker_config = config.clone();
                    worker_config.worker_id = worker_id + 1;
                    
                    // Run the worker (this blocks forever)
                    run_worker(worker_config, router.clone(), middleware.clone(), handlers_clone);
                    
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
    _num_workers: usize,
    _config: WorkerConfig,
    _router: Arc<Router>,
    _middleware: Arc<MiddlewareChain>,
    _handlers: Vec<(u64, Py<PyAny>)>,
) -> Vec<i32> {
    panic!("Multiprocess mode is only supported on Unix systems");
}

/// Non-Unix stub for wait_for_workers  
#[cfg(not(unix))]
pub fn wait_for_workers(_pids: &[i32]) {
    panic!("Multiprocess mode is only supported on Unix systems");
}

/// Non-Unix stub for terminate_workers
#[cfg(not(unix))]
pub fn terminate_workers(_pids: &[i32]) {
    panic!("Multiprocess mode is only supported on Unix systems");
}
