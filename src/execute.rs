use std::sync::Arc;

use pyo3::prelude::*;

use crate::{request::Request, response::Response};

#[inline(always)]
pub async fn execute_http_function(
    function: Py<PyAny>,
    request: Request,
    response: Response,
    task_locals: Arc<pyo3_async_runtimes::TaskLocals>,
) -> PyResult<Py<PyAny>> {
    let output = Python::with_gil(|py| {
        let handler = function.bind(py).downcast()?;
        let function_output = handler.call1((request, response))?;
        pyo3_async_runtimes::into_future_with_locals(&task_locals, function_output)
    })?
    .await?;
    Ok(output)
}
