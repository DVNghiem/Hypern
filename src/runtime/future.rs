use pyo3::{prelude::*, types::PyDict};
use std::{
    future::Future,
    sync::{Arc, Mutex},
    time::Duration,
};
use tokio::sync::oneshot;
use tokio::{
    runtime::Builder as RuntimeBuilder,
    task::{JoinHandle, LocalSet},
};

#[cfg(unix)]
use super::callbacks::PyFutureAwaitable;

use super::callbacks::PyIterAwaitable;
use super::conversion::FutureResultToPy;
use super::{
    asyncio::{asyncio, copy_context, ensure_future},
    blocking::BlockingRunner,
};

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
    fn py_event_loop(&self, py: Python) -> PyObject;
}

pub(crate) struct RuntimeWrapper {
    pub inner: tokio::runtime::Runtime,
    br: Arc<BlockingRunner>,
    pr: Arc<PyObject>,
}

impl RuntimeWrapper {
    pub fn new(
        blocking_threads: usize,
        py_threads: usize,
        py_threads_idle_timeout: u64,
        py_loop: Arc<PyObject>,
    ) -> Self {
        Self {
            inner: default_runtime(blocking_threads),
            br: BlockingRunner::new(py_threads, py_threads_idle_timeout).into(),
            pr: py_loop,
        }
    }

    pub fn with_runtime(
        rt: tokio::runtime::Runtime,
        py_threads: usize,
        py_threads_idle_timeout: u64,
        py_loop: Arc<PyObject>,
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
    innerp: Arc<PyObject>,
}

impl RuntimeRef {
    pub fn new(rt: tokio::runtime::Handle, br: Arc<BlockingRunner>, pyloop: Arc<PyObject>) -> Self {
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
    fn py_event_loop(&self, py: Python) -> PyObject {
        self.innerp.clone_ref(py)
    }
}

fn default_runtime(blocking_threads: usize) -> tokio::runtime::Runtime {
    RuntimeBuilder::new_current_thread()
        .max_blocking_threads(blocking_threads)
        .enable_all()
        .build()
        .unwrap()
}

pub(crate) fn init_runtime(
    threads: usize,
    blocking_threads: usize,
    py_threads: usize,
    py_threads_idle_timeout: u64,
    py_loop: Arc<PyObject>,
) -> RuntimeWrapper {
    RuntimeWrapper::with_runtime(
        RuntimeBuilder::new_multi_thread()
            .worker_threads(threads)
            .max_blocking_threads(blocking_threads)
            .thread_keep_alive(Duration::from_secs(5 * 60)) // 5 minutes
            .thread_name("hypern-worker")
            .enable_all()
            .build()
            .unwrap(),
        py_threads,
        py_threads_idle_timeout,
        py_loop,
    )
}


// NOTE:
//  `future_into_py_iter` relies on what CPython refers as "bare yield".
//  This is generally ~55% faster than `pyo3_asyncio.future_into_py` implementation.
//  It consumes more cpu-cycles than `future_into_py_futlike`,
//  but for "quick" operations it's something like 12% faster.
#[allow(unused_must_use)]
pub(crate) fn future_into_py_iter<R, F>(rt: R, py: Python, fut: F) -> PyResult<PyObject>
where
    R: Runtime + ContextExt + Clone,
    F: Future<Output = FutureResultToPy> + Send + 'static,
{
    let aw = Py::new(py, PyIterAwaitable::new())?;
    let py_fut = aw.clone_ref(py);
    let rth = rt.clone();

    rt.spawn(async move {
        let result = fut.await;
        rth.spawn_blocking(move |py| PyIterAwaitable::set_result(aw, py, result));
    });

    Ok(py_fut.into_py(py))
}

// NOTE:
//  `future_into_py_futlike` relies on an `asyncio.Future` like implementation.
//  This is generally ~38% faster than `pyo3_asyncio.future_into_py` implementation.
//  It won't consume more cpu-cycles than standard asyncio implementation,
//  and for "long" operations it's something like 6% faster than `future_into_py_iter`.
#[allow(unused_must_use)]
#[cfg(unix)]
pub(crate) fn future_into_py_futlike<R, F>(rt: R, py: Python, fut: F) -> PyResult<PyObject>
where
    R: Runtime + ContextExt + Clone,
    F: Future<Output = FutureResultToPy> + Send + 'static,
{
    let event_loop = rt.py_event_loop(py);
    let (aw, cancel_tx) = PyFutureAwaitable::new(event_loop).to_spawn(py)?;
    let py_fut = aw.clone_ref(py);
    let rth = rt.clone();

    rt.spawn(async move {
        tokio::select! {
            result = fut => rth.spawn_blocking(move |py| PyFutureAwaitable::set_result(aw, py, result)),
            () = cancel_tx.notified() => rth.spawn_blocking(move |_py| drop(aw)),
        }
    });

    Ok(py_fut.into_py(py))
}

#[allow(unused_must_use)]
pub(crate) fn run_until_complete<F>(
    rt: RuntimeWrapper,
    event_loop: Py<PyAny>,
    fut: F,
) -> PyResult<()>
where
    F: Future<Output = PyResult<()>> + Send + 'static,
{
    let result_tx = Arc::new(Mutex::new(None));
    let result_rx = Arc::clone(&result_tx);

    let py = unsafe { Python::assume_gil_acquired() };

    let py_fut = event_loop.call_method0(py, "create_future")?;
    let loop_tx = event_loop.clone();
    let future_tx = py_fut.clone();

    rt.inner.spawn(async move {
        let _ = fut.await;
        if let Ok(mut result) = result_tx.lock() {
            *result = Some(());
        }

        // NOTE: we don't care if we block the runtime.
        //       `run_until_complete` is used only for the workers main loop.
        Python::with_gil(move |py| {
            let res_method = future_tx.getattr(py, "set_result").unwrap();
            let _ = loop_tx.call_method(py, "call_soon_threadsafe", (res_method, py.None()), None);
            drop(future_tx);
            drop(loop_tx);
            // future_tx.drop_ref(py);
            // loop_tx.drop_ref(py);
        });
    });

    event_loop.call_method1(py, "run_until_complete", (py_fut,))?;

    result_rx.lock().unwrap().take().unwrap();
    Ok(())
}

pub(crate) fn block_on_local<F>(rt: &RuntimeWrapper, local: LocalSet, fut: F)
where
    F: Future + 'static,
{
    local.block_on(&rt.inner, fut);
}

#[pyclass]
struct PyTaskCompleter {
    tx: Option<oneshot::Sender<PyResult<PyObject>>>,
}

#[pymethods]
impl PyTaskCompleter {
    #[pyo3(signature = (task))]
    pub fn __call__(&mut self, py: Python, task: Py<PyAny>) -> PyResult<()> {
        let result = match task.call_method0(py, "result") {
            Ok(val) => Ok(val.into()),
            Err(e) => Err(e),
        };

        // unclear to me whether or not this should be a panic or silent error.
        //
        // calling PyTaskCompleter twice should not be possible, but I don't think it really hurts
        // anything if it happens.
        if let Some(tx) = self.tx.take() {
            if tx.send(result).is_err() {
                // cancellation is not an error
            }
        }

        Ok(())
    }
}

#[pyclass]
struct PyEnsureFuture {
    awaitable: PyObject,
    tx: Option<oneshot::Sender<PyResult<PyObject>>>,
}

#[pymethods]
impl PyEnsureFuture {
    pub fn __call__(&mut self) -> PyResult<()> {
        Python::with_gil(|py| {
            let task = ensure_future(py, self.awaitable.clone_ref(py))?;
            let on_complete = PyTaskCompleter { tx: self.tx.take() };
            task.call_method1(py, "add_done_callback", (on_complete,))?;
            Ok(())
        })
    }
}

pub fn into_future<R>(
    rt: R,
    awaitable: &PyAny,
) -> PyResult<impl Future<Output = PyResult<PyObject>> + Send>
where
    R: Runtime + ContextExt + Clone,
{
    let py = awaitable.py();
    // Convert Python objects to owned values that can be sent between threads
    let awaitable_py = awaitable.into_py(py);
    let event_loop = rt.py_event_loop(py);
    let (tx, rx) = oneshot::channel();

    // Clone these values to avoid capturing references to Python objects
    let event_loop_py = event_loop.clone_ref(py);

    // Prepare any context needed before spawning the async task
    let ctx = copy_context(py).into_py(py);

    let rt_clone = rt.clone();
    rt_clone.spawn_blocking(move |py| {
        let args = (PyEnsureFuture {
            awaitable: awaitable_py.clone_ref(py),
            tx: Some(tx),
        },);
        let kwargs = PyDict::new(py);
        kwargs.set_item("context", ctx.as_ref(py)).unwrap();
        event_loop_py
            .call_method(py, "call_soon_threadsafe", args, Some(&kwargs))
            .unwrap();
    });

    Ok(async move {
        match rx.await {
            Ok(item) => item,
            Err(_) => Python::with_gil(|py| {
                Err(PyErr::from_value(
                    asyncio(py)
                        .unwrap()
                        .call_method0(py, "CancelledError")
                        .unwrap()
                        .into_ref(py),
                ))
            }),
        }
    })
}
