use crate::{
    instants::TokioExecutor,
    router::router::Router,
    socket::SocketHeld,
    types::{
        body::{full, BoxBody},
        request::Request,
    },
};
use dashmap::DashMap;
use hyper::{
    body::Incoming,
    server::conn::{http1, http2},
    service::service_fn,
    Request as HyperRequest, StatusCode,
};
use hyper::{header::HeaderValue, Response as HyperResponse};
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
) -> HyperResponse<BoxBody> {
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
        Some((route, path_params)) => {
            let function = route.function;
            let mut request = Request::new(req).await;
            // request.path_params = path_params;
            let response = mapping_method(
                request,
                function,
                shared_context.task_locals,
                shared_context.extra_headers,
            )
            .await;
            response
        }
        None => HyperResponse::builder()
            .status(StatusCode::NOT_FOUND)
            .body(full(NOTFOUND))
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
) -> HyperResponse<BoxBody> {
    // Execute the main handler
    let response = execute_http_function(&request, &function).await.unwrap();

    // mapping context id
    response.to_response(&extra_headers)
}

async fn mapping_method(
    req: Request,
    function: PyObject,
    task_locals: Arc<TaskLocals>,
    extra_headers: Arc<DashMap<String, String>>,
) -> HyperResponse<BoxBody> {
    pyo3_async_runtimes::tokio::scope(
        (*task_locals).clone_ref(function.py()),
        execute_request(req, function, extra_headers),
    )
    .await
}
