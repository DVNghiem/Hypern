use crate::core::blocking::BlockingRunner;
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

#[inline]
pub fn future_into_py<F, C>(rt: &RuntimeRef, is_async: bool, args_builder: F, on_complete: C)
where
    F: FnOnce(Python) -> (Py<PyAny>, Py<PyTuple>) + Send + 'static,
    C: FnOnce() + Send + 'static,
{
    if is_async {
        // For async handlers: call and step coroutine on blocking thread
        rt.spawn_blocking(move |py| {
            let (handler, args) = args_builder(py);

            // Call handler to get coroutine and step it to completion
            // Using raw C API for maximum speed
            unsafe {
                let coro_ptr =
                    pyo3::ffi::PyObject_Call(handler.as_ptr(), args.as_ptr(), std::ptr::null_mut());

                if coro_ptr.is_null() {
                    pyo3::ffi::PyErr_Print();
                    on_complete();
                    return;
                }

                // Step coroutine to completion
                let none_ptr = pyo3::ffi::Py_None();
                loop {
                    let mut result_ptr = std::ptr::null_mut::<pyo3::ffi::PyObject>();
                    let send_result =
                        pyo3::ffi::PyIter_Send(coro_ptr, none_ptr, &raw mut result_ptr);

                    match send_result {
                        pyo3::ffi::PySendResult::PYGEN_RETURN => {
                            if !result_ptr.is_null() {
                                pyo3::ffi::Py_DECREF(result_ptr);
                            }
                            pyo3::ffi::Py_DECREF(coro_ptr);
                            break;
                        }
                        pyo3::ffi::PySendResult::PYGEN_NEXT => {
                            if !result_ptr.is_null() {
                                pyo3::ffi::Py_DECREF(result_ptr);
                            }
                            continue;
                        }
                        pyo3::ffi::PySendResult::PYGEN_ERROR => {
                            if pyo3::ffi::PyErr_ExceptionMatches(pyo3::ffi::PyExc_StopIteration)
                                != 0
                            {
                                pyo3::ffi::PyErr_Clear();
                            } else {
                                pyo3::ffi::PyErr_Print();
                            }
                            pyo3::ffi::Py_DECREF(coro_ptr);
                            break;
                        }
                    }
                }
            }
            on_complete();
        });
    } else {
        // For sync handlers: run directly on blocking thread using raw C API
        rt.spawn_blocking(move |py| {
            let (handler, args) = args_builder(py);
            unsafe {
                let result =
                    pyo3::ffi::PyObject_Call(handler.as_ptr(), args.as_ptr(), std::ptr::null_mut());
                if result.is_null() {
                    pyo3::ffi::PyErr_Print();
                } else {
                    pyo3::ffi::Py_DECREF(result);
                }
            }
            on_complete();
        });
    }
}
