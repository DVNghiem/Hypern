use anyhow::Result;
use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::types::{request::Request, response::Response};

#[inline]
fn get_function_output<'a>(
    py: Python<'a>,
    function: Py<PyAny>,
    kwargs: &'a pyo3::Bound<'a, PyDict>,
) -> Result<pyo3::Bound<'a, pyo3::PyAny>, PyErr>
{
    let handler = function.bind(py).downcast()?;
    handler.call((), Some(kwargs))
}

#[inline]
pub async fn execute_http_function(
    function: Py<PyAny>,
    request: Request,
    response: Response,
) -> PyResult<Py<PyAny>> {
    let output = Python::with_gil(|py| {
        let kwargs = pyo3::types::PyDict::new(py);
        kwargs.set_item("request", request)?;
        kwargs.set_item("response", response)?;
        let function_output = get_function_output(py, function, &kwargs)?;
        pyo3_async_runtimes::tokio::into_future(function_output)
    })?
    .await?;
    Ok(output)
}
