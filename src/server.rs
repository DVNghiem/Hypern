use crate::{
    database::{
        context::{
            get_session_database, get_sql_connect, insert_sql_session, remove_sql_session,
            set_sql_connect,
        },
        sql::{config::DatabaseConfig, connection::DatabaseConnection},
    },
    executor::{execute_http_function, execute_middleware_function, execute_startup_handler},
    instants::create_mem_pool,
    middlewares::base::{Middleware, MiddlewareConfig},
    router::router::Router,
    types::{function_info::FunctionInfo, middleware::MiddlewareReturn, request::Request},
    ws::{router::WebsocketRouter, socket::SocketHeld, websocket::websocket_handler},
};
use dashmap::DashMap;
use futures::future::join_all;
use pyo3::{prelude::*, types::PyDict};
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
use tower::ServiceBuilder;

use axum::{
    body::Body,
    extract::{Request as HttpRequest, WebSocketUpgrade},
    http::StatusCode,
    response::{IntoResponse, Response as ServerResponse},
    routing::{any, delete, get, head, options, patch, post, put, trace},
    Extension, Router as RouterServer,
};

use crate::di::DependencyInjection;
use tower_http::{
    trace::{DefaultOnResponse, TraceLayer},
    LatencyUnit,
    {compression::CompressionLayer, decompression::RequestDecompressionLayer},
};
use tracing::{debug, Level};
use tracing_subscriber::{fmt, layer::SubscriberExt, util::SubscriberInitExt};

static STARTED: AtomicBool = AtomicBool::new(false);

#[pyclass]
pub struct Server {
    router: Arc<RwLock<Router>>,
    websocket_router: Arc<WebsocketRouter>,
    startup_handler: Option<Arc<FunctionInfo>>,
    shutdown_handler: Option<Arc<FunctionInfo>>,
    injected: Arc<DependencyInjection>,
    middlewares: Arc<Middleware>,
    extra_headers: Arc<DashMap<String, String>>,
    auto_compression: bool,
    database_config: Option<DatabaseConfig>,
    mem_pool_min_capacity: usize,
    mem_pool_max_capacity: usize,
}

#[pymethods]
impl Server {
    #[new]
    pub fn new() -> Self {
        Self {
            router: Arc::new(RwLock::new(Router::default())),
            websocket_router: Arc::new(WebsocketRouter::default()),
            startup_handler: None,
            shutdown_handler: None,
            injected: Arc::new(DependencyInjection::new()),
            middlewares: Arc::new(Middleware::new()),
            extra_headers: Arc::new(DashMap::new()),
            auto_compression: true,
            database_config: None,
            mem_pool_min_capacity: 10,
            mem_pool_max_capacity: 100,
        }
    }

    pub fn set_router(&mut self, router: Router) {
        // Update router
        self.router = Arc::new(RwLock::new(router));
    }

    pub fn set_websocket_router(&mut self, websocket_router: WebsocketRouter) {
        self.websocket_router = Arc::new(websocket_router);
    }

    pub fn inject(&mut self, key: &str, value: Py<PyAny>) {
        let _ = self.injected.add_dependency(key, value);
    }

    pub fn set_injected(&mut self, injected: Py<PyDict>) {
        self.injected = Arc::new(DependencyInjection::from_object(injected));
    }

    pub fn set_before_hooks(&mut self, hooks: Vec<(FunctionInfo, MiddlewareConfig)>) {
        Arc::get_mut(&mut self.middlewares)
            .unwrap()
            .set_before_hooks(hooks);
    }

    pub fn set_after_hooks(&mut self, hooks: Vec<(FunctionInfo, MiddlewareConfig)>) {
        Arc::get_mut(&mut self.middlewares)
            .unwrap()
            .set_after_hooks(hooks);
    }

    pub fn set_response_headers(&mut self, headers: HashMap<String, String>) {
        for (key, value) in headers {
            self.extra_headers.insert(key, value);
        }
    }

    pub fn set_startup_handler(&mut self, handler: FunctionInfo) {
        self.startup_handler = Some(Arc::new(handler));
    }

    pub fn set_shutdown_handler(&mut self, handler: FunctionInfo) {
        self.shutdown_handler = Some(Arc::new(handler));
    }

    pub fn set_auto_compression(&mut self, enabled: bool) {
        self.auto_compression = enabled;
    }

    pub fn set_database_config(&mut self, config: DatabaseConfig) {
        self.database_config = Some(config);
    }

    pub fn set_mem_pool_capacity(&mut self, min_capacity: usize, max_capacity: usize) {
        self.mem_pool_min_capacity = min_capacity;
        self.mem_pool_max_capacity = max_capacity;
    }

    pub fn start(
        &mut self,
        py: Python,
        socket: &PyCell<SocketHeld>,
        workers: usize,
        max_blocking_threads: usize,
    ) -> PyResult<()> {
        tracing_subscriber::registry()
            .with(
                tracing_subscriber::EnvFilter::try_from_default_env()
                    .unwrap_or_else(|_| "debug".into()),
            )
            .with(fmt::layer().with_target(false).with_level(true))
            .init();

        if STARTED
            .compare_exchange(false, true, SeqCst, Relaxed)
            .is_err()
        {
            return Ok(());
        }

        let raw_socket = socket.try_borrow_mut()?.get_socket();
        let asyncio = py.import("asyncio")?;
        let event_loop = asyncio.call_method0("get_event_loop")?;

        let router = Arc::clone(&self.router);
        let websocket_router = Arc::clone(&self.websocket_router);

        let startup_handler = self.startup_handler.clone();
        let shutdown_handler = self.shutdown_handler.clone();

        let task_locals = Arc::new(pyo3_asyncio::TaskLocals::new(event_loop).copy_context(py)?);
        let task_local_copy = Arc::clone(&task_locals);

        let injected = Arc::clone(&self.injected);
        let copy_middlewares = Arc::clone(&self.middlewares);
        let extra_headers = Arc::clone(&self.extra_headers);
        let auto_compression = self.auto_compression;
        let database_config = self.database_config.clone();
        let mem_pool_min_capacity = self.mem_pool_min_capacity;
        let mem_pool_max_capacity = self.mem_pool_max_capacity;

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
                create_mem_pool(mem_pool_min_capacity, mem_pool_max_capacity);

                let _ = execute_startup_handler(startup_handler, &Arc::clone(&task_locals)).await;

                let mut app = RouterServer::new();

                // handle logic for each route with pyo3
                for route in router.read().unwrap().iter() {
                    let task_locals = Arc::clone(&task_locals);
                    let function = route.function.clone();
                    let copy_middlewares = Arc::clone(&copy_middlewares);
                    let extra_headers = Arc::clone(&extra_headers);
                    let handler = move |req| {
                        mapping_method(req, function, task_locals, copy_middlewares, extra_headers)
                    };

                    app = app.route(
                        &route.path,
                        match route.method.as_str() {
                            "GET" => get(handler),
                            "POST" => post(handler),
                            "PUT" => put(handler),
                            "DELETE" => delete(handler),
                            "PATCH" => patch(handler),
                            "HEAD" => head(handler),
                            "OPTIONS" => options(handler),
                            "TRACE" => trace(handler),
                            _ => any(handler),
                        },
                    );
                }

                // handle logic for each websocket route with pyo3
                for ws_route in websocket_router.iter() {
                    let ws_route_copy = ws_route.clone();
                    let handler = move |ws: WebSocketUpgrade| {
                        websocket_handler(ws_route_copy.handler.clone(), ws)
                    };
                    app = app.route(&ws_route.path, any(handler));
                }

                match database_config {
                    Some(config) => {
                        let database = DatabaseConnection::new(config).await;
                        set_sql_connect(database);
                    }
                    None => {}
                };

                app = app.layer(Extension(injected));
                app = app.layer(
                    TraceLayer::new_for_http().on_response(
                        DefaultOnResponse::new()
                            .level(Level::INFO)
                            .latency_unit(LatencyUnit::Millis),
                    ),
                );
                if auto_compression {
                    // Add compression and decompression layers
                    app = app.layer(
                        ServiceBuilder::new()
                            .layer(RequestDecompressionLayer::new())
                            .layer(CompressionLayer::new()),
                    )
                }
                debug!("Application started");
                // run our app with hyper, listening globally on port 3000
                let listener = tokio::net::TcpListener::from_std(raw_socket.into()).unwrap();
                axum::serve(listener, app).await.unwrap();
            });
        });

        let event_loop = (*event_loop).call_method0("run_forever");
        if event_loop.is_err() {
            if let Some(function) = shutdown_handler {
                if function.is_async {
                    pyo3_asyncio::tokio::run_until_complete(
                        task_local_copy.event_loop(py),
                        pyo3_asyncio::into_future_with_locals(
                            &task_local_copy.clone(),
                            function.handler.as_ref(py).call0()?,
                        )
                        .unwrap(),
                    )
                    .unwrap();
                } else {
                    Python::with_gil(|py| function.handler.call0(py))?;
                }
            }

            exit(0);
        }
        Ok(())
    }
}

async fn inject_database(request_id: Arc<String>) {
    let database = get_sql_connect();
    match database {
        Some(database) => {
            insert_sql_session(&request_id, database.transaction().await);
        }
        None => {}
    }
}

fn free_database(request_id: String) {
    tokio::task::spawn(async move {
        let tx = get_session_database(&request_id);
        tx.unwrap().commit_internal().await;
        remove_sql_session(&request_id);
    });
}

async fn execute_request(
    req: HttpRequest<Body>,
    function: FunctionInfo,
    middlewares: Arc<Middleware>,
    extra_headers: Arc<DashMap<String, String>>,
) -> ServerResponse {
    let response_builder = ServerResponse::builder();

    let deps = req.extensions().get::<Arc<DependencyInjection>>().cloned();

    let mut request = Request::from_request(req).await;
    let request_id = Arc::new(request.context_id.clone());

    inject_database(Arc::clone(&request_id)).await;

    // Execute before middlewares in parallel where possible
    let before_results = join_all(
        middlewares
            .get_before_hooks()
            .into_iter()
            .filter(|(_, config)| !config.is_conditional)
            .map(|(middleware, _)| {
                let request = request.clone();
                let middleware = middleware.clone();
                async move { execute_middleware_function(&request, &middleware).await }
            }),
    )
    .await;

    // Process results and handle any errors
    for result in before_results {
        match result {
            Ok(MiddlewareReturn::Request(r)) => request = r,
            Ok(MiddlewareReturn::Response(r)) => return r.to_axum_response(&extra_headers),
            Err(e) => {
                return response_builder
                    .body(Body::from(format!("Error: {}", e)))
                    .unwrap();
            }
        }
    }

    // Execute conditional middlewares sequentially
    for (middleware, config) in middlewares.get_before_hooks() {
        if config.is_conditional {
            match execute_middleware_function(&request, &middleware).await {
                Ok(MiddlewareReturn::Request(r)) => request = r,
                Ok(MiddlewareReturn::Response(r)) => return r.to_axum_response(&extra_headers),
                Err(e) => {
                    return ServerResponse::builder()
                        .status(StatusCode::INTERNAL_SERVER_ERROR)
                        .body(Body::from(format!("Error: {}", e)))
                        .unwrap();
                }
            }
        }
    }

    // Execute the main handler
    let mut response = execute_http_function(&request, &function, deps)
        .await
        .unwrap();

    // mapping context id
    response.context_id = request.context_id;

    // Execute after middlewares with similar optimization
    for (after_middleware, _) in middlewares.get_after_hooks() {
        response = match execute_middleware_function(&response, &after_middleware).await {
            Ok(MiddlewareReturn::Request(_)) => {
                return response_builder
                    .status(StatusCode::INTERNAL_SERVER_ERROR)
                    .body(Body::from("Middleware returned a response"))
                    .unwrap();
            }
            Ok(MiddlewareReturn::Response(r)) => {
                let response = r;
                response
            }
            Err(e) => {
                return response_builder
                    .status(StatusCode::INTERNAL_SERVER_ERROR)
                    .body(Body::from(e.to_string()))
                    .unwrap();
            }
        };
    }

    free_database(request_id.to_string());

    response.to_axum_response(&extra_headers)
}

async fn mapping_method(
    req: HttpRequest<Body>,
    function: FunctionInfo,
    task_locals: Arc<pyo3_asyncio::TaskLocals>,
    middlewares: Arc<Middleware>,
    extra_headers: Arc<DashMap<String, String>>,
) -> impl IntoResponse {
    pyo3_asyncio::tokio::scope(
        task_locals.as_ref().to_owned(),
        execute_request(req, function, middlewares, extra_headers),
    )
    .await
}
