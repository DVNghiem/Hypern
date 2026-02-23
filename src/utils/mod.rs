pub mod cpu;
pub mod crypto;
pub mod hash;
pub mod json;
pub mod pagination;
pub mod str_utils;
pub mod time_utils;

pub use json::{
    json_value_to_py, parse_json_to_py, py_to_json_value, serialize_py_to_json,
    serialize_py_to_json_pretty, serialize_py_to_json_string,
};

/// Register all utility functions and classes with the Python module.
pub fn register_utils(m: &pyo3::Bound<'_, pyo3::types::PyModule>) -> pyo3::PyResult<()> {
    str_utils::register(m)?;
    pagination::register(m)?;
    crypto::register(m)?;
    time_utils::register(m)?;
    Ok(())
}
