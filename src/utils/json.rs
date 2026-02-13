use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyList};
use serde_json::Value as JsonValue;

pub fn json_value_to_py(py: Python<'_>, value: &JsonValue) -> PyResult<Py<PyAny>> {
    match value {
        JsonValue::Null => Ok(py.None()),
        JsonValue::Bool(b) => Ok(PyBool::new(py, *b).to_owned().into_any().unbind()),
        JsonValue::Number(n) => {
            if let Some(i) = n.as_i64() {
                Ok(i.into_pyobject(py)?.into_any().unbind())
            } else if let Some(u) = n.as_u64() {
                Ok(u.into_pyobject(py)?.into_any().unbind())
            } else if let Some(f) = n.as_f64() {
                Ok(f.into_pyobject(py)?.into_any().unbind())
            } else {
                // Fallback: treat as 0
                Ok(0i64.into_pyobject(py)?.into_any().unbind())
            }
        }
        JsonValue::String(s) => Ok(s.clone().into_pyobject(py)?.into_any().unbind()),
        JsonValue::Array(arr) => {
            let list = PyList::empty(py);
            for item in arr {
                list.append(json_value_to_py(py, item)?)?;
            }
            Ok(list.into_any().unbind())
        }
        JsonValue::Object(obj) => {
            let dict = PyDict::new(py);
            for (key, val) in obj {
                dict.set_item(key, json_value_to_py(py, val)?)?;
            }
            Ok(dict.into_any().unbind())
        }
    }
}

pub fn py_to_json_value(obj: &Bound<'_, PyAny>) -> PyResult<JsonValue> {
    if obj.is_none() {
        return Ok(JsonValue::Null);
    }

    // Check for bool first (before int, since bool is subclass of int in Python)
    if let Ok(b) = obj.extract::<bool>() {
        return Ok(JsonValue::Bool(b));
    }

    // Integer
    if let Ok(i) = obj.extract::<i64>() {
        return Ok(JsonValue::Number(i.into()));
    }

    // Float
    if let Ok(f) = obj.extract::<f64>() {
        if let Some(n) = serde_json::Number::from_f64(f) {
            return Ok(JsonValue::Number(n));
        }
        // NaN/Infinity - convert to null (JSON doesn't support these)
        return Ok(JsonValue::Null);
    }

    // String
    if let Ok(s) = obj.extract::<String>() {
        return Ok(JsonValue::String(s));
    }

    // List/Tuple - use is_instance_of for type checking (check before bytes!)
    if obj.is_instance_of::<PyList>() {
        let list = obj.extract::<Bound<'_, PyList>>()?;
        let mut arr = Vec::with_capacity(list.len());
        for item in list.iter() {
            arr.push(py_to_json_value(&item)?);
        }
        return Ok(JsonValue::Array(arr));
    }

    // Bytes - convert to base64 or string
    if let Ok(bytes) = obj.extract::<Vec<u8>>() {
        // Try to decode as UTF-8 string first
        if let Ok(s) = String::from_utf8(bytes.clone()) {
            return Ok(JsonValue::String(s));
        }
        // Fallback: convert to hex or just use lossy
        return Ok(JsonValue::String(
            String::from_utf8_lossy(&bytes).to_string(),
        ));
    }

    // Dict
    if obj.is_instance_of::<PyDict>() {
        let dict = obj.extract::<Bound<'_, PyDict>>()?;
        let mut map = serde_json::Map::new();
        for (key, value) in dict.iter() {
            let key_str: String = if let Ok(s) = key.extract::<String>() {
                s
            } else {
                // Convert non-string keys to string
                key.str()?.to_string()
            };
            map.insert(key_str, py_to_json_value(&value)?);
        }
        return Ok(JsonValue::Object(map));
    }

    // Try to iterate (for tuples, sets, etc.)
    if let Ok(iter) = obj.try_iter() {
        let mut arr = Vec::new();
        for item in iter {
            arr.push(py_to_json_value(&item?)?);
        }
        return Ok(JsonValue::Array(arr));
    }

    // Try __dict__ for custom objects
    if let Ok(dict) = obj.getattr("__dict__") {
        if dict.is_instance_of::<PyDict>() {
            let d = dict.extract::<Bound<'_, PyDict>>()?;
            let mut map = serde_json::Map::new();
            for (key, value) in d.iter() {
                let key_str: String = key.str()?.to_string();
                // Skip private attributes
                if !key_str.starts_with('_') {
                    map.insert(key_str, py_to_json_value(&value)?);
                }
            }
            return Ok(JsonValue::Object(map));
        }
    }

    // Fallback: convert to string representation
    Ok(JsonValue::String(obj.str()?.to_string()))
}

pub fn parse_json_to_py(py: Python<'_>, bytes: &[u8]) -> PyResult<Py<PyAny>> {
    // Use simd_json for fast parsing
    let mut data = bytes.to_vec();
    match simd_json::serde::from_slice::<JsonValue>(&mut data) {
        Ok(value) => json_value_to_py(py, &value),
        Err(e) => Err(pyo3::exceptions::PyValueError::new_err(format!(
            "JSON parse error: {}",
            e
        ))),
    }
}

/// Uses simd_json for serialization where possible.
pub fn serialize_py_to_json(obj: &Bound<'_, PyAny>) -> PyResult<Vec<u8>> {
    let value = py_to_json_value(obj)?;
    serde_json::to_vec(&value).map_err(|e| {
        pyo3::exceptions::PyValueError::new_err(format!("JSON serialization error: {}", e))
    })
}

/// Serialize Python object to JSON string.
pub fn serialize_py_to_json_string(obj: &Bound<'_, PyAny>) -> PyResult<String> {
    let value = py_to_json_value(obj)?;
    serde_json::to_string(&value).map_err(|e| {
        pyo3::exceptions::PyValueError::new_err(format!("JSON serialization error: {}", e))
    })
}

/// Serialize Python object to pretty-printed JSON string.
pub fn serialize_py_to_json_pretty(obj: &Bound<'_, PyAny>) -> PyResult<String> {
    let value = py_to_json_value(obj)?;
    serde_json::to_string_pretty(&value).map_err(|e| {
        pyo3::exceptions::PyValueError::new_err(format!("JSON serialization error: {}", e))
    })
}
