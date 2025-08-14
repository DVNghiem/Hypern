use crate::{
    execute::execute_http_function,
    router::router::Router,
    runtime::TokioExecutor,
    socket::SocketHeld,
    types::{body::{full_http, HTTPResponseBody}, request::Request, response::Response},
};
use hyper::Response as HyperResponse;
use hyper::{
    body::Incoming,
    server::conn::{http1, http2},
    service::service_fn,
    Request as HyperRequest, StatusCode,
};
use hyper_util::rt::TokioIo;
use pyo3::prelude::*;
use pyo3::pycell::PyRef;
use std::{process::exit, sync::Arc};
use std::{sync::RwLock, thread, time::Duration};
use tokio::sync::oneshot;

struct SharedContext {
    router: Arc<RwLock<Router>>,
    task_locals: Arc<pyo3_async_runtimes::TaskLocals>,
    http2: bool,
}

impl SharedContext {
    fn new(
        router: Arc<RwLock<Router>>,
        task_locals: Arc<pyo3_async_runtimes::TaskLocals>,
        http2: bool,
    ) -> Self {
        Self {
            router,
            task_locals,
            http2,
        }
    }

    fn clone(&self) -> Self {
        Self {
            router: Arc::clone(&self.router),
            task_locals: Arc::clone(&self.task_locals),
            http2: self.http2,
        }
    }
}

#[pyclass]
pub struct Server {
    router: Arc<RwLock<Router>>,
    http2: bool,
}

#[pymethods]
impl Server {
    #[new]
    pub fn new() -> Self {
        Self {
            router: Arc::new(RwLock::new(Router::default())),
            http2: false,
        }
    }

    pub fn set_router(&mut self, router: Router) {
        // Update router
        self.router = Arc::new(RwLock::new(router));
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
        let raw_socket = socket.get_socket();
        let asyncio = py.import("asyncio")?;
        let event_loop = asyncio.call_method0("get_event_loop")?;
        let task_locals =
            Arc::new(pyo3_async_runtimes::TaskLocals::new(event_loop.clone()).copy_context(py)?);

        let shared_context = SharedContext::new(self.router.clone(), task_locals, self.http2);

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
            execute_request(request, function, shared_context.task_locals).await
        }
        None => HyperResponse::builder()
            .status(StatusCode::NOT_FOUND)
            .body(full_http(b"Not Found".to_vec()))
            .unwrap(),
    };
    return response;
}

async fn execute_request(
    request: Request,
    function: PyObject,
    task_locals: Arc<pyo3_async_runtimes::TaskLocals>,
) -> HyperResponse<HTTPResponseBody> {
    // Create a channel for communication between Python and Rust
    let (tx, rx) = oneshot::channel();
    let response = Response::new(tx);
    let _ = execute_http_function(function, request, response, task_locals).await;
    // Create an async task that will handle the Python function call
    // tokio::spawn(async move { execute_http_function(function, request, response).await });

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
                    // Create the response with the proper body type
                    body_response.to_response()
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
