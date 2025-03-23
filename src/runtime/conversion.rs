use pyo3::prelude::*;

pub(crate) struct BytesToPy(pub hyper::body::Bytes);
pub(crate) struct Utf8BytesToPy(pub tokio_tungstenite::tungstenite::Utf8Bytes);

impl<'p> ToPyObject for BytesToPy {

    fn to_object(&self, py: Python<'_>) -> PyObject {
        self.0.as_ref().into_py(py)
    }
}

impl<'p> ToPyObject for Utf8BytesToPy {

    fn to_object(&self, py: Python<'_>) -> PyObject {
        self.0.as_str().into_py(py)
    }
}

pub(crate) enum FutureResultToPy {
    None,
    Err(PyResult<()>),
    Bytes(hyper::body::Bytes),
}

impl<'p> ToPyObject for FutureResultToPy {

    fn to_object(&self, py: Python<'_>) -> PyObject {
        match self {
            Self::None => py.None(),
            Self::Err(res) => {
                match res {
                    Ok(_) => py.None(),
                    Err(err) => err.to_object(py)
                }
            },
            Self::Bytes(inner) => inner.into_py(py),
        }
    }
}
