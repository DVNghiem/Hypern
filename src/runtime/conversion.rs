use pyo3::{prelude::*, IntoPyObjectExt};

pub(crate) struct BytesToPy(pub hyper::body::Bytes);
pub(crate) struct Utf8BytesToPy(pub tokio_tungstenite::tungstenite::Utf8Bytes);

impl<'p> IntoPyObject<'p> for BytesToPy {
    type Target = PyAny;
    type Output = Bound<'p, Self::Target>;
    type Error = PyErr;

    fn into_pyobject(self, py: Python<'p>) -> Result<Self::Output, Self::Error> {
        self.0.as_ref().into_bound_py_any(py)
    }
}

impl<'p> IntoPyObject<'p> for Utf8BytesToPy {
    type Target = PyAny;
    type Output = Bound<'p, Self::Target>;
    type Error = PyErr;

    fn into_pyobject(self, py: Python<'p>) -> Result<Self::Output, Self::Error> {
        self.0.as_str().into_bound_py_any(py)
    }
}

pub(crate) enum FutureResultToPy {
    None,
    Err(PyResult<()>),
    Bytes(hyper::body::Bytes),
}

impl<'p> IntoPyObject<'p> for FutureResultToPy {
    type Target = PyAny;
    type Output = Bound<'p, Self::Target>;
    type Error = PyErr;

    fn into_pyobject(self, py: Python<'p>) -> Result<Self::Output, Self::Error> {
        match self {
            Self::None => Ok(py.None().into_bound(py)),
            Self::Err(res) => Err(res.err().unwrap()),
            Self::Bytes(inner) => inner.into_pyobject(py),
        }
    }
}
