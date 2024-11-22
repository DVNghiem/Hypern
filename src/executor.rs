use pyo3::{prelude::*, types::PyDict};

use anyhow::Result;
use crate::{
    di::DependencyInjection,
    types::{function_info::FunctionInfo, middleware::MiddlewareReturn, request::Request, response::Response},
};

#[inline]
fn get_function_output<'a, T>(
    function: &'a FunctionInfo,
    py: Python<'a>,
    function_args: &T,
    deps: Option<DependencyInjection>,
) -> Result<&'a PyAny, PyErr>
where
    T: ToPyObject,
{
    let handler = function.handler.as_ref(py);
    let kwargs = PyDict::new(py);

    // Add dependencies to kwargs if provided
    if let Some(dependency_injection) = deps {
        let _ = kwargs.set_item(
            "inject",
            dependency_injection
                .to_object(py)
                .into_ref(py)
                .downcast::<PyDict>()?
                .to_owned(),
        );
    }
    handler.call((function_args.to_object(py),), Some(kwargs))
}

#[inline]
pub async fn execute_http_function(
    request: &Request,
    function: &FunctionInfo,
    deps: Option<DependencyInjection>,
) -> PyResult<Response> {
    if function.is_async {
        let output = Python::with_gil(|py| {
            let function_output = get_function_output(function, py, request, deps)?;
            pyo3_asyncio::tokio::into_future(function_output)
        })?
        .await?;

        return Python::with_gil(|py| -> PyResult<Response> { output.extract(py) });
    };

    Python::with_gil(|py| -> PyResult<Response> {
        get_function_output(function, py, request, deps)?.extract()
    })
}


#[inline]
pub async fn execute_middleware_function<T>(
    input: &T,
    function: &FunctionInfo,
) -> Result<MiddlewareReturn>
where
    T: for<'a> FromPyObject<'a> + ToPyObject,
{
    if function.is_async {
        let output: Py<PyAny> = Python::with_gil(|py| {
            pyo3_asyncio::tokio::into_future(get_function_output(function, py, input, None)?)
        })?
        .await?;

        Python::with_gil(|py| -> Result<MiddlewareReturn> {
            let output_response = output.extract::<Response>(py);
            match output_response {
                Ok(o) => Ok(MiddlewareReturn::Response(o)),
                Err(_) => Ok(MiddlewareReturn::Request(output.extract::<Request>(py)?)),
            }
        })
    } else {
        Python::with_gil(|py| -> Result<MiddlewareReturn> {
            let output = get_function_output(function, py, input, None)?;
            match output.extract::<Response>() {
                Ok(o) => Ok(MiddlewareReturn::Response(o)),
                Err(_) => Ok(MiddlewareReturn::Request(output.extract::<Request>()?)),
            }
        })
    }
}