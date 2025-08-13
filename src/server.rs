use crate::{
    execute::execute_http_function,
    router::router::Router,
    runtime::TokioExecutor,
    socket::SocketHeld,
    types::{
        body::full_http,
        request::Request,
        response::{HTTPResponseBody, Response},
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
use std::{
    collections::HashMap,
    sync::{
        atomic::Ordering::{Relaxed, SeqCst},
        RwLock,
    },
    thread,
    time::Duration,
};
use std::{
    process::exit,
    sync::{atomic::AtomicBool, Arc},
};
use tokio::sync::oneshot;

use tracing_subscriber::{fmt, layer::SubscriberExt, util::SubscriberInitExt};

static STARTED: AtomicBool = AtomicBool::new(false);
static NOTFOUND: &[u8] = b"Not Found";

struct SharedContext {
    router: Arc<RwLock<Router>>,
    extra_headers: Arc<DashMap<String, String>>,
    http2: bool,
}

impl SharedContext {
    fn new(
        router: Arc<RwLock<Router>>,
        extra_headers: Arc<DashMap<String, String>>,
        http2: bool,
    ) -> Self {
        Self {
            router,
            extra_headers,
            http2,
        }
    }

    fn clone(&self) -> Self {
        Self {
            router: Arc::clone(&self.router),
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

        let shared_context =
            SharedContext::new(self.router.clone(), self.extra_headers.clone(), self.http2);

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
                                http2::Builder::new(TokioExecutor)
                                    .keep_alive_timeout(Duration::from_secs(60))
                                    .serve_connection(io, svc)
                                    .await
                            }
                            false => {
                                http1::Builder::new()
                                    .keep_alive(true)
                                    .serve_connection(io, svc)
                                    .with_upgrades()
                                    .await
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
            let response = execute_request(request, function, shared_context.extra_headers).await;
            response
        }
        None => HyperResponse::builder()
            .status(StatusCode::NOT_FOUND)
            .body(full_http(NOTFOUND))
            .unwrap(),
    };
    return response;
}

async fn execute_request(
    request: Request,
    function: PyObject,
    extra_headers: Arc<DashMap<String, String>>,
) -> HyperResponse<HTTPResponseBody> {
    // Create a channel for communication between Python and Rust
    let (tx, rx) = oneshot::channel();
    let response = Response::new(tx);
    
    // Create an async task that will handle the Python function call
    tokio::spawn(async move { execute_http_function(function, request, response).await });

    // Wait for the response from the Python side with a timeout
    let response_result = match rx.await {
        Ok(py_response) => Some(py_response),
        Err(_) => {
            eprintln!("Channel closed without response");
            None
        }
    };

    // Convert the response or return an error
    match response_result {
        Some(py_response) => {
            // Convert PyResponse to HyperResponse
            match py_response {
                crate::types::response::PyResponse::Body(body_response) => {
                    let (mut parts, body) = body_response.to_response().into_parts();

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
                    HyperResponse::from_parts(parts, body)
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
