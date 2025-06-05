use std::collections::HashMap;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use pyo3::exceptions::PyRuntimeError;
use pyo3::exceptions::PyTimeoutError;
use pyo3::exceptions::PyTypeError;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use pyo3::types::PyTuple;

use tokio::time::timeout;

use uuid;

#[pyclass]
pub struct BackgroundTask {
    id: String,
    #[pyo3(get, set)]
    function: PyObject,
    #[pyo3(get, set)]
    args: Option<Vec<PyObject>>,
    #[pyo3(get, set)]
    kwargs: Option<HashMap<String, PyObject>>,
    #[pyo3(get, set)]
    timeout_secs: Option<u64>,

    cancelled: Arc<Mutex<bool>>,
}

#[pymethods]
impl BackgroundTask {
    #[new]
    fn new(
        function: PyObject,
        args: Option<Vec<PyObject>>,
        kwargs: Option<HashMap<String, PyObject>>,
        timeout_secs: Option<u64>,
    ) -> PyResult<Self> {
        Python::with_gil(|py| {
            let inspect = py.import("inspect")?;
            let is_coroutine = inspect
                .call_method1("iscoroutinefunction", (function.clone(),))?
                .extract::<bool>()?;
            if is_coroutine {
                return Err(PyTypeError::new_err(
                    "Background tasks cannot use async functions. Please use a regular function instead."
                ));
            }
            // If not awaitable, create the BackgroundTask
            Ok(BackgroundTask {
                id: uuid::Uuid::new_v4().to_string(),
                function,
                args,
                kwargs,
                timeout_secs,
                cancelled: Arc::new(Mutex::new(false)),
            })
        })
    }

    pub fn get_id(&self) -> String {
        self.id.clone()
    }

    pub fn cancel(&self) -> PyResult<()> {
        let mut cancelled = self.cancelled.lock().unwrap();
        *cancelled = true;
        Ok(())
    }

    fn is_cancelled(&self) -> bool {
        let cancelled = self.cancelled.lock().unwrap();
        *cancelled
    }

    pub fn execute(&self, py: Python) -> PyResult<PyObject> {
        // Clone necessary data outside of async block
        let function = self.function.clone();
        let cancelled = self.cancelled.clone();
        let timeout_secs = self.timeout_secs;

        // Check if task was cancelled
        if *cancelled.lock().unwrap() {
            return Err(PyErr::new::<PyRuntimeError, _>("Task was cancelled"));
        }

        // Prepare arguments
        let args = match &self.args {
            Some(args) => PyTuple::new(py, args),
            None => Ok(PyTuple::empty(py)),
        };

        // Prepare keyword arguments
        let kwargs = match &self.kwargs {
            Some(kwargs) => {
                let dict = PyDict::new(py);
                for (key, value) in kwargs {
                    dict.set_item(key, value).map_err(|e| {
                        PyErr::new::<PyRuntimeError, _>(format!("Failed to set kwargs: {}", e))
                    })?;
                }
                Some(dict)
            }
            None => None,
        };

        // Create the future for executing the Python function
        let execute_future = Python::with_gil(|py| {
            let asyncio = py.import("asyncio")?;
            let coro = match kwargs {
                Some(kw) => function.call(py, args, Some(kw))?,
                None => function.call(py, args, None)?,
            };

            // Check if the result is a coroutine
            if asyncio
                .call_method1("iscoroutine", (coro.clone(),))?
                .extract::<bool>()?
            {
                Ok(coro)
            } else {
                // If not a coroutine, wrap it in a future
                asyncio
                    .call_method1("create_task", (coro,))
                    .map(|obj| obj.into())
            }
        })?;

        // Convert the future to a Python awaitable and wrap it with a timeout
        let fut = pyo3_async_runtimes::tokio::future_into_py(py, async move {
            match timeout(Duration::from_secs(timeout_secs.unwrap()), async {
                Ok(execute_future)
            })
            .await
            {
                Ok(result) => result,
                Err(_) => Err(PyErr::new::<PyTimeoutError, _>(format!(
                    "Task timed out after {} seconds",
                    timeout_secs.unwrap()
                ))),
            }
        });

        fut.map(|obj| obj.into())
    }
}

// impl FromPyObject<'_> for BackgroundTask {
//     fn extract(ob: &PyAny) -> PyResult<Self> {
//         let function = ob.getattr("function")?.extract::<PyObject>()?;
//         let args = ob.getattr("args")?.extract::<Option<Vec<PyObject>>>()?;
//         let kwargs = ob
//             .getattr("kwargs")?
//             .extract::<Option<HashMap<String, PyObject>>>()?;
//         let timeout_secs = ob.getattr("timeout_secs")?.extract::<Option<u64>>()?;

//         BackgroundTask::new(function, args, kwargs, timeout_secs)
//     }
// }
