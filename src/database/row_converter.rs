use chrono::{NaiveDate, NaiveDateTime, NaiveTime, Datelike, Timelike};
use pyo3::prelude::*;
use pyo3::types::{
    PyBool, PyDate, PyDateAccess, PyDateTime, PyDict, PyList, 
    PyTime, PyTimeAccess, PyBytes,
};
use rust_decimal::Decimal;
use serde_json::Value as JsonValue;
use tokio_postgres::Row;
use tokio_postgres::types::{ToSql, Type};

/// Wrapper for dynamic PostgreSQL parameters that implements ToSql
#[derive(Debug)]
pub enum DynParam {
    Null,
    Bool(bool),
    I16(i16),
    I32(i32),
    I64(i64),
    F32(f32),
    F64(f64),
    Decimal(Decimal),
    Text(String),
    Bytes(Vec<u8>),
    Date(NaiveDate),
    Time(NaiveTime),
    Timestamp(NaiveDateTime),
    Json(JsonValue),
}

impl ToSql for DynParam {
    fn to_sql(
        &self,
        ty: &Type,
        out: &mut bytes::BytesMut,
    ) -> Result<postgres_types::IsNull, Box<dyn std::error::Error + Sync + Send>> {
        match self {
            DynParam::Null => Ok(postgres_types::IsNull::Yes),
            DynParam::Bool(v) => v.to_sql(ty, out),
            DynParam::I16(v) => {
                // Handle coercion for different integer target types
                match *ty {
                    Type::INT2 => v.to_sql(ty, out),
                    Type::INT4 => (*v as i32).to_sql(ty, out),
                    Type::INT8 => (*v as i64).to_sql(ty, out),
                    _ => v.to_sql(ty, out),
                }
            }
            DynParam::I32(v) => {
                match *ty {
                    Type::INT2 => (*v as i16).to_sql(ty, out),
                    Type::INT4 => v.to_sql(ty, out),
                    Type::INT8 => (*v as i64).to_sql(ty, out),
                    _ => v.to_sql(ty, out),
                }
            }
            DynParam::I64(v) => {
                // Coerce to target integer type
                match *ty {
                    Type::INT2 => (*v as i16).to_sql(ty, out),
                    Type::INT4 => (*v as i32).to_sql(ty, out),
                    Type::INT8 => v.to_sql(ty, out),
                    _ => v.to_sql(ty, out),
                }
            }
            DynParam::F32(v) => {
                match *ty {
                    Type::FLOAT4 => v.to_sql(ty, out),
                    Type::FLOAT8 => (*v as f64).to_sql(ty, out),
                    Type::NUMERIC => {
                        // Convert to Decimal for NUMERIC
                        let d = Decimal::from_f32_retain(*v).unwrap_or_default();
                        d.to_sql(ty, out)
                    }
                    _ => v.to_sql(ty, out),
                }
            }
            DynParam::F64(v) => {
                match *ty {
                    Type::FLOAT4 => (*v as f32).to_sql(ty, out),
                    Type::FLOAT8 => v.to_sql(ty, out),
                    Type::NUMERIC => {
                        // Convert to Decimal for NUMERIC
                        let d = Decimal::from_f64_retain(*v).unwrap_or_default();
                        d.to_sql(ty, out)
                    }
                    _ => v.to_sql(ty, out),
                }
            }
            DynParam::Decimal(v) => v.to_sql(ty, out),
            DynParam::Text(v) => v.to_sql(ty, out),
            DynParam::Bytes(v) => v.as_slice().to_sql(ty, out),
            DynParam::Date(v) => v.to_sql(ty, out),
            DynParam::Time(v) => v.to_sql(ty, out),
            DynParam::Timestamp(v) => v.to_sql(ty, out),
            DynParam::Json(v) => v.to_sql(ty, out),
        }
    }

    fn accepts(ty: &Type) -> bool {
        matches!(
            *ty,
            Type::BOOL
                | Type::INT2
                | Type::INT4
                | Type::INT8
                | Type::FLOAT4
                | Type::FLOAT8
                | Type::NUMERIC
                | Type::TEXT
                | Type::VARCHAR
                | Type::BYTEA
                | Type::DATE
                | Type::TIME
                | Type::TIMESTAMP
                | Type::TIMESTAMPTZ
                | Type::JSON
                | Type::JSONB
        ) || ty.name() == "text"
            || ty.name() == "varchar"
            || ty.name() == "numeric"
    }

    postgres_types::to_sql_checked!();
}

/// Utility struct for row conversion operations
pub struct RowConverter;

impl RowConverter {
    /// Convert a PostgreSQL row to a Python dictionary
    pub fn row_to_py_dict(py: Python<'_>, row: &Row) -> PyResult<Py<PyAny>> {
        let dict = PyDict::new(py);
        
        for (i, column) in row.columns().iter().enumerate() {
            let name = column.name();
            let ty = column.type_();
            
            let value: Py<PyAny> = match *ty {
                Type::BOOL => {
                    match row.try_get::<_, Option<bool>>(i) {
                        Ok(Some(v)) => PyBool::new(py, v).to_owned().into_any().unbind(),
                        Ok(None) => py.None(),
                        Err(_) => py.None(),
                    }
                }
                Type::INT2 => {
                    match row.try_get::<_, Option<i16>>(i) {
                        Ok(Some(v)) => v.into_pyobject(py)?.into_any().unbind(),
                        Ok(None) => py.None(),
                        Err(_) => py.None(),
                    }
                }
                Type::INT4 => {
                    match row.try_get::<_, Option<i32>>(i) {
                        Ok(Some(v)) => v.into_pyobject(py)?.into_any().unbind(),
                        Ok(None) => py.None(),
                        Err(_) => py.None(),
                    }
                }
                Type::INT8 => {
                    match row.try_get::<_, Option<i64>>(i) {
                        Ok(Some(v)) => v.into_pyobject(py)?.into_any().unbind(),
                        Ok(None) => py.None(),
                        Err(_) => py.None(),
                    }
                }
                Type::FLOAT4 => {
                    match row.try_get::<_, Option<f32>>(i) {
                        Ok(Some(v)) => v.into_pyobject(py)?.into_any().unbind(),
                        Ok(None) => py.None(),
                        Err(_) => py.None(),
                    }
                }
                Type::FLOAT8 => {
                    match row.try_get::<_, Option<f64>>(i) {
                        Ok(Some(v)) => v.into_pyobject(py)?.into_any().unbind(),
                        Ok(None) => py.None(),
                        Err(_) => py.None(),
                    }
                }
                Type::TEXT | Type::VARCHAR | Type::BPCHAR | Type::NAME => {
                    match row.try_get::<_, Option<String>>(i) {
                        Ok(Some(v)) => v.into_pyobject(py)?.into_any().unbind(),
                        Ok(None) => py.None(),
                        Err(_) => py.None(),
                    }
                }
                Type::BYTEA => {
                    match row.try_get::<_, Option<Vec<u8>>>(i) {
                        Ok(Some(v)) => PyBytes::new(py, &v).into_any().unbind(),
                        Ok(None) => py.None(),
                        Err(_) => py.None(),
                    }
                }
                Type::DATE => {
                    match row.try_get::<_, Option<NaiveDate>>(i) {
                        Ok(Some(v)) => {
                            PyDate::new(py, v.year(), v.month() as u8, v.day() as u8)?
                                .into_any().unbind()
                        }
                        Ok(None) => py.None(),
                        Err(_) => py.None(),
                    }
                }
                Type::TIME => {
                    match row.try_get::<_, Option<NaiveTime>>(i) {
                        Ok(Some(v)) => {
                            PyTime::new(
                                py,
                                v.hour() as u8,
                                v.minute() as u8,
                                v.second() as u8,
                                v.nanosecond() / 1000,
                                None,
                            )?.into_any().unbind()
                        }
                        Ok(None) => py.None(),
                        Err(_) => py.None(),
                    }
                }
                Type::TIMESTAMP | Type::TIMESTAMPTZ => {
                    match row.try_get::<_, Option<NaiveDateTime>>(i) {
                        Ok(Some(v)) => {
                            PyDateTime::new(
                                py,
                                v.year(),
                                v.month() as u8,
                                v.day() as u8,
                                v.hour() as u8,
                                v.minute() as u8,
                                v.second() as u8,
                                v.nanosecond() / 1000,
                                None,
                            )?.into_any().unbind()
                        }
                        Ok(None) => py.None(),
                        Err(_) => py.None(),
                    }
                }
                Type::JSON | Type::JSONB => {
                    match row.try_get::<_, Option<JsonValue>>(i) {
                        Ok(Some(v)) => Self::json_to_py(py, &v)?,
                        Ok(None) => py.None(),
                        Err(_) => py.None(),
                    }
                }
                Type::NUMERIC => {
                    // Handle NUMERIC/DECIMAL - convert to string first, then to Python Decimal
                    match row.try_get::<_, Option<Decimal>>(i) {
                        Ok(Some(v)) => {
                            // Convert to Python Decimal for precision
                            let decimal_module = py.import("decimal")?;
                            let py_decimal = decimal_module.call_method1("Decimal", (v.to_string(),))?;
                            py_decimal.into_any().unbind()
                        }
                        Ok(None) => py.None(),
                        Err(_) => {
                            // Fallback: try as string
                            match row.try_get::<_, Option<String>>(i) {
                                Ok(Some(v)) => v.into_pyobject(py)?.into_any().unbind(),
                                Ok(None) => py.None(),
                                Err(_) => py.None(),
                            }
                        }
                    }
                }
                _ => {
                    // Try to get as string for unknown types
                    match row.try_get::<_, Option<String>>(i) {
                        Ok(Some(v)) => v.into_pyobject(py)?.into_any().unbind(),
                        Ok(None) => py.None(),
                        Err(_) => py.None(),
                    }
                }
            };
            
            dict.set_item(name, value)?;
        }
        
        Ok(dict.into_any().unbind())
    }

    /// Convert JSON value to Python object
    fn json_to_py(py: Python<'_>, value: &JsonValue) -> PyResult<Py<PyAny>> {
        match value {
            JsonValue::Null => Ok(py.None()),
            JsonValue::Bool(b) => Ok(PyBool::new(py, *b).to_owned().into_any().unbind()),
            JsonValue::Number(n) => {
                if let Some(i) = n.as_i64() {
                    Ok(i.into_pyobject(py)?.into_any().unbind())
                } else if let Some(f) = n.as_f64() {
                    Ok(f.into_pyobject(py)?.into_any().unbind())
                } else {
                    Ok(py.None())
                }
            }
            JsonValue::String(s) => Ok(s.into_pyobject(py)?.into_any().unbind()),
            JsonValue::Array(arr) => {
                let py_list = PyList::empty(py);
                for item in arr {
                    py_list.append(Self::json_to_py(py, item)?)?;
                }
                Ok(py_list.into_any().unbind())
            }
            JsonValue::Object(obj) => {
                let py_dict = PyDict::new(py);
                for (k, v) in obj {
                    py_dict.set_item(k, Self::json_to_py(py, v)?)?;
                }
                Ok(py_dict.into_any().unbind())
            }
        }
    }

    /// Convert Python parameters to DynParam list
    pub fn convert_params_from_py(
        py: Python<'_>,
        params: &[Py<PyAny>],
    ) -> PyResult<Vec<DynParam>> {
        let mut result: Vec<DynParam> = Vec::with_capacity(params.len());
        
        for param in params {
            let param = param.bind(py);
            let dyn_param = if param.is_none() {
                DynParam::Null
            } else if let Ok(b) = param.extract::<bool>() {
                DynParam::Bool(b)
            } else if let Ok(i) = param.extract::<i64>() {
                DynParam::I64(i)
            } else if let Ok(f) = param.extract::<f64>() {
                DynParam::F64(f)
            } else if let Ok(s) = param.extract::<String>() {
                DynParam::Text(s)
            } else if param.is_instance_of::<PyDateTime>() {
                let dt = param.cast::<PyDateTime>()?;
                let naive = NaiveDateTime::new(
                    NaiveDate::from_ymd_opt(
                        dt.get_year(),
                        dt.get_month() as u32,
                        dt.get_day() as u32,
                    ).unwrap(),
                    NaiveTime::from_hms_nano_opt(
                        dt.get_hour() as u32,
                        dt.get_minute() as u32,
                        dt.get_second() as u32,
                        dt.get_microsecond() * 1000,
                    ).unwrap(),
                );
                DynParam::Timestamp(naive)
            } else if param.is_instance_of::<PyDate>() {
                let d = param.cast::<PyDate>()?;
                let naive = NaiveDate::from_ymd_opt(
                    d.get_year(),
                    d.get_month() as u32,
                    d.get_day() as u32,
                ).unwrap();
                DynParam::Date(naive)
            } else if param.is_instance_of::<PyTime>() {
                let t = param.cast::<PyTime>()?;
                let naive = NaiveTime::from_hms_nano_opt(
                    t.get_hour() as u32,
                    t.get_minute() as u32,
                    t.get_second() as u32,
                    t.get_microsecond() * 1000,
                ).unwrap();
                DynParam::Time(naive)
            } else if param.is_instance_of::<PyDict>() || param.is_instance_of::<PyList>() {
                // Convert dict/list to JSON properly using Python's json module
                let json_module = py.import("json")?;
                let json_str: String = json_module.call_method1("dumps", (param,))?.extract()?;
                let json_value: JsonValue = serde_json::from_str(&json_str)
                    .unwrap_or(JsonValue::Null);
                DynParam::Json(json_value)
            } else if let Ok(bytes) = param.extract::<Vec<u8>>() {
                DynParam::Bytes(bytes)
            } else {
                // Fall back to string representation
                let s = param.str()?.to_string();
                DynParam::Text(s)
            };
            
            result.push(dyn_param);
        }
        
        Ok(result)
    }
}
