
use pyo3::{prelude::*, sync::GILOnceCell};
use std::convert::Into;

static CONTEXTVARS: GILOnceCell<PyObject> = GILOnceCell::new();
static CONTEXT: GILOnceCell<PyObject> = GILOnceCell::new();

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
