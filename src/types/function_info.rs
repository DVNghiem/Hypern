use pyo3::prelude::*;

#[pyclass]
#[derive(Debug)]
pub struct FunctionInfo {
    #[pyo3(get, set)]
    pub handler: Py<PyAny>,
    #[pyo3(get, set)]
    pub is_async: bool,
}


#[pymethods]
impl FunctionInfo {
    #[new]
    pub fn new(
        handler: Py<PyAny>,
        is_async: bool,
    ) -> Self {
        Self {
            handler,
            is_async,
        }
    }

    fn __str__(&self) -> PyResult<String> {
        Ok(format!("Function(handler = {:?}, is_async = {})", self.handler, self.is_async))
    }
}
