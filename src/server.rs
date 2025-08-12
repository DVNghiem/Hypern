use crate::{
    runtime::TokioExecutor,
    router::router::Router,
    socket::SocketHeld,
    types::{
        body::full_http,
        request::Request, 
        response::{Response, HTTPResponseBody},
    },
};
use dashmap::DashMap;
use hyper::Response as HyperResponse;
use hyper::{
    body::Incoming,
    header::{HeaderName, HeaderValue},
    server::conn::{http1, http2},
    service::service_fn,
    Request as HyperRequest, StatusCode,
};
use hyper_util::rt::TokioIo;
use pyo3::prelude::*;
use pyo3::pycell::PyRef;
use pyo3_async_runtimes::TaskLocals;
use std::{
    collections::HashMap,
    sync::{
        atomic::Ordering::{Relaxed, SeqCst},
        RwLock,
    },
    thread,
    time::{Duration, Instant},
};
use std::{
    process::exit,
    sync::{atomic::AtomicBool, Arc},
};
use tokio::sync::oneshot;

use tracing::{debug, info};
use tracing_subscriber::{fmt, layer::SubscriberExt, util::SubscriberInitExt};

static STARTED: AtomicBool = AtomicBool::new(false);
static NOTFOUND: &[u8] = b"Not Found";

struct SharedContext {
    router: Arc<RwLock<Router>>,
    task_locals: Arc<TaskLocals>,
    extra_headers: Arc<DashMap<String, String>>,
    http2: bool,
}

impl SharedContext {
    fn new(
        router: Arc<RwLock<Router>>,
        task_locals: Arc<TaskLocals>,
        extra_headers: Arc<DashMap<String, String>>,
        http2: bool,
    ) -> Self {
        Self {
            router,
            task_locals,
            extra_headers,
            http2,
        }
    }

    fn clone(&self) -> Self {
        Self {
            router: Arc::clone(&self.router),
            task_locals: Arc::clone(&self.task_locals),
            extra_headers: Arc::clone(&self.extra_headers),
            http2: self.http2,
        }
    }
}

#[pyclass]
pub struct Server {
    router: Arc<RwLock<Router>>,
    extra_headers: Arc<DashMap<String, String>>,
    http2: bool,
}

#[pymethods]
impl Server {
    #[new]
    pub fn new() -> Self {
        Self {
            router: Arc::new(RwLock::new(Router::default())),
            extra_headers: Arc::new(DashMap::new()),
            http2: false,
        }
    }

    pub fn set_router(&mut self, router: Router) {
        // Update router
        self.router = Arc::new(RwLock::new(router));
    }

    pub fn set_response_headers(&mut self, headers: HashMap<String, String>) {
        for (key, value) in headers {
            self.extra_headers.insert(key, value);
        }
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
    ) -> PyResult<()> {
        tracing_subscriber::registry()
            .with(
                tracing_subscriber::EnvFilter::try_from_default_env()
                    .unwrap_or_else(|_| "debug".into()),
            )
            .with(
                fmt::layer()
                    .with_target(false)
                    .with_level(true)
                    .with_file(true),
            )
            .init();

        if STARTED
            .compare_exchange(false, true, SeqCst, Relaxed)
            .is_err()
        {
            return Ok(());
        }

        let raw_socket = socket.get_socket();
        let asyncio = py.import("asyncio")?;
        let event_loop = asyncio.call_method0("get_event_loop")?;

        let task_locals = Arc::new(TaskLocals::new(event_loop.clone()).copy_context(py)?);

        let shared_context = SharedContext::new(
            self.router.clone(),
            task_locals.clone(),
            self.extra_headers.clone(),
            self.http2,
        );

        thread::spawn(move || {
            let rt = tokio::runtime::Builder::new_multi_thread()
                .worker_threads(workers)
                .max_blocking_threads(max_blocking_threads)
                .thread_keep_alive(Duration::from_secs(60))
                .thread_name("hypern-worker")
                .thread_stack_size(3 * 1024 * 1024) // 3MB stack
                .enable_all()
                .build()
                .unwrap();
            debug!(
                "Server start with {} workers and {} max blockingthreads",
                workers, max_blocking_threads
            );
            debug!("Waiting for process to start...");

            rt.block_on(async move {
                let listener = tokio::net::TcpListener::from_std(raw_socket.into()).unwrap();

                loop {
                    let (stream, _) = listener.accept().await.unwrap();
                    let io = TokioIo::new(stream);
                    let shared_context = shared_context.clone();
                    tokio::task::spawn(async move {
                        let svc = service_fn(|req: hyper::Request<hyper::body::Incoming>| {
                            let shared_context = shared_context.clone();
                            async move {
                                let response = http_service(req, shared_context).await;
                                Ok::<_, hyper::Error>(response)
                            }
                        });

                        match shared_context.http2 {
                            true => {
                                if let Err(err) = http2::Builder::new(TokioExecutor)
                                    .keep_alive_timeout(Duration::from_secs(60))
                                    .serve_connection(io, svc)
                                    .await
                                {
                                    debug!("Failed to serve connection: {:?}", err);
                                }
                            }
                            false => {
                                if let Err(err) = http1::Builder::new()
                                    .keep_alive(true)
                                    .serve_connection(io, svc)
                                    .with_upgrades()
                                    .await
                                {
                                    debug!("Failed to serve connection: {:?}", err);
                                }
                            }
                        }
                    });
                }
            });
        });

        let event_loop = event_loop.call_method0("run_forever");
        if event_loop.is_err() {
            exit(0);
        }
        Ok(())
    }
}

async fn http_service(
    req: HyperRequest<Incoming>,
    shared_context: SharedContext,
) -> HyperResponse<HTTPResponseBody> {
    let path = req.uri().path().to_string();
    let method = req.method().to_string();
    let version = req.version();
    let user_agent = req
        .headers()
        .get("user-agent")
        .cloned()
        .unwrap_or(HeaderValue::from_str("unknown").unwrap());
    let start_time = Instant::now();

    // matching mapping router
    let route = {
        let router = shared_context.router.read().unwrap();
        router.find_matching_route(&path, &method)
    };

    let response = match route {
        Some((route, _path_params)) => {
            let function = route.function;
            let request = Request::new(req).await;
            // request.path_params = path_params;
            let response = execute_request(
                request,
                function,
                shared_context.extra_headers,
                shared_context.task_locals,
            )
            .await;
            response
        }
        None => HyperResponse::builder()
            .status(StatusCode::NOT_FOUND)
            .body(full_http(NOTFOUND))
            .unwrap(),
    };
    // logging
    info!(
        "{:?} {:?} {:?} {:?} {:?} {:?}",
        version,
        method,
        path,
        user_agent,
        start_time.elapsed(),
        response.status(),
    );

    return response;
}

async fn execute_request(
    request: Request,
    function: PyObject,
    extra_headers: Arc<DashMap<String, String>>,
    task_locals: Arc<TaskLocals>,
) -> HyperResponse<HTTPResponseBody> {
    // Create a channel for communication between Python and Rust
    let (tx, rx) = oneshot::channel();
    let response = Response::new(tx);

    // Clone necessary data for the async task
    let function_clone = function;
    
    // Create an async task that will handle the Python function call
    let python_task = async move {
        // Use spawn_blocking but with proper async handling
        let result = tokio::task::spawn_blocking(move || {
            Python::with_gil(|py| {
                // Call the Python function
                let args = (request, response);
                let result = function_clone.call1(py, args);
                
                // Handle the result - whether it's a coroutine or not
                match result {
                    Ok(maybe_coro) => {
                        // Check if it's a coroutine by trying to access __await__
                        if let Ok(true) = maybe_coro.bind(py).hasattr("__await__") {
                            // This is a coroutine, we need to await it properly
                            let asyncio = py.import("asyncio")?;
                            
                            // Use asyncio.run() to create a new event loop and run the coroutine
                            let _result = asyncio.call_method1("run", (maybe_coro,))?;
                            Ok(())
                        } else {
                            // Synchronous function, already executed
                            Ok(())
                        }
                    }
                    Err(e) => {
                        eprintln!("Python function call error: {:?}", e);
                        Err(e)
                    }
                }
            })
        })
        .await;

        match result {
            Ok(Ok(())) => Ok(()),
            Ok(Err(py_err)) => {
                eprintln!("Python function error: {:?}", py_err);
                Err(())
            }
            Err(join_err) => {
                eprintln!("Task join error: {:?}", join_err);
                Err(())
            }
        }
    };

    // Wait for the response from the Python side with a timeout
    let response_result = tokio::select! {
        // Execute the Python function
        python_result = python_task => {
            match python_result {
                Ok(()) => {
                    // Python function executed successfully, now wait for response
                    match rx.await {
                        Ok(py_response) => Some(py_response),
                        Err(_) => {
                            eprintln!("Channel closed without response");
                            None
                        }
                    }
                }
                Err(()) => {
                    eprintln!("Python function execution failed");
                    None
                }
            }
        }
        // Add a timeout to prevent hanging
        _ = tokio::time::sleep(tokio::time::Duration::from_secs(30)) => {
            eprintln!("Request timeout after 30 seconds");
            None
        }
    };

    // Convert the response or return an error
    match response_result {
        Some(py_response) => {
            // Convert PyResponse to HyperResponse
            match py_response {
                crate::types::response::PyResponse::Body(body_response) => {
                    let (mut parts, _body) = body_response.to_response().into_parts();

                    // Add extra headers from the server configuration
                    for header in extra_headers.iter() {
                        if let (Ok(name), Ok(value)) = (
                            HeaderName::from_bytes(header.key().as_bytes()),
                            HeaderValue::from_str(header.value()),
                        ) {
                            parts.headers.insert(name, value);
                        }
                    }

                    // Create the response with the proper body type
                    HyperResponse::from_parts(parts, full_http(""))
                }
            }
        }
        None => {
            // If no response was received, return 500
            HyperResponse::builder()
                .status(StatusCode::INTERNAL_SERVER_ERROR)
                .body(full_http("No response from handler"))
                .unwrap()
        }
    }
}
