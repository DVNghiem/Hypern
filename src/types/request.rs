use axum::extract::{ConnectInfo, Multipart};
use axum::extract::{FromRequest, Request as HttpRequest};
use axum::http::header;
use axum::response::IntoResponse;
use axum::Json;
use pyo3::types::{PyBytes, PyDict, PyList, PyString};
use pyo3::{exceptions::PyValueError, prelude::*};
use serde_json::Value;
use std::collections::HashMap;
use std::io::{Read, Write};
use tempfile::NamedTempFile;

use super::{header::Header, query::QueryParams};

#[derive(Debug, Clone, FromPyObject)]
pub struct UploadedFile {
    name: String,
    content_type: String,
    path: std::path::PathBuf,
    size: u64,
    content: Vec<u8>,
    filename: String,
}

impl ToPyObject for UploadedFile {
    fn to_object(&self, py: Python) -> PyObject {
        let name = self.name.clone();
        let content_type = self.content_type.clone();
        let path = self.path.clone();
        let size = self.size;
        let content = PyBytes::new(py, &self.content).into_py(py);
        let filename = self.filename.clone();

        let uploaded_file = PyUploadedFile {
            name,
            content_type,
            path,
            size,
            content,
            filename,
        };
        Py::new(py, uploaded_file).unwrap().as_ref(py).into()
    }
}

#[derive(Debug, Clone)]
#[pyclass]
pub struct PyUploadedFile {
    #[pyo3(get)]
    name: String,

    #[pyo3(get)]
    content_type: String,

    #[pyo3(get)]
    path: std::path::PathBuf,

    #[pyo3(get)]
    size: u64,

    #[pyo3(get)]
    content: Py<PyBytes>,

    #[pyo3(get)]
    filename: String,
}
#[derive(Debug, Default, Clone, FromPyObject)]
pub struct BodyData {
    json: Vec<u8>,
    files: Vec<UploadedFile>,
}

impl ToPyObject for BodyData {
    fn to_object(&self, py: Python) -> PyObject {
        let json = self.json.clone();
        let files = self.files.clone();

        let json = PyBytes::new(py, &json);
        let files: Vec<Py<PyAny>> = files.into_iter().map(|file| file.to_object(py)).collect();
        let files = PyList::new(py, files);
        let body = PyBodyData {
            json: json.into(),
            files: files.into(),
        };
        Py::new(py, body).unwrap().as_ref(py).into()
    }
}

#[derive(Debug, Clone)]
#[pyclass]
pub struct PyBodyData {
    #[pyo3(get)]
    json: Py<PyBytes>,

    #[pyo3(get)]
    files: Py<PyList>,
}

#[derive(Default, Debug, Clone, FromPyObject)]
pub struct Request {

    pub path: String,
    pub query_params: QueryParams,
    pub headers: Header,
    pub method: String,
    pub path_params: HashMap<String, String>,
    pub body: BodyData,

    pub remote_addr: String,
    pub timestamp: u32,
    pub context_id: String,

}

impl ToPyObject for Request {
    fn to_object(&self, py: Python) -> PyObject {
        let query_params = self.query_params.clone();
        let headers: Py<Header> = self.headers.clone().into_py(py).extract(py).unwrap();
        let path_params = self.path_params.clone().into_py(py).extract(py).unwrap();
        let body = self.body.clone().to_object(py).extract(py).unwrap();

        let request = PyRequest {
            path: self.path.clone(),
            query_params,
            path_params,
            headers,
            body,
            method: self.method.clone(),
            remote_addr: self.remote_addr.clone(),
            timestamp: self.timestamp.clone(),
            context_id: self.context_id.clone(),
        };
        Py::new(py, request).unwrap().as_ref(py).into()
    }
}

impl Request {
    pub async fn from_request(request: HttpRequest) -> Self {
        let mut query_params: QueryParams = QueryParams::new();

        // setup query params
        if let Some(qs) = request.uri().query() {
            for (key, value) in qs.split('&').filter_map(|s| {
                let mut split = s.splitn(2, '=');
                Some((split.next()?, split.next()?))
            }) {
                query_params.set(key.to_string(), value.to_string());
            }
        }

        let remote_addr = request
            .extensions()
            .get::<ConnectInfo<std::net::SocketAddr>>()
            .map(|ConnectInfo(addr)| addr.ip().to_string())
            .unwrap_or_default();

        // init default current timestamp
        let timestamp = Some(
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs() as u32,
        ).unwrap();
        let context_id = uuid::Uuid::new_v4().to_string();

        // parse the header to python header object
        let path = request.uri().path().to_string();
        let headers = Header::from_hyper_headers(request.headers());
        let method = request.method().to_string();
        let content_type = request
            .headers()
            .get(header::CONTENT_TYPE)
            .and_then(|v| v.to_str().ok())
            .unwrap_or("");
        let default_body = BodyData::default();
        let body = match content_type {
            t if t.starts_with("application/json") => {
                let json = Json::<Value>::from_request(request, &())
                    .await
                    .map_err(|e| e.into_response());
                match json {
                    Ok(json) => BodyData {
                        json: json.to_string().as_bytes().to_vec(),
                        files: vec![],
                    },
                    Err(_e) => default_body,
                }
            }
            t if t.starts_with("multipart/form-data") => {
                let mut multipart = Multipart::from_request(request, &())
                    .await
                    .map_err(|e| e.into_response());

                let mut files = vec![];
                let mut json = vec![];

                while let Some(field) = multipart
                    .as_mut()
                    .unwrap()
                    .next_field()
                    .await
                    .map_err(|e| e.into_response())
                    .ok()
                    .flatten()
                {
                    let name = field.name().unwrap_or("").to_string();
                    let content_type = field
                        .content_type()
                        .unwrap_or("application/octet-stream")
                        .to_string();

                    if name == "json" {
                        let data = field.bytes().await.map_err(|e| e.into_response());
                        json = match Some(serde_json::from_slice(&data.unwrap()).map_err(|e| e)) {
                            Some(Ok(json)) => json,
                            _ => vec![],
                        }
                    } else {
                        let filename = field.file_name().unwrap_or("").to_string();
                        let data = field.bytes().await.map_err(|e| e.into_response());

                        let mut temp_file = NamedTempFile::new().map_err(|e| e);

                        match temp_file {
                            Ok(ref mut file) => {
                                let _ = file.write(&data.unwrap()).map_err(|e| e);
                                let file_content = file.reopen().map_err(|e| e);
                                files.push(UploadedFile {
                                    name,
                                    content_type,
                                    path: file.path().to_path_buf(),
                                    size: file.path().metadata().unwrap().len(),
                                    content: {
                                        let mut buffer = Vec::new();
                                        file_content.unwrap().read_to_end(&mut buffer).unwrap();
                                        buffer
                                    },
                                    filename,
                                });
                            }
                            Err(e) => {
                                eprintln!("Error: {:?}", e);
                            }
                        }
                    }
                }

                BodyData { json, files }
            }
            _ => default_body,
        };

        Self {
            path,
            query_params,
            headers: headers.clone(),
            method,
            path_params: HashMap::new(),
            body,
            remote_addr,
            timestamp,
            context_id,
        }
    }
}

#[pyclass(name = "Request")]
#[derive(Clone)]
pub struct PyRequest {
    #[pyo3(get, set)]
    pub path: String,
    #[pyo3(get, set)]
    pub query_params: QueryParams,
    #[pyo3(get, set)]
    pub headers: Py<Header>,
    #[pyo3(get, set)]
    pub path_params: Py<PyDict>,
    #[pyo3(get)]
    pub body: PyBodyData,
    #[pyo3(get)]
    pub method: String,
    #[pyo3(get)]
    pub remote_addr: String,
    #[pyo3(get)]
    pub timestamp: u32,
    #[pyo3(get)]
    pub context_id: String,
}

#[pymethods]
impl PyRequest {
    #[new]
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        path: String,
        query_params: QueryParams,
        headers: Py<Header>,
        path_params: Py<PyDict>,
        body: PyBodyData,
        method: String,
        context_id: String,
        remote_addr: String,
        timestamp: u32,
    ) -> Self {
        Self {
            path,
            query_params,
            headers,
            path_params,
            body,
            method,
            remote_addr,
            timestamp,
            context_id,
        }
    }

    #[setter]
    pub fn set_body(&mut self, body: PyBodyData) -> PyResult<()> {
        self.body = body;
        Ok(())
    }

    pub fn json(&self, py: Python) -> PyResult<PyObject> {
        let body = self.body.json.clone();
        let body_bytes: &[u8] = &body.as_ref(py).as_bytes();
        let body = PyString::new(py, &String::from_utf8_lossy(body_bytes));
        match serde_json::from_str(body.extract()?) {
            Ok(Value::Object(map)) => {
                let dict = PyDict::new(py);

                for (key, value) in map.iter() {
                    let py_key = key.to_string().into_py(py);
                    let py_value = match value {
                        Value::String(s) => s.as_str().into_py(py),
                        _ => value.to_string().into_py(py),
                    };

                    dict.set_item(py_key, py_value)?;
                }

                Ok(dict.into_py(py))
            }
            _ => Err(PyValueError::new_err("Invalid JSON object")),
        }
    }
}
