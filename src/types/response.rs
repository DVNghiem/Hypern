use dashmap::DashMap;
use pyo3::{
    prelude::*,
    types::{PyBytes, PyDict, PyString},
};

use hyper::{header::HeaderName, Response as HyperResponse, StatusCode};

use super::{body::{full, BoxBody}, header::Header};

fn get_description_from_pyobject(description: &Bound<PyAny>) -> PyResult<Vec<u8>> {
    if let Ok(s) = description.downcast::<PyString>() {
        Ok(s.to_string().into_bytes())
    } else if let Ok(b) = description.downcast::<PyBytes>() {
        Ok(b.as_bytes().to_vec())
    } else {
        Ok(vec![])
    }
}

#[derive(Debug, Clone, FromPyObject)]
pub struct Response {
    pub status_code: u16,
    pub response_type: String,
    pub headers: Header,

    #[pyo3(from_py_with = "get_description_from_pyobject")]
    pub description: Vec<u8>,
    pub file_path: Option<String>,

    pub context_id: String,
}

impl Response {
    pub fn to_response(
        &self,
        extra_headers: &DashMap<String, String>,
    ) -> HyperResponse<BoxBody> {
        let mut builder =
        HyperResponse::builder().status(StatusCode::from_u16(self.status_code).unwrap());

        for (key, value) in self.headers.headers.iter() {
            if let Ok(name) = HeaderName::from_bytes(key.as_bytes()) {
                builder = builder.header(name, value);
            }
        }

        for ref_multi in extra_headers.iter() {
            if let Ok(name) = HeaderName::from_bytes(ref_multi.key().as_bytes()) {
                builder = builder.header(name, ref_multi.value());
            }
        }

        builder.body(full(self.description.clone())).unwrap()
    }
}
impl<'py> IntoPyObject<'py> for Response {

    type Target = PyResponse; 
    type Output = Bound<'py, Self::Target>; // in most cases this will be `Bound`
    type Error = std::convert::Infallible;

    fn into_pyobject(self, py: Python<'py>) -> Result<Self::Output, Self::Error> {
        let headers = self.headers.clone().into_py(py).extract(py).unwrap();
        // The description should only be either string or binary.
        // it should raise an exception otherwise
        let description = match String::from_utf8(self.description.to_vec()) {
            Ok(description) => description.to_object(py),
            Err(_) => PyBytes::new(py, &self.description.to_vec()).into(),
        };

        let response = PyResponse {
            status_code: self.status_code,
            response_type: self.response_type.clone(),
            headers,
            description,
            file_path: self.file_path.clone(),
            context_id: self.context_id.clone(),
        };
        Ok(Py::new(py, response).unwrap().into_bound(py))
    }
}

#[pyclass(name = "Response")]
#[derive(Debug)]
pub struct PyResponse {
    #[pyo3(get)]
    pub status_code: u16,
    #[pyo3(get)]
    pub response_type: String,
    #[pyo3(get, set)]
    pub headers: Header,
    #[pyo3(get)]
    pub description: PyObject,
    #[pyo3(get)]
    pub file_path: Option<String>,

    #[pyo3(get)]
    pub context_id: String,
}

#[pymethods]
impl PyResponse {
    // To do: Add check for content-type in header and change response_type accordingly
    #[new]
    pub fn new(
        _py: Python,
        status_code: u16,
        headers: Bound<PyAny>,
        description: Bound<PyAny>,
    ) -> PyResult<Self> {
        let headers_output: Header = if let Ok(headers_dict) = headers.downcast::<PyDict>() {
            // Here you'd have logic to create a Headers instance from a PyDict
            // For simplicity, let's assume you have a method `from_dict` on Headers for this
            let headers = Header::from_pydict(headers_dict); // Hypothetical method
            headers
        } else if let Ok(headers) = headers.extract::<Header>() {
            // If it's already a Py<Headers>, use it directly
            headers
        } else {
            return Err(PyErr::new::<pyo3::exceptions::PyTypeError, _>(
                "headers must be a Headers instance or a dict",
            ));
        };

        Ok(Self {
            status_code,
            // we should be handling based on headers but works for now
            response_type: "text".to_string(),
            headers: headers_output,
            description: description.into(),
            file_path: None,
            context_id: "".to_string(),
        })
    }

    #[setter]
    pub fn set_description(&mut self, description: Py<PyAny>) -> PyResult<()> {
        self.description = description;
        Ok(())
    }

    pub fn set_cookie(&mut self, py: Python, key: String, value: String) -> PyResult<()> {
        self.headers.set(key, value);
        Ok(())
    }
}
