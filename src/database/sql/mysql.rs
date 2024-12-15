use std::sync::Arc;
use tokio::sync::Mutex;

use futures::StreamExt;
use pyo3::{prelude::*, types::PyDict};
use sqlx::{
    mysql::{MySqlArguments, MySqlRow},
    Column, Row, ValueRef,
};

use super::db_trait::{DatabaseOperations, DynamicParameterBinder};
// Similarly implement for other database types...
pub struct MySqlParameterBinder;

impl DynamicParameterBinder for MySqlParameterBinder {
    type Arguments = MySqlArguments;
    type Database = sqlx::MySql;
    type Row = MySqlRow;

    fn bind_parameters<'q>(
        &self,
        mut query_builder: sqlx::query::Query<'q, Self::Database, Self::Arguments>,
        params: Vec<&PyAny>,
    ) -> Result<sqlx::query::Query<'q, Self::Database, Self::Arguments>, PyErr> {
        // Create query with explicit lifetime

        // Bind parameters with lifetime preservation
        for param in params {
            query_builder = match param.extract::<String>() {
                // Use String instead of &str
                Ok(s) => query_builder.bind(s),
                Err(_) => match param.extract::<i64>() {
                    Ok(i) => query_builder.bind(i),
                    Err(_) => match param.extract::<f64>() {
                        Ok(f) => query_builder.bind(f),
                        Err(_) => match param.extract::<bool>() {
                            Ok(b) => query_builder.bind(b),
                            Err(_) => {
                                return Err(PyErr::new::<pyo3::exceptions::PyTypeError, _>(
                                    format!("Unsupported parameter type: {:?}", param.get_type()),
                                ))
                            }
                        },
                    },
                },
            };
        }

        Ok(query_builder)
    }

    fn bind_result(&self, py: Python<'_>, row: &MySqlRow) -> Result<PyObject, PyErr> {
        let dict = PyDict::new(py);

        for (i, column) in row.columns().iter().enumerate() {
            let column_name = column.name();

            // Dynamically handle different column types
            match row.try_get_raw(i) {
                Ok(val) => {
                    if val.is_null() {
                        dict.set_item(column_name, py.None()).unwrap();
                    } else if let Ok(int_val) = row.try_get::<i32, _>(i) {
                        dict.set_item(column_name, int_val).unwrap();
                    } else if let Ok(str_val) = row.try_get::<String, _>(i) {
                        dict.set_item(column_name, str_val).unwrap();
                    } else if let Ok(float_val) = row.try_get::<f64, _>(i) {
                        dict.set_item(column_name, float_val).unwrap();
                    } else if let Ok(bool_val) = row.try_get::<bool, _>(i) {
                        dict.set_item(column_name, bool_val).unwrap();
                    }
                }
                Err(_) => {
                    // Handle unsupported types or log an error
                    dict.set_item(column_name, py.None()).unwrap();
                }
            }
        }

        Ok(dict.into())
    }
}

#[derive(Debug, Clone, Default)]
pub struct MySqlDatabase;

impl DatabaseOperations for MySqlDatabase {
    type Row = MySqlRow;
    type Arguments = MySqlArguments;
    type DatabaseType = sqlx::MySql;
    type ParameterBinder = MySqlParameterBinder;

    async fn execute(
        &mut self,
        transaction: Arc<Mutex<Option<sqlx::Transaction<'static, sqlx::MySql>>>>,
        query: &str,
        params: Vec<&PyAny>,
    ) -> Result<u64, PyErr> {
        let query = sqlx::query(query);
        let query_builder = MySqlParameterBinder.bind_parameters(query, params)?;
        let mut guard = transaction.lock().await.take().unwrap();
        let result = query_builder
            .execute(&mut *guard)
            .await
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

        Ok(result.rows_affected())
    }

    async fn fetch_all(
        &mut self,
        py: Python<'_>,
        transaction: Arc<Mutex<Option<sqlx::Transaction<'static, Self::DatabaseType>>>>,
        query: &str,
        params: Vec<&PyAny>,
    ) -> Result<Vec<PyObject>, PyErr> {
        let query = sqlx::query(query);
        let query_builder = MySqlParameterBinder.bind_parameters(query, params)?;
        let mut guard  = transaction.lock().await;
        let transaction = guard.as_mut().unwrap();
        let rows = query_builder
            .fetch_all(&mut **transaction)
            .await
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

        let result: Vec<PyObject> = rows
            .iter()
            .map(|row| MySqlParameterBinder.bind_result(py, row))
            .collect::<Result<Vec<_>, _>>()?;

        Ok(result)
    }

    async fn stream_data(
        &mut self,
        py: Python<'_>,
        transaction: Arc<Mutex<Option<sqlx::Transaction<'static, sqlx::MySql>>>>,
        query: &str,
        params: Vec<&PyAny>,
        chunk_size: usize,
    ) -> PyResult<Vec<Vec<PyObject>>> {
        let query = sqlx::query(query);
        let query_builder = MySqlParameterBinder.bind_parameters(query, params)?;
        let mut guard = transaction.lock().await.take().unwrap();
        let mut stream = query_builder.fetch(&mut *guard);
        let mut chunks: Vec<Vec<PyObject>> = Vec::new();
        let mut current_chunk: Vec<PyObject> = Vec::new();

        while let Some(row_result) = stream.next().await {
            match row_result {
                Ok(row) => {
                    let row_data: PyObject = MySqlParameterBinder.bind_result(py, &row)?;
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
        Ok(chunks)
    }

    async fn bulk_create(
        &mut self,
        transaction: Arc<Mutex<Option<sqlx::Transaction<'static, Self::DatabaseType>>>>,
        query: &str,
        params: Vec<Vec<&PyAny>>,
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
                // Build query with current parameters
                let mut query_builder = sqlx::query(query);
                for param in param_set {
                    query_builder =
                        MySqlParameterBinder.bind_parameters(query_builder, vec![*param])?;
                }
                // Execute query and accumulate affected rows
                let result = query_builder.execute(&mut **tx).await.map_err(|e| {
                    PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string())
                })?;

                total_affected += result.rows_affected();
            }
        }
        Ok(total_affected)
    }
}
