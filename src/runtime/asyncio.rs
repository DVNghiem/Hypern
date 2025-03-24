
use pyo3::{prelude::*, sync::GILOnceCell};
use std::convert::Into;

static CONTEXTVARS: GILOnceCell<PyObject> = GILOnceCell::new();
static CONTEXT: GILOnceCell<PyObject> = GILOnceCell::new();
static ENSURE_FUTURE: GILOnceCell<PyObject> = GILOnceCell::new();
static ASYNCIO: GILOnceCell<PyObject> = GILOnceCell::new();

pub fn asyncio(py: Python) -> PyResult<Py<PyAny>> {
    ASYNCIO
        .get_or_try_init(py, || Ok(py.import("asyncio")?.into()))
        .map(|asyncio| asyncio.into_py(py))
}

pub fn ensure_future<'p>(py: Python<'p>, awaitable: Py<PyAny>) -> PyResult<Py<PyAny>> {
    ENSURE_FUTURE
        .get_or_try_init(py, || -> PyResult<PyObject> {
            Ok(asyncio(py)?.getattr(py, "ensure_future")?.into())
        })?
        .into_py(py)
        .call1(py, (awaitable,))
}

fn contextvars(py: Python) -> PyResult<&PyAny> {
    Ok(CONTEXTVARS
        .get_or_try_init(py, || py.import("contextvars").map(Into::into))?
        .as_ref(py))
}

#[allow(dead_code)]
pub(crate) fn empty_context(py: Python) -> PyResult<&PyAny> {
    Ok(CONTEXT
        .get_or_try_init(py, || {
            contextvars(py)?
                .getattr("Context")?
                .call0()
                .map(std::convert::Into::into)
        })?
        .as_ref(py))
}

pub(crate) fn copy_context(py: Python) -> PyObject {
    let ctx = unsafe {
        let ptr = pyo3::ffi::PyContext_CopyCurrent();
        ptr
    };
    unsafe { PyObject::from_borrowed_ptr(py, ctx) }
}
