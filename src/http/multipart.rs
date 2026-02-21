use bytes::Bytes;
use parking_lot::RwLock;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList};
use std::collections::HashMap;
use std::fs;
use std::io::Write;
use std::path::PathBuf;
use std::sync::Arc;

#[pyclass(from_py_object)]
#[derive(Clone)]
pub struct UploadedFile {
    /// Original filename from the upload
    #[pyo3(get)]
    pub filename: String,

    /// Field name from the form
    #[pyo3(get)]
    pub name: String,

    /// Content type (MIME type)
    #[pyo3(get)]
    pub content_type: String,

    /// File size in bytes
    #[pyo3(get)]
    pub size: usize,

    /// File content (in memory)
    content: Arc<RwLock<Bytes>>,
}

#[pymethods]
impl UploadedFile {
    /// Read the file content as bytes
    pub fn read<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyBytes>> {
        let content = self.content.read();
        Ok(PyBytes::new(py, &content))
    }

    /// Read the file content as string (UTF-8)
    pub fn read_text(&self) -> PyResult<String> {
        let content = self.content.read();
        String::from_utf8(content.to_vec())
            .map_err(|e| pyo3::exceptions::PyUnicodeDecodeError::new_err(e.to_string()))
    }

    /// Save the file to disk
    #[pyo3(signature = (path, overwrite=false))]
    pub fn save(&self, path: &str, overwrite: bool) -> PyResult<String> {
        let path = PathBuf::from(path);

        // Check if file exists
        if path.exists() && !overwrite {
            return Err(pyo3::exceptions::PyFileExistsError::new_err(format!(
                "File already exists: {}",
                path.display()
            )));
        }

        // Create parent directory if needed
        if let Some(parent) = path.parent() {
            if !parent.exists() {
                fs::create_dir_all(parent)?;
            }
        }

        // Write file content
        let content = self.content.read();
        let mut file = fs::File::create(&path)?;
        file.write_all(&content)?;

        Ok(path.to_string_lossy().to_string())
    }

    /// Save to a directory using the original filename
    pub fn save_to(&self, directory: &str) -> PyResult<String> {
        let dir = PathBuf::from(directory);
        let path = dir.join(&self.filename);
        self.save(&path.to_string_lossy(), false)
    }

    /// Check if file is an image
    pub fn is_image(&self) -> bool {
        self.content_type.starts_with("image/")
    }

    /// Check if file is a video
    pub fn is_video(&self) -> bool {
        self.content_type.starts_with("video/")
    }

    /// Check if file is audio
    pub fn is_audio(&self) -> bool {
        self.content_type.starts_with("audio/")
    }

    /// Check if file is a PDF
    pub fn is_pdf(&self) -> bool {
        self.content_type == "application/pdf"
    }

    pub fn extension(&self) -> Option<String> {
        PathBuf::from(&self.filename)
            .extension()
            .map(|e| e.to_string_lossy().to_string())
    }

    fn __repr__(&self) -> String {
        format!(
            "UploadedFile(name='{}', filename='{}', content_type='{}', size={})",
            self.name, self.filename, self.content_type, self.size
        )
    }

    fn __str__(&self) -> String {
        self.filename.clone()
    }

    fn __len__(&self) -> usize {
        self.size
    }

    fn __bool__(&self) -> bool {
        self.size > 0
    }
}

impl UploadedFile {
    /// Create a new UploadedFile from raw data
    pub fn new(name: String, filename: String, content_type: String, content: Bytes) -> Self {
        let size = content.len();
        Self {
            filename,
            name,
            content_type,
            size,
            content: Arc::new(RwLock::new(content)),
        }
    }

    /// Get the raw content bytes
    pub fn content_bytes(&self) -> Bytes {
        self.content.read().clone()
    }
}

#[pyclass]
pub struct FormData {
    /// Text fields from the form
    fields: HashMap<String, String>,

    /// Uploaded files
    files: HashMap<String, Vec<UploadedFile>>,
}

#[pymethods]
impl FormData {
    /// Get a text field value
    pub fn get(&self, key: &str) -> Option<String> {
        self.fields.get(key).cloned()
    }

    /// Get a text field value with default
    #[pyo3(signature = (key, default=None))]
    pub fn get_or(&self, key: &str, default: Option<String>) -> Option<String> {
        self.fields.get(key).cloned().or(default)
    }

    /// Get a single uploaded file by field name
    pub fn file(&self, key: &str) -> Option<UploadedFile> {
        self.files.get(key).and_then(|v| v.first().cloned())
    }

    /// Get all uploaded files for a field name (for multiple file uploads)
    pub fn files_list(&self, key: &str) -> Vec<UploadedFile> {
        self.files.get(key).cloned().unwrap_or_default()
    }

    /// Get all uploaded files
    pub fn all_files(&self) -> Vec<UploadedFile> {
        self.files.values().flatten().cloned().collect()
    }

    /// Get all field names
    pub fn field_names(&self) -> Vec<String> {
        self.fields.keys().cloned().collect()
    }

    /// Get all file field names
    pub fn file_names(&self) -> Vec<String> {
        self.files.keys().cloned().collect()
    }

    /// Check if a field exists
    pub fn has(&self, key: &str) -> bool {
        self.fields.contains_key(key)
    }

    /// Check if a file field exists
    pub fn has_file(&self, key: &str) -> bool {
        self.files.contains_key(key)
    }

    /// Get total number of files
    pub fn file_count(&self) -> usize {
        self.files.values().map(|v| v.len()).sum()
    }

    /// Get fields as Python dict
    fn get_fields<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let dict = PyDict::new(py);
        for (k, v) in &self.fields {
            dict.set_item(k, v)?;
        }
        Ok(dict)
    }

    /// Get files as Python dict
    fn get_files_dict<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let dict = PyDict::new(py);
        for (k, v) in &self.files {
            let list = PyList::new(py, v.iter().map(|f| f.clone().into_pyobject(py).unwrap()))?;
            dict.set_item(k, list)?;
        }
        Ok(dict)
    }

    fn __repr__(&self) -> String {
        format!(
            "FormData(fields={}, files={})",
            self.fields.len(),
            self.file_count()
        )
    }

    fn __len__(&self) -> usize {
        self.fields.len() + self.file_count()
    }
}

impl FormData {
    pub fn new() -> Self {
        Self {
            fields: HashMap::new(),
            files: HashMap::new(),
        }
    }

    pub fn add_field(&mut self, name: String, value: String) {
        self.fields.insert(name, value);
    }

    pub fn add_file(&mut self, name: String, file: UploadedFile) {
        self.files.entry(name).or_insert_with(Vec::new).push(file);
    }
}

impl Default for FormData {
    fn default() -> Self {
        Self::new()
    }
}

/// consider streaming directly to disk.
pub fn parse_multipart(body: &Bytes, boundary: &str) -> FormData {
    let mut form_data = FormData::new();

    let boundary_bytes = format!("--{}", boundary);
    let parts = split_multipart(body, boundary_bytes.as_bytes());

    for part in parts {
        if part.is_empty() {
            continue;
        }

        // Find header/body separator
        if let Some(sep_pos) = find_double_crlf(&part) {
            let header_bytes = &part[..sep_pos];
            let body_bytes = &part[sep_pos + 4..]; // Skip \r\n\r\n

            // Parse headers
            let headers = parse_part_headers(header_bytes);

            // Get content disposition
            if let Some(disposition) = headers.get("content-disposition") {
                let (name, filename) = parse_content_disposition(disposition);

                if let Some(name) = name {
                    if let Some(filename) = filename {
                        // This is a file upload
                        let content_type = headers
                            .get("content-type")
                            .cloned()
                            .unwrap_or_else(|| "application/octet-stream".to_string());

                        // Remove trailing \r\n if present
                        let body_bytes = if body_bytes.ends_with(b"\r\n") {
                            &body_bytes[..body_bytes.len() - 2]
                        } else {
                            body_bytes
                        };

                        let file = UploadedFile::new(
                            name.clone(),
                            filename,
                            content_type,
                            Bytes::copy_from_slice(body_bytes),
                        );
                        form_data.add_file(name, file);
                    } else {
                        // This is a text field
                        let value = String::from_utf8_lossy(body_bytes)
                            .trim_end_matches("\r\n")
                            .to_string();
                        form_data.add_field(name, value);
                    }
                }
            }
        }
    }

    form_data
}

/// Split multipart body by boundary
fn split_multipart(body: &Bytes, boundary: &[u8]) -> Vec<Vec<u8>> {
    let mut parts = Vec::new();
    let mut start = 0;

    // Find first boundary
    if let Some(pos) = find_bytes(body, boundary) {
        start = pos + boundary.len();
        // Skip CRLF after boundary
        if body.len() > start + 2 && &body[start..start + 2] == b"\r\n" {
            start += 2;
        }
    }

    loop {
        // Find next boundary
        if let Some(end) = find_bytes(&body[start..], boundary) {
            let part = body[start..start + end].to_vec();
            parts.push(part);
            start = start + end + boundary.len();

            // Check for final boundary (--boundary--)
            if body.len() > start && body[start..].starts_with(b"--") {
                break;
            }

            // Skip CRLF after boundary
            if body.len() > start + 2 && &body[start..start + 2] == b"\r\n" {
                start += 2;
            }
        } else {
            // No more boundaries
            if start < body.len() {
                parts.push(body[start..].to_vec());
            }
            break;
        }
    }

    parts
}

fn find_double_crlf(data: &[u8]) -> Option<usize> {
    for i in 0..data.len().saturating_sub(3) {
        if &data[i..i + 4] == b"\r\n\r\n" {
            return Some(i);
        }
    }
    None
}

/// Find bytes in slice
fn find_bytes(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack
        .windows(needle.len())
        .position(|window| window == needle)
}

/// Parse part headers
fn parse_part_headers(header_bytes: &[u8]) -> HashMap<String, String> {
    let mut headers = HashMap::new();
    let header_str = String::from_utf8_lossy(header_bytes);

    for line in header_str.split("\r\n") {
        if let Some(colon_pos) = line.find(':') {
            let name = line[..colon_pos].trim().to_lowercase();
            let value = line[colon_pos + 1..].trim().to_string();
            headers.insert(name, value);
        }
    }

    headers
}

/// Parse Content-Disposition header to extract name and filename
fn parse_content_disposition(value: &str) -> (Option<String>, Option<String>) {
    let mut name = None;
    let mut filename = None;

    for part in value.split(';') {
        let part = part.trim();

        if part.starts_with("name=") {
            let val = part[5..].trim_matches('"');
            name = Some(val.to_string());
        } else if part.starts_with("filename=") {
            let val = part[9..].trim_matches('"');
            filename = Some(val.to_string());
        }
    }

    (name, filename)
}

/// Extract boundary from Content-Type header
pub fn extract_boundary(content_type: &str) -> Option<String> {
    for part in content_type.split(';') {
        let part = part.trim();
        if part.starts_with("boundary=") {
            return Some(part[9..].trim_matches('"').to_string());
        }
    }
    None
}
