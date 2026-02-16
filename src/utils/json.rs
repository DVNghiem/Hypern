use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyFloat, PyInt, PyList, PyString};
use serde_json::Value as JsonValue;

/// Convert JSON value to Python object - optimized with type-specific checks
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

/// Convert Python object to JSON value - optimized with fast type checks
pub fn py_to_json_value(obj: &Bound<'_, PyAny>) -> PyResult<JsonValue> {
    if obj.is_none() {
        return Ok(JsonValue::Null);
    }

    // Use is_instance_of for fast type checking (avoids extract overhead for wrong types)
    // Check bool before int since bool is a subclass of int in Python
    if obj.is_instance_of::<PyBool>() {
        return Ok(JsonValue::Bool(obj.extract::<bool>()?));
    }

    if obj.is_instance_of::<PyInt>() {
        if let Ok(i) = obj.extract::<i64>() {
            return Ok(JsonValue::Number(i.into()));
        }
        // Fallback for very large ints
        if let Ok(u) = obj.extract::<u64>() {
            return Ok(JsonValue::Number(u.into()));
        }
        // Really large int - convert to string
        return Ok(JsonValue::String(obj.str()?.to_string()));
    }

    if obj.is_instance_of::<PyFloat>() {
        let f = obj.extract::<f64>()?;
        if let Some(n) = serde_json::Number::from_f64(f) {
            return Ok(JsonValue::Number(n));
        }
        return Ok(JsonValue::Null);
    }

    if obj.is_instance_of::<PyString>() {
        return Ok(JsonValue::String(obj.extract::<String>()?));
    }

    // Dict - most common complex type in JSON APIs
    if obj.is_instance_of::<PyDict>() {
        let dict = obj.cast::<PyDict>()?;
        let mut map = serde_json::Map::with_capacity(dict.len());
        for (key, value) in dict.iter() {
            let key_str = if key.is_instance_of::<PyString>() {
                key.extract::<String>()?
            } else {
                key.str()?.to_string()
            };
            map.insert(key_str, py_to_json_value(&value)?);
        }
        return Ok(JsonValue::Object(map));
    }

    // List
    if obj.is_instance_of::<PyList>() {
        let list = obj.cast::<PyList>()?;
        let mut arr = Vec::with_capacity(list.len());
        for item in list.iter() {
            arr.push(py_to_json_value(&item)?);
        }
        return Ok(JsonValue::Array(arr));
    }

    // Bytes - convert to string
    if let Ok(bytes) = obj.extract::<Vec<u8>>() {
        if let Ok(s) = String::from_utf8(bytes.clone()) {
            return Ok(JsonValue::String(s));
        }
        return Ok(JsonValue::String(
            String::from_utf8_lossy(&bytes).into_owned(),
        ));
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
            let d = dict.cast::<PyDict>()?;
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

/// Serialize Python object to JSON bytes using simd-json when possible.
pub fn serialize_py_to_json(obj: &Bound<'_, PyAny>) -> PyResult<Vec<u8>> {
    let value = py_to_json_value(obj)?;
    // Use simd-json for serialization - faster than serde_json
    simd_json::to_vec(&value).map_err(|e| {
        pyo3::exceptions::PyValueError::new_err(format!("JSON serialization error: {}", e))
    })
}

/// Serialize Python object to JSON string.
pub fn serialize_py_to_json_string(obj: &Bound<'_, PyAny>) -> PyResult<String> {
    let value = py_to_json_value(obj)?;
    // Use simd-json for serialization
    simd_json::to_string(&value).map_err(|e| {
        pyo3::exceptions::PyValueError::new_err(format!("JSON serialization error: {}", e))
    })
}

/// Serialize Python object to pretty-printed JSON string.
pub fn serialize_py_to_json_pretty(obj: &Bound<'_, PyAny>) -> PyResult<String> {
    let value = py_to_json_value(obj)?;
    // Pretty print still uses serde_json (simd-json doesn't have pretty print)
    serde_json::to_string_pretty(&value).map_err(|e| {
        pyo3::exceptions::PyValueError::new_err(format!("JSON serialization error: {}", e))
    })
}
