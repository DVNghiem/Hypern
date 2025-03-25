use std::sync::Arc;

use pyo3::{prelude::*, types::PyDict};

use crate::{
    di::DependencyInjection,
    runtime::future::{into_future, ContextExt, Runtime},
    types::{
        function_info::FunctionInfo, middleware::MiddlewareReturn, request::Request,
        response::Response,
    },
};

#[inline]
fn get_function_output<'a, T>(
    function: &'a FunctionInfo,
    py: Python<'a>,
    function_args: &T,
    deps: Option<Arc<DependencyInjection>>,
) -> Result<&'a PyAny, PyErr>
where
    T: ToPyObject,
{
    let handler = function.handler.as_ref(py);
    let kwargs = PyDict::new(py);

    // Add dependencies to kwargs if provided
    if let Some(dependency_injection) = deps {
        kwargs.set_item(
            "inject",
            dependency_injection
                .to_object(py)
                .into_ref(py)
                .downcast::<PyDict>()?
                .to_owned(),
        )?;
    }
    let result = handler.call((function_args.to_object(py),), Some(kwargs));
    result
}

#[inline]
pub async fn execute_http_function<R>(
    request: &Request,
    function: &FunctionInfo,
    deps: Option<Arc<DependencyInjection>>,
    rt: R,
) -> PyResult<Response> where R: Runtime + ContextExt + Clone, {
    if function.is_async {
        let output = Python::with_gil(|py| -> PyResult<_> {
            let function_output = get_function_output(function, py, request, deps)?;
            into_future(rt, function_output)
        })?
        .await?;
        return Python::with_gil(|py| -> PyResult<Response> { output.extract(py) });
    };

    Python::with_gil(|py| -> PyResult<Response> {
        get_function_output(function, py, request, deps)?.extract()
    })
}

#[inline]
pub async fn execute_middleware_function<T, R>(
    input: &T,
    function: &FunctionInfo,
    rt: R,
) -> PyResult<MiddlewareReturn>
where
    T: for<'a> FromPyObject<'a> + ToPyObject,
    R: Runtime + ContextExt + Clone,
{
    if function.is_async {
        let output: Py<PyAny> = Python::with_gil(|py| {
            into_future(rt, get_function_output(function, py, input, None)?)
        })?
        .await?;

        Python::with_gil(|py| -> PyResult<MiddlewareReturn> {
            let output_response = output.extract::<Response>(py);
            match output_response {
                Ok(o) => Ok(MiddlewareReturn::Response(o)),
                Err(_) => Ok(MiddlewareReturn::Request(output.extract::<Request>(py)?)),
            }
        })
    } else {
        Python::with_gil(|py| -> PyResult<MiddlewareReturn> {
            let output = get_function_output(function, py, input, None)?;
            match output.extract::<Response>() {
                Ok(o) => Ok(MiddlewareReturn::Response(o)),
                Err(_) => Ok(MiddlewareReturn::Request(output.extract::<Request>()?)),
            }
        })
    }
}

pub async fn execute_startup_handler<R>(
    event_handler: Option<Arc<FunctionInfo>>,
    rt: R,
) -> PyResult<()> where R: Runtime + ContextExt + Clone,{
    if let Some(function) = event_handler {
        if function.is_async {
            Python::with_gil(|py| {
                into_future(
                    rt,
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

pub async fn execute_shutdown_handler<R>(
    event_handler: Option<Arc<FunctionInfo>>,
    rt: R,
) -> PyResult<()> where R: Runtime + ContextExt + Clone, {
    if let Some(function) = event_handler {
        if function.is_async {
            Python::with_gil(|py| {
                into_future(
                    rt,
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
