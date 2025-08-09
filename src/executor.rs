use std::sync::Arc;

use pyo3::{prelude::*, types::PyDict};

use crate::{
    types::{
        function_info::FunctionInfo, request::Request,
        response::Response,
    }
};
use pyo3_asyncio::TaskLocals;


#[inline]
fn get_function_output<'a, T>(
    function: &'a FunctionInfo,
    py: Python<'a>,
    function_args: &T,
) -> Result<&'a PyAny, PyErr>
where
    T: ToPyObject,
{
    let handler = function.handler.as_ref(py);

    let kwargs = PyDict::new(py);

    let result = handler.call(
        (function_args.to_object(py),),
        Some(kwargs),
    );

    result

}

#[inline]
pub async fn execute_http_function(
    request: &Request,
    function: &FunctionInfo,
) -> PyResult<Response> {
    if function.is_async {
        let output = Python::with_gil(|py| {
            let function_output = get_function_output(function, py, request)?;
            pyo3_asyncio::tokio::into_future(function_output)
        })?
        .await?;

        return Python::with_gil(|py| -> PyResult<Response> { output.extract(py) });
    };

    Python::with_gil(|py| -> PyResult<Response> {
        get_function_output(function, py, request)?.extract()
    })
}

pub async fn execute_startup_handler(
    event_handler: Option<Arc<FunctionInfo>>,
    task_locals: &TaskLocals,
) -> PyResult<()> {
    if let Some(function) = event_handler {
        if function.is_async {
            Python::with_gil(|py| {
                pyo3_asyncio::into_future_with_locals(
                    task_locals,
                    function.handler.as_ref(py).call0()?,
                )
            })?
            .await?;
        } else {
            Python::with_gil(|py| function.handler.call0(py))?;
        }
    }
    Ok(())
}
