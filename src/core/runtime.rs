use crate::{core::blocking::BlockingRunner, http::callback::PyFutureAwaitable};
use pyo3::prelude::*;
use pyo3::types::{PyTuple, PyDict};
use std::{future::Future, sync::Arc};
use tokio::task::JoinHandle;
use tokio::runtime::Builder as RuntimeBuilder;

pub trait JoinError {
    #[allow(dead_code)]
    fn is_panic(&self) -> bool;
}

pub trait Runtime: Send + 'static {
    type JoinError: JoinError + Send;
    type JoinHandle: Future<Output = Result<(), Self::JoinError>> + Send;

    fn spawn<F>(&self, fut: F) -> Self::JoinHandle
    where
        F: Future<Output = ()> + Send + 'static;

    fn spawn_blocking<F>(&self, task: F)
    where
        F: FnOnce(Python) + Send + 'static;
}

pub trait ContextExt: Runtime {
    fn py_event_loop(&self, py: Python) -> Py<PyAny>;
}

#[derive(Debug)]
pub(crate) struct RuntimeWrapper {
    pub inner: tokio::runtime::Runtime,
    br: Arc<BlockingRunner>,
    pr: Arc<Py<PyAny>>,
}

impl RuntimeWrapper {
    pub fn with_runtime(
        rt: tokio::runtime::Runtime,
        py_threads: usize,
        py_threads_idle_timeout: u64,
        py_loop: Arc<Py<PyAny>>,
    ) -> Self {
        Self {
            inner: rt,
            br: BlockingRunner::new(py_threads, py_threads_idle_timeout).into(),
            pr: py_loop,
        }
    }

    pub fn handler(&self) -> RuntimeRef {
        RuntimeRef::new(
            self.inner.handle().clone(),
            self.br.clone(),
            self.pr.clone(),
        )
    }
}

#[derive(Clone)]
pub struct RuntimeRef {
    pub inner: tokio::runtime::Handle,
    innerb: Arc<BlockingRunner>,
    innerp: Arc<Py<PyAny>>,
}

impl RuntimeRef {
    pub(crate) fn new(
        rt: tokio::runtime::Handle,
        br: Arc<BlockingRunner>,
        pyloop: Arc<Py<PyAny>>,
    ) -> Self {
        Self {
            inner: rt, 
            innerb: br,
            innerp: pyloop,
        }
    }
}

impl JoinError for tokio::task::JoinError {
    fn is_panic(&self) -> bool {
        tokio::task::JoinError::is_panic(self)
    }
}

impl Runtime for RuntimeRef {
    type JoinError = tokio::task::JoinError;
    type JoinHandle = JoinHandle<()>;

    fn spawn<F>(&self, fut: F) -> Self::JoinHandle
    where
        F: Future<Output = ()> + Send + 'static,
    {
        self.inner.spawn(fut)
    }

    #[inline]
    fn spawn_blocking<F>(&self, task: F)
    where
        F: FnOnce(Python) + Send + 'static,
    {
        _ = self.innerb.run(task);
    }
}

impl ContextExt for RuntimeRef {
    fn py_event_loop(&self, py: Python) -> Py<PyAny> {
        self.innerp.clone_ref(py)
    }
}

pub(crate) fn init_runtime_mt(
    threads: usize,
    blocking_threads: usize,
    py_threads: usize,
    py_threads_idle_timeout: u64,
    py_loop: Arc<Py<PyAny>>,
) -> RuntimeWrapper {
    RuntimeWrapper::with_runtime(
        RuntimeBuilder::new_multi_thread()
            .worker_threads(threads)
            .max_blocking_threads(blocking_threads)
            .enable_all()
            .build()
            .unwrap(),
        py_threads,
        py_threads_idle_timeout,
        py_loop,
    )
}

#[allow(dead_code)]
#[warn(unused_must_use)]
pub(crate) fn future_into_py<R, F>(rt: R, py: Python, fut: F) -> PyResult<Bound<PyAny>>
where
    R: Runtime + ContextExt + Clone,
    F: Future<Output = Py<PyAny>> + Send + 'static,
{
    let event_loop = rt.py_event_loop(py);
    let (aw, cancel_tx) = PyFutureAwaitable::new(event_loop).to_spawn(py)?;
    let py_fut = aw.clone_ref(py);
    let rth = rt.clone();

    let _ = rt.spawn(async move {
        tokio::select! {
            biased;
            result = fut => rth.spawn_blocking(move |py| PyFutureAwaitable::set_result(aw, py, result)),
            () = cancel_tx.notified() => rth.spawn_blocking(move |py| aw.drop_ref(py)),
        }
    });
    Ok(py_fut.into_any().into_bound(py))
}

/// Handles both sync and async Python handlers via rt (tokio) or br (blocking runner)
pub(crate) fn future_into_py_handler<F, A>(
    rt: &RuntimeRef,
    handler: Py<PyAny>,
    is_async: bool,
    args_provider: A,
    on_complete: F,
) where
    F: FnOnce() + Send + 'static,
    A: FnOnce(Python) -> Py<PyTuple> + Send + 'static,
{
    if is_async {
        // Async handler: call handler, schedule on event loop
        let on_complete = Arc::new(std::sync::Mutex::new(Some(on_complete)));
        rt.spawn_blocking(move |py| {
            let handler_bound = handler.bind(py);
            let args = args_provider(py);
            match handler_bound.call1(args) {
                Ok(coro) => {
                    let asyncio = crate::core::global::get_asyncio(py);
                    let loop_ = crate::core::global::get_event_loop(py);
                    match asyncio.call_method1(py, "call_soon_threadsafe", (coro, loop_)) {
                        Ok(future) => {
                            // Create callback wrapper that calls on_complete
                            let on_complete_clone = on_complete.clone();
                            let callback = pyo3::types::PyCFunction::new_closure(
                                py,
                                None,
                                None,
                                move |_args: &Bound<PyTuple>, _kwargs: Option<&Bound<PyDict>>| -> PyResult<()> {
                                    if let Some(callback) = on_complete_clone.lock().unwrap().take() {
                                        callback();
                                    }
                                    Ok(())
                                },
                            );
                            if let Ok(callback) = callback {
                                let _ = future.call_method1(py, "add_done_callback", (callback,));
                            } else {
                                if let Some(callback) = on_complete.lock().unwrap().take() {
                                    callback();
                                }
                            }
                        }
                        Err(e) => {
                            tracing::error!("Failed to schedule coroutine: {:?}", e);
                            if let Some(callback) = on_complete.lock().unwrap().take() {
                                callback();
                            }
                        }
                    }
                }
                Err(e) => {
                    tracing::error!("Failed to call async handler: {:?}", e);
                    if let Some(callback) = on_complete.lock().unwrap().take() {
                        callback();
                    }
                }
            }
        });
    } else {
        // Sync handler: call directly on blocking runner
        rt.spawn_blocking(move |py| {
            let handler_bound = handler.bind(py);
            let args = args_provider(py);
            match handler_bound.call1(args) {
                Ok(_) => {}
                Err(e) => {
                    tracing::error!("Failed to call sync handler: {:?}", e);
                }
            }
            on_complete();
        });
    }
}

