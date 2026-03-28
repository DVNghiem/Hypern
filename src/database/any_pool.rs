//! Sqlx `Any` pool — lightweight multi-driver wrapper (MySQL / SQLite / Postgres).
//!
//! This is an additive module alongside the primary `deadpool-postgres` path.
//! It provides a simpler API for MySQL and SQLite users.

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use std::sync::OnceLock;

static ANY_RT: OnceLock<tokio::runtime::Runtime> = OnceLock::new();

fn any_runtime() -> &'static tokio::runtime::Runtime {
    ANY_RT.get_or_init(|| {
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("failed to create sqlx-any runtime")
    })
}

/// A multi-driver database pool backed by sqlx `Any` (MySQL / SQLite / Postgres).
#[pyclass]
pub struct AnyPool {
    pool: sqlx::Pool<sqlx::Any>,
}

#[pymethods]
impl AnyPool {
    /// Connect to a database.
    ///
    /// Args:
    ///     url: Database URL (``mysql://``, ``sqlite://``, ``postgres://``)
    ///     max_connections: Maximum pool size (default: 16)
    #[new]
    #[pyo3(signature = (url, max_connections = 16))]
    pub fn new(url: &str, max_connections: u32) -> PyResult<Self> {
        // Install all sqlx Any drivers at first use
        sqlx::any::install_default_drivers();

        let pool = any_runtime().block_on(async {
            sqlx::pool::PoolOptions::<sqlx::Any>::new()
                .max_connections(max_connections)
                .connect(url)
                .await
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
        })?;
        Ok(Self { pool })
    }

    /// Execute a SELECT query. Returns a list of dicts.
    ///
    /// Args:
    ///     sql: SQL query (use ``?`` placeholders for MySQL/SQLite, ``$1`` for Postgres)
    ///     params: Positional string parameters
    #[pyo3(signature = (sql, params = None))]
    pub fn query<'py>(
        &self,
        py: Python<'py>,
        sql: &str,
        params: Option<Vec<String>>,
    ) -> PyResult<Py<PyList>> {
        let pool = self.pool.clone();
        let sql = sql.to_owned();
        let params = params.unwrap_or_default();

        any_runtime().block_on(async {
            let mut q = sqlx::query(&sql);
            for p in &params {
                q = q.bind(p);
            }
            let rows = q
                .fetch_all(&pool)
                .await
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

            let list = PyList::empty(py);
            for row in &rows {
                let dict = any_row_to_dict(py, row)?;
                list.append(dict)?;
            }
            Ok(list.unbind())
        })
    }

    /// Execute a SELECT and return a single row dict.
    #[pyo3(signature = (sql, params = None))]
    pub fn query_one<'py>(
        &self,
        py: Python<'py>,
        sql: &str,
        params: Option<Vec<String>>,
    ) -> PyResult<Py<PyDict>> {
        let pool = self.pool.clone();
        let sql = sql.to_owned();
        let params = params.unwrap_or_default();

        any_runtime().block_on(async {
            let mut q = sqlx::query(&sql);
            for p in &params {
                q = q.bind(p);
            }
            let row = q
                .fetch_one(&pool)
                .await
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
            let dict = any_row_to_dict(py, &row)?;
            Ok(dict.unbind())
        })
    }

    /// Execute an INSERT / UPDATE / DELETE. Returns rows affected.
    #[pyo3(signature = (sql, params = None))]
    pub fn execute(&self, sql: &str, params: Option<Vec<String>>) -> PyResult<u64> {
        let pool = self.pool.clone();
        let sql = sql.to_owned();
        let params = params.unwrap_or_default();

        any_runtime().block_on(async {
            let mut q = sqlx::query(&sql);
            for p in &params {
                q = q.bind(p);
            }
            let result = q
                .execute(&pool)
                .await
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
            Ok(result.rows_affected())
        })
    }

    /// Close the pool.
    pub fn close(&self) {
        any_runtime().block_on(async {
            self.pool.close().await;
        });
    }

    fn __repr__(&self) -> String {
        format!(
            "AnyPool(size={}, idle={})",
            self.pool.size(),
            self.pool.num_idle()
        )
    }
}

/// Convert a sqlx `AnyRow` to a Python dict.
fn any_row_to_dict<'py>(py: Python<'py>, row: &sqlx::any::AnyRow) -> PyResult<pyo3::Bound<'py, PyDict>> {
    use sqlx::Row;
    use sqlx::Column;
    use sqlx::TypeInfo;

    let dict = PyDict::new(py);
    for (i, col) in row.columns().iter().enumerate() {
        let name = col.name();
        let type_name = col.type_info().name();
        let val: Py<pyo3::PyAny> = match type_name {
            "BOOLEAN" | "BOOL" => {
                let v: Option<bool> = row.try_get(i).ok();
                match v {
                    Some(b) => b.into_pyobject(py)?.to_owned().into_any().unbind(),
                    None => py.None(),
                }
            }
            "INT2" | "SMALLINT" | "TINYINT" | "INT" | "INTEGER" | "INT4" | "INT8" | "BIGINT" => {
                let v: Option<i64> = row.try_get(i).ok();
                match v {
                    Some(n) => n.into_pyobject(py)?.to_owned().into_any().unbind(),
                    None => py.None(),
                }
            }
            "FLOAT4" | "FLOAT8" | "REAL" | "DOUBLE" | "FLOAT" => {
                let v: Option<f64> = row.try_get(i).ok();
                match v {
                    Some(f) => f.into_pyobject(py)?.to_owned().into_any().unbind(),
                    None => py.None(),
                }
            }
            "TEXT" | "VARCHAR" | "CHAR" | "BPCHAR" | "NAME" | "TINYTEXT" | "MEDIUMTEXT"
            | "LONGTEXT" => {
                let v: Option<String> = row.try_get(i).ok();
                match v {
                    Some(s) => s.into_pyobject(py)?.into_any().unbind(),
                    None => py.None(),
                }
            }
            "BLOB" | "BYTEA" | "BINARY" | "VARBINARY" | "TINYBLOB" | "MEDIUMBLOB"
            | "LONGBLOB" => {
                let v: Option<Vec<u8>> = row.try_get(i).ok();
                match v {
                    Some(b) => b.into_pyobject(py)?.into_any().unbind(),
                    None => py.None(),
                }
            }
            _ => {
                // Fallback: try as string
                let v: Option<String> = row.try_get(i).ok();
                match v {
                    Some(s) => s.into_pyobject(py)?.into_any().unbind(),
                    None => py.None(),
                }
            }
        };
        dict.set_item(name, val)?;
    }
    Ok(dict)
}
