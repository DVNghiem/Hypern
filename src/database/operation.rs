use std::sync::Arc;

use chrono::{Datelike, NaiveDate, NaiveDateTime, NaiveTime, Timelike};
use futures::StreamExt;
use pyo3::{
    prelude::*,
    types::{
        PyBool, PyDate, PyDateAccess, PyDateTime, PyDict, PyFloat, PyInt, PyList, PyString, PyTime,
        PyTimeAccess,
    },
};
use serde_json::to_string;
use sqlx::{
    postgres::{PgArguments, PgRow},
    types::{Json, JsonValue},
    Column, Row, ValueRef,
};
use tokio::sync::Mutex;

/// A streaming row iterator that yields chunks of rows lazily.
/// This allows Python to iterate over large result sets without loading everything into memory.
#[pyclass]
pub struct RowStream {
    /// The chunks that have been fetched (we still collect, but can be improved with channels)
    chunks: Arc<Mutex<Vec<Vec<Py<PyAny>>>>>,
    /// Current chunk index
    current_index: Arc<Mutex<usize>>,
    /// Whether the stream has been fully consumed
    exhausted: Arc<Mutex<bool>>,
}

#[pymethods]
impl RowStream {
    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }
    
    fn __next__(&self, py: Python<'_>) -> Option<Vec<Py<PyAny>>> {
        let chunks = self.chunks.clone();
        let current_index = self.current_index.clone();
        let exhausted = self.exhausted.clone();
        
        let chunks_guard = futures::executor::block_on(async {
            chunks.lock().await
        });
        let mut index = futures::executor::block_on(async {
            current_index.lock().await
        });
        let mut is_exhausted = futures::executor::block_on(async {
            exhausted.lock().await
        });
        
        if *index >= chunks_guard.len() {
            *is_exhausted = true;
            return None;
        }
        
        let chunk: Vec<Py<PyAny>> = chunks_guard[*index]
            .iter()
            .map(|item| item.clone_ref(py))
            .collect();
        *index += 1;
        Some(chunk)
    }
    
    fn is_exhausted(&self) -> bool {
        futures::executor::block_on(async {
            *self.exhausted.lock().await
        })
    }
    
    fn chunk_count(&self) -> usize {
        futures::executor::block_on(async {
            self.chunks.lock().await.len()
        })
    }
}

impl RowStream {
    pub fn new(chunks: Vec<Vec<Py<PyAny>>>) -> Self {
        Self {
            chunks: Arc::new(Mutex::new(chunks)),
            current_index: Arc::new(Mutex::new(0)),
            exhausted: Arc::new(Mutex::new(false)),
        }
    }
}

pub struct ParameterBinder;

impl ParameterBinder {

    fn bind_parameters<'q>(
        &self,
        py: Python<'_>,
        query: &'q str,
        params: Vec<Py<PyAny>>,
    ) -> Result<sqlx::query::Query<'q, sqlx::Postgres, PgArguments>, PyErr> {

        let mut query_builder = sqlx::query(query);

        for param in params {
            let p = param.bind(py);
            query_builder = if p.is_none() {
                query_builder.bind(None::<Option<String>>)
            } else if p.is_instance_of::<PyString>() {
                query_builder.bind(p.extract::<String>()?)
            } else if p.is_instance_of::<PyBool>() {
                query_builder.bind(p.extract::<bool>()?)
            } else if p.is_instance_of::<PyInt>() {
                query_builder.bind(p.extract::<i64>()?)
            } else if p.is_instance_of::<PyFloat>() {
                query_builder.bind(p.extract::<f64>()?)
            } else if p.is_instance_of::<PyDateTime>() {
                let dt = p.cast::<PyDateTime>()?;
                let naive_dt = NaiveDateTime::new(
                    NaiveDate::from_ymd_opt(
                        dt.get_year(),
                        dt.get_month() as u32,
                        dt.get_day() as u32,
                    )
                    .unwrap(),
                    NaiveTime::from_hms_nano_opt(
                        dt.get_hour() as u32,
                        dt.get_minute() as u32,
                        dt.get_second() as u32,
                        dt.get_microsecond() as u32 * 1000,
                    )
                    .unwrap(),
                );
                query_builder.bind(naive_dt)
            } else if p.is_instance_of::<PyDate>() {
                let date = p.cast::<PyDate>()?;
                let naive_date = NaiveDate::from_ymd_opt(
                    date.get_year(),
                    date.get_month() as u32,
                    date.get_day() as u32,
                )
                .unwrap();
                query_builder.bind(naive_date)
            } else if p.is_instance_of::<PyTime>() {
                let time = p.cast::<PyTime>()?;
                let naive_time = NaiveTime::from_hms_nano_opt(
                    time.get_hour() as u32,
                    time.get_minute() as u32,
                    time.get_second() as u32,
                    time.get_microsecond() as u32 * 1000,
                )
                .unwrap();
                query_builder.bind(naive_time)
            } else if p.is_instance_of::<PyDict>() {
                let dict = p.cast::<PyDict>()?;
                let json_value: JsonValue =
                    serde_json::from_str(&dict.to_string()).unwrap_or(JsonValue::Null);
                query_builder.bind(Json(json_value))
            } else if p.is_instance_of::<PyList>() {
                let list = p.cast::<PyList>()?;
                let json_value: JsonValue =
                    serde_json::from_str(&list.to_string()).unwrap_or(JsonValue::Null);
                query_builder.bind(Json(json_value))
            } else {
                return Err(PyErr::new::<pyo3::exceptions::PyTypeError, _>(format!(
                    "Unsupported parameter type: {:?}",
                    p.get_type()
                )))
            };
        }
        

        Ok(query_builder)
    }

    fn bind_result(&self, py: Python<'_>, row: &PgRow) -> Result<Py<PyAny>, PyErr> {
        let dict = PyDict::new(py);

        for (i, column) in row.columns().iter().enumerate() {
            let column_name = column.name();

            // Dynamically handle different column types
            match row.try_get_raw(i) {
                Ok(val) => {
                    if val.is_null() {
                        dict.set_item(column_name, py.None())?;
                    } else {
                        // Primitive Types
                        if let Ok(int_val) = row.try_get::<i32, _>(i) {
                            dict.set_item(column_name, int_val)?;
                        } else if let Ok(bigint_val) = row.try_get::<i64, _>(i) {
                            dict.set_item(column_name, bigint_val)?;
                        } else if let Ok(str_val) = row.try_get::<String, _>(i) {
                            dict.set_item(column_name, str_val)?;
                        } else if let Ok(float_val) = row.try_get::<f64, _>(i) {
                            dict.set_item(column_name, float_val)?;
                        } else if let Ok(bool_val) = row.try_get::<bool, _>(i) {
                            dict.set_item(column_name, bool_val)?;
                        }
                        // Date and Time Types
                        else if let Ok(datetime_val) = row.try_get::<NaiveDateTime, _>(i) {
                            let py_datetime = PyDateTime::new(
                                py,
                                datetime_val.year(),
                                datetime_val.month() as u8,
                                datetime_val.day() as u8,
                                datetime_val.hour() as u8,
                                datetime_val.minute() as u8,
                                datetime_val.second() as u8,
                                (datetime_val.nanosecond() / 1000) as u32,
                                None,
                            )?;
                            dict.set_item(column_name, py_datetime)?;
                        } else if let Ok(date_val) = row.try_get::<NaiveDate, _>(i) {
                            let py_date = PyDate::new(
                                py,
                                date_val.year(),
                                date_val.month() as u8,
                                date_val.day() as u8,
                            )?;
                            dict.set_item(column_name, py_date)?;
                        } else if let Ok(time_val) = row.try_get::<NaiveTime, _>(i) {
                            let py_time = PyTime::new(
                                py,
                                time_val.hour() as u8,
                                time_val.minute() as u8,
                                time_val.second() as u8,
                                (time_val.nanosecond() / 1000) as u32,
                                None,
                            )?;
                            dict.set_item(column_name, py_time)?;
                        }
                        // JSONB and Complex Types
                        else if let Ok(json_val) = row.try_get::<Json<JsonValue>, _>(i) {
                            // Convert JSON to Python object
                            let json_str = to_string(&json_val.0).map_err(|e| {
                                PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string())
                            })?;

                            dict.set_item(column_name, json_str)?;
                        }
                        else if let Ok(str_array) = row.try_get::<Vec<String>, _>(i) {
                            let py_list = PyList::new(py, &str_array)?;
                            dict.set_item(column_name, py_list)?;
                        } else if let Ok(int_array) = row.try_get::<Vec<i32>, _>(i) {
                            let py_list = PyList::new(py, &int_array)?;
                            dict.set_item(column_name, py_list)?;
                        }
                        else {
                            dict.set_item(column_name, py.None())?;
                        }
                    }
                }
                Err(_) => {
                    dict.set_item(column_name, py.None())?;
                }
            }
        }

        Ok(dict.into())
    }
}

#[derive(Debug, Clone, Default)]
pub struct DatabaseOperations;

impl DatabaseOperations {

    pub async fn execute(
        &self,
        py: Python<'_>,
        transaction: Arc<Mutex<Option<sqlx::Transaction<'static, sqlx::Postgres>>>>,
        query: &str,
        params: Vec<Py<PyAny>>,
    ) -> Result<u64, PyErr> {
        let query_builder = ParameterBinder.bind_parameters(py, query, params)?;
        let mut guard = transaction.lock().await;
        let transaction = guard.as_mut().unwrap();
        let result = query_builder
            .execute(&mut **transaction)
            .await
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

        std::mem::drop(guard);
        Ok(result.rows_affected())
    }

    pub async fn fetch_all(
        &self,
        py: Python<'_>,
        transaction: Arc<Mutex<Option<sqlx::Transaction<'static, sqlx::Postgres>>>>,
        query: &str,
        params: Vec<Py<PyAny>>,
    ) -> Result<Vec<Py<PyAny>>, PyErr> {

        let query_builder = ParameterBinder.bind_parameters(py, query, params)?;
        let mut guard = transaction.lock().await;
        let transaction = guard.as_mut().unwrap();
        let rows = query_builder
            .fetch_all(&mut **transaction)
            .await
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

        let result: Vec<Py<PyAny>> = rows
            .iter()
            .map(|row| ParameterBinder.bind_result(py, row))
            .collect::<Result<Vec<_>, _>>()?;
        Ok(result)
    }

    pub async fn stream_data(
        &self,
        py: Python<'_>,
        transaction: Arc<Mutex<Option<sqlx::Transaction<'static, sqlx::Postgres>>>>,
        query: &str,
        params: Vec<Py<PyAny>>,
        chunk_size: usize,
    ) -> PyResult<RowStream> {
        let query_builder = ParameterBinder.bind_parameters(py, query, params)?;
        let mut guard = transaction.lock().await.take().unwrap();
        let mut stream = query_builder.fetch(&mut *guard);
        let mut chunks: Vec<Vec<Py<PyAny>>> = Vec::new();
        let mut current_chunk: Vec<Py<PyAny>> = Vec::new();

        while let Some(row_result) = stream.next().await {
            match row_result {
                Ok(row) => {
                    let row_data: Py<PyAny> = ParameterBinder.bind_result(py, &row)?;
                    current_chunk.push(row_data);

                    if current_chunk.len() >= chunk_size {
                        chunks.push(current_chunk);
                        current_chunk = Vec::new();
                    }
                }
                Err(e) => {
                    return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                        e.to_string(),
                    ));
                }
            }
        }

        if !current_chunk.is_empty() {
            chunks.push(current_chunk);
        }
        Ok(RowStream::new(chunks))
    }

    pub async fn bulk_change(
        &self,
        py: Python<'_>,
        transaction: Arc<Mutex<Option<sqlx::Transaction<'static, sqlx::Postgres>>>>,
        query: &str,
        params: Vec<Vec<Py<PyAny>>>,
        batch_size: usize,
    ) -> Result<u64, PyErr> {
        let mut total_affected: u64 = 0;
        let mut guard = transaction.lock().await;
        let tx = guard.as_mut().ok_or_else(|| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("No active transaction")
        })?;

        // Process in batches
        for chunk in params.chunks(batch_size) {
            for param_set in chunk {
                let cloned_params: Vec<Py<PyAny>> = param_set.iter().map(|p| p.clone_ref(py)).collect();
                let query_builder = ParameterBinder.bind_parameters(py, query, cloned_params)?;
                let result = query_builder.execute(&mut **tx).await.map_err(|e| {
                    PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string())
                })?;

                total_affected += result.rows_affected();
            }
        }
        Ok(total_affected)
    }
}