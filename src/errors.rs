use pyo3::{create_exception, exceptions::PyRuntimeError};

create_exception!(_hypern, RequestError, PyRuntimeError, "RequestError");
create_exception!(_hypern, RequestClosed, PyRuntimeError, "RequestClosed");

macro_rules! error_request {
    () => {
        Err(crate::errors::RequestError::new_err("Request protocol error").into())
    };
}

macro_rules! error_stream {
    () => {
        Err(crate::errors::RequestClosed::new_err("Request transport is closed").into())
    };
}

pub(crate) use error_request;
pub(crate) use error_stream;
