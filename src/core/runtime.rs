use crate::core::blocking::{BlockingRunner, BlockingRunnerError};
use pyo3::prelude::*;
use pyo3::types::PyTuple;
use std::future::Future;
use std::sync::Arc;
use tokio::runtime::Builder as RuntimeBuilder;
use tokio::task::JoinHandle;

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

    fn spawn_blocking<F, C>(&self, task: F, completion: C) -> Result<(), BlockingRunnerError>
    where
        F: FnOnce(Python) + Send + 'static,
        C: FnOnce(Result<(), BlockingRunnerError>) + Send + 'static;
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

    pub fn shutdown_python_workers(&self) {
        self.br.shutdown();
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
    pub fn block_on<F: Future>(&self, fut: F) -> F::Output {
        self.inner.block_on(fut)
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
    fn spawn_blocking<F, C>(&self, task: F, completion: C) -> Result<(), BlockingRunnerError>
    where
        F: FnOnce(Python) + Send + 'static,
        C: FnOnce(Result<(), BlockingRunnerError>) + Send + 'static,
    {
        self.innerb.run(task, completion)
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

#[inline]
pub fn future_into_py<F, C>(
    rt: &RuntimeRef,
    is_async: bool,
    args_builder: F,
    on_complete: C,
) -> Result<(), BlockingRunnerError>
where
    F: FnOnce(Python) -> (Py<PyAny>, Py<PyTuple>) + Send + 'static,
    C: FnOnce(Result<(), BlockingRunnerError>) + Send + 'static,
{
    if is_async {
        // Run async handlers on the event loop owned by this blocking worker.
        rt.spawn_blocking(
            move |py| {
                let (handler, args) = args_builder(py);

                // Call the handler to get its coroutine with minimum overhead.
                let coro_ptr = unsafe {
                    pyo3::ffi::PyObject_Call(handler.as_ptr(), args.as_ptr(), std::ptr::null_mut())
                };

                if coro_ptr.is_null() {
                    unsafe {
                        pyo3::ffi::PyErr_Print();
                    }
                    return;
                }

                let coroutine = unsafe { Bound::from_owned_ptr(py, coro_ptr) };
                let result = py
                    .import("asyncio")
                    .and_then(|asyncio| asyncio.call_method0("get_event_loop"))
                    .and_then(|event_loop| {
                        event_loop.call_method1("run_until_complete", (&coroutine,))
                    });
                if let Err(error) = result {
                    error.print(py);
                }
            },
            on_complete,
        )
    } else {
        // Run sync handlers directly on the blocking worker.
        rt.spawn_blocking(
            move |py| {
                let (handler, args) = args_builder(py);
                unsafe {
                    let result = pyo3::ffi::PyObject_Call(
                        handler.as_ptr(),
                        args.as_ptr(),
                        std::ptr::null_mut(),
                    );
                    if result.is_null() {
                        pyo3::ffi::PyErr_Print();
                    } else {
                        pyo3::ffi::Py_DECREF(result);
                    }
                }
            },
            on_complete,
        )
    }
}
