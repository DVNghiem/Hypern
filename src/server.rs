use crate::{
    application::Application,
    execute::execute_http_function,
    router::Router,
    runtime::TokioExecutor,
    socket::SocketHeld,
    {
        body::{full_http, HTTPResponseBody},
        request::Request,
        response::Response,
    },
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
use std::{thread, time::Duration};
use tokio::sync::oneshot;

struct SharedContext {
    router: Arc<Router>,
    task_locals: Arc<pyo3_async_runtimes::TaskLocals>,
    http2: bool,
}

impl SharedContext {
    fn new(
        router: Arc<Router>,
        task_locals: Arc<pyo3_async_runtimes::TaskLocals>,
        http2: bool,
    ) -> Self {
        Self {
            router,
            task_locals,
            http2,
        }
    }
}

#[pyclass]
pub struct Server {
    router: Arc<Router>,
    http2: bool,
}

#[pymethods]
impl Server {
    #[new]
    pub fn new() -> Self {
        Self {
            router: Arc::new(Router::default()),
            http2: false,
        }
    }

    pub fn set_router(&mut self, router: Router) {
        // Update router - convert to Arc for shared immutable access
        self.router = Arc::new(router);
    }

    pub fn set_application(&mut self, app: &Application) {
        // Update router from application
        self.router = Arc::new(app.get_router());
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

        let shared_context = Arc::new(SharedContext::new(
            self.router.clone(),
            task_locals,
            self.http2,
        ));

        thread::spawn(move || {
            let rt = tokio::runtime::Builder::new_multi_thread()
                .worker_threads(workers)
                .max_blocking_threads(max_blocking_threads)
                .thread_keep_alive(Duration::from_secs(5))
                .thread_name("hypern-worker")
                .thread_stack_size(1024 * 1024) // 1MB stack (minimal)
                .enable_io()
                .enable_time()
                .build()
                .unwrap();

            rt.block_on(async move {
                let listener = tokio::net::TcpListener::from_std(raw_socket.into()).unwrap();

                loop {
                    let (stream, _) = listener.accept().await.unwrap();
                    
                    // Configure stream for maximum performance
                    let _ = stream.set_nodelay(true);
                    let _ = stream.set_linger(None);
                    
                    let io = TokioIo::new(stream);
                    let shared_context = shared_context.clone();
                    
                    // Use a lighter-weight spawn for connection handling
                    tokio::task::spawn(async move {
                        let svc = service_fn(|req: hyper::Request<hyper::body::Incoming>| {
                            let ctx = shared_context.clone();
                            async move {
                                let response = http_service(req, ctx).await;
                                Ok::<_, hyper::Error>(response)
                            }
                        });

                        let result = match shared_context.http2 {
                            true => {
                                http2::Builder::new(TokioExecutor)
                                    .keep_alive_timeout(Duration::from_secs(10))
                                    .keep_alive_interval(Duration::from_secs(2))
                                    .max_concurrent_streams(Some(4000))
                                    .max_frame_size(Some(8192))
                                    .serve_connection(io, svc)
                                    .await
                            }
                            false => {
                                http1::Builder::new()
                                    .keep_alive(true)
                                    .half_close(true)
                                    .max_buf_size(8192)
                                    .serve_connection(io, svc)
                                    .with_upgrades()
                                    .await
                            }
                        };
                        
                        if let Err(e) = result {
                            eprintln!("Connection error: {}", e);
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
    shared_context: Arc<SharedContext>,
) -> HyperResponse<HTTPResponseBody> {
    let path = req.uri().path();
    let method = req.method().as_str();

    // Fast path: direct router lookup without cloning
    let route = shared_context.router.find_matching_route(path, method);

    match route {
        Some((route, _path_params)) => {
            let function = route.function;
            let request = Request::new(req).await;
            // request.path_params = path_params;
            execute_request(request, function, shared_context.task_locals.clone()).await
        }
        None => HyperResponse::builder()
            .status(StatusCode::NOT_FOUND)
            .body(full_http(b"Not Found".to_vec()))
            .unwrap(),
    }
}

async fn execute_request(
    request: Request,
    function: PyObject,
    task_locals: Arc<pyo3_async_runtimes::TaskLocals>,
) -> HyperResponse<HTTPResponseBody> {
    // Create a channel for communication between Python and Rust
    let (tx, rx) = oneshot::channel();
    let response = Response::new(tx);
    
    // Execute Python function on a blocking thread pool for better isolation
    tokio::task::spawn(execute_http_function(function, request, response, task_locals));

    // Wait for the response from the Python side with a shorter timeout
    let response_result = match tokio::time::timeout(Duration::from_secs(10), rx).await {
        Ok(Ok(py_response)) => Some(py_response),
        Ok(Err(_)) => None,
        Err(_) => None,
    };

    // Convert the response or return an error
    match response_result {
        Some(py_response) => {
            match py_response {
                crate::response::PyResponse::Body(body_response) => {
                    body_response.to_response()
                }
            }
        }
        None => {
            HyperResponse::builder()
                .status(StatusCode::INTERNAL_SERVER_ERROR)
                .body(full_http("Handler error"))
                .unwrap()
        }
    }
}
