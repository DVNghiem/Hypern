use dashmap::DashMap;
use deadpool_postgres::Object;
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use std::collections::HashMap;
use std::sync::{Arc, Mutex, OnceLock};
use tokio_postgres::Row;

use super::pool::{get_db_runtime, ConnectionPoolManager};
use super::row_converter::{DynParam, RowConverter};

fn format_db_error(e: &tokio_postgres::Error) -> String {
    if let Some(db_error) = e.as_db_error() {
        // Extract detailed PostgreSQL error information
        let mut msg = format!(
            "PostgreSQL error: {} (SQLSTATE {})",
            db_error.message(),
            db_error.code().code()
        );
        if let Some(detail) = db_error.detail() {
            msg.push_str(&format!("\nDetail: {}", detail));
        }
        if let Some(hint) = db_error.hint() {
            msg.push_str(&format!("\nHint: {}", hint));
        }
        if let Some(position) = db_error.position() {
            msg.push_str(&format!("\nPosition: {:?}", position));
        }
        msg
    } else {
        // Not a database error, use the standard display
        format!("{}", e)
    }
}

/// Global map of request_id -> (alias -> DatabaseContext) for cross-function access
static REQUEST_CONTEXTS: OnceLock<DashMap<String, HashMap<String, Arc<DatabaseContextInner>>>> =
    OnceLock::new();

fn get_contexts() -> &'static DashMap<String, HashMap<String, Arc<DatabaseContextInner>>> {
    REQUEST_CONTEXTS.get_or_init(DashMap::new)
}

/// Internal state of a database context
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ContextState {
    /// No connection or transaction
    Idle,
    /// Connection acquired, no active transaction
    Connected,
    /// Transaction is active
    InTransaction,
    /// Transaction committed
    Committed,
    /// Transaction rolled back
    RolledBack,
    /// Context is closed
    Closed,
}

pub struct DatabaseContextInner {
    request_id: String,
    alias: String,
    /// The database connection (acquired lazily)
    connection: Mutex<Option<Object>>,
    /// Current state
    state: Mutex<ContextState>,
    /// Whether to auto-commit on success
    auto_commit: Mutex<bool>,
    /// Whether an error occurred during the request
    has_error: Mutex<bool>,
    /// Whether we're in a transaction
    in_transaction: Mutex<bool>,
}

impl DatabaseContextInner {
    pub fn new(request_id: String, alias: String) -> Self {
        Self {
            request_id,
            alias,
            connection: Mutex::new(None),
            state: Mutex::new(ContextState::Idle),
            auto_commit: Mutex::new(true),
            has_error: Mutex::new(false),
            in_transaction: Mutex::new(false),
        }
    }

    pub fn request_id(&self) -> &str {
        &self.request_id
    }

    pub fn alias(&self) -> &str {
        &self.alias
    }

    pub fn state(&self) -> ContextState {
        *self.state.lock().unwrap()
    }

    pub fn set_auto_commit(&self, auto_commit: bool) {
        *self.auto_commit.lock().unwrap() = auto_commit;
    }

    pub fn set_error(&self) {
        *self.has_error.lock().unwrap() = true;
    }

    pub fn has_error(&self) -> bool {
        *self.has_error.lock().unwrap()
    }

    fn take_connection(&self) -> Option<Object> {
        self.connection.lock().unwrap().take()
    }

    fn put_connection(&self, conn: Object) {
        *self.connection.lock().unwrap() = Some(conn);
    }

    fn has_connection(&self) -> bool {
        self.connection.lock().unwrap().is_some()
    }

    async fn ensure_connection(&self) -> Result<(), String> {
        if self.has_connection() {
            return Ok(());
        }

        let pool = ConnectionPoolManager::get_pool_by_alias(&self.alias)
            .ok_or_else(|| format!("Connection pool for alias '{}' not initialized", self.alias))?;

        let conn = pool
            .get()
            .await
            .map_err(|e| format!("Failed to acquire connection: {}", e))?;

        self.put_connection(conn);
        *self.state.lock().unwrap() = ContextState::Connected;
        Ok(())
    }

    pub async fn begin(&self) -> Result<(), String> {
        self.ensure_connection().await?;

        let in_tx = *self.in_transaction.lock().unwrap();
        if in_tx {
            return Err("Transaction already active".to_string());
        }

        let conn = self
            .take_connection()
            .ok_or_else(|| "No connection available".to_string())?;

        let result = conn.execute("BEGIN", &[]).await;
        self.put_connection(conn);

        result.map_err(|e| format!("Failed to begin transaction: {}", e))?;

        *self.in_transaction.lock().unwrap() = true;
        *self.state.lock().unwrap() = ContextState::InTransaction;
        Ok(())
    }

    pub async fn commit(&self) -> Result<(), String> {
        let in_tx = *self.in_transaction.lock().unwrap();
        if !in_tx {
            return Err("No active transaction to commit".to_string());
        }

        let conn = self
            .take_connection()
            .ok_or_else(|| "No connection available".to_string())?;

        let result = conn.execute("COMMIT", &[]).await;
        self.put_connection(conn);

        result.map_err(|e| format!("Failed to commit transaction: {}", e))?;

        *self.in_transaction.lock().unwrap() = false;
        *self.state.lock().unwrap() = ContextState::Committed;
        Ok(())
    }

    pub async fn rollback(&self) -> Result<(), String> {
        let in_tx = *self.in_transaction.lock().unwrap();
        if !in_tx {
            return Err("No active transaction to rollback".to_string());
        }

        let conn = self
            .take_connection()
            .ok_or_else(|| "No connection available".to_string())?;

        let result = conn.execute("ROLLBACK", &[]).await;
        self.put_connection(conn);

        result.map_err(|e| format!("Failed to rollback transaction: {}", e))?;

        *self.in_transaction.lock().unwrap() = false;
        *self.state.lock().unwrap() = ContextState::RolledBack;
        Ok(())
    }

    pub async fn query(&self, sql: &str, params: &[DynParam]) -> Result<Vec<Row>, String> {
        self.ensure_connection().await?;

        let param_refs: Vec<&(dyn tokio_postgres::types::ToSql + Sync)> = params
            .iter()
            .map(|p| p as &(dyn tokio_postgres::types::ToSql + Sync))
            .collect();

        let conn = self
            .take_connection()
            .ok_or_else(|| "No connection available".to_string())?;

        let result = conn.query(sql, &param_refs).await;
        self.put_connection(conn);

        result.map_err(|e| format!("Query failed: {}", format_db_error(&e)))
    }

    pub async fn execute(&self, sql: &str, params: &[DynParam]) -> Result<u64, String> {
        self.ensure_connection().await?;

        let param_refs: Vec<&(dyn tokio_postgres::types::ToSql + Sync)> = params
            .iter()
            .map(|p| p as &(dyn tokio_postgres::types::ToSql + Sync))
            .collect();

        let conn = self
            .take_connection()
            .ok_or_else(|| "No connection available".to_string())?;

        let result = conn.execute(sql, &param_refs).await;
        self.put_connection(conn);

        result.map_err(|e| format!("Execute failed: {}", format_db_error(&e)))
    }

    pub async fn finalize(&self) -> Result<(), String> {
        let in_tx = *self.in_transaction.lock().unwrap();
        let has_error = *self.has_error.lock().unwrap();
        let auto_commit = *self.auto_commit.lock().unwrap();

        if in_tx {
            if has_error {
                self.rollback().await?;
            } else if auto_commit {
                self.commit().await?;
            } else {
                self.rollback().await?;
            }
        }

        let conn = self.connection.lock().unwrap().take();

        // Spawn a task to drop the connection, so it doesn't block
        // This allows deadpool to recycle properly
        if let Some(conn) = conn {
            tokio::spawn(async move {
                // Connection drops here when the task completes
                drop(conn);
            });
        }

        *self.state.lock().unwrap() = ContextState::Closed;

        // Remove from global context map
        let contexts = get_contexts();
        if let Some(mut request_contexts) = contexts.get_mut(&self.request_id) {
            request_contexts.remove(&self.alias);
            if request_contexts.is_empty() {
                drop(request_contexts);
                contexts.remove(&self.request_id);
            }
        }
        Ok(())
    }
}

#[pyclass(from_py_object)]
#[derive(Clone)]
pub struct DbSession {
    context: Arc<DatabaseContextInner>,
}

impl DbSession {
    pub fn new(context: Arc<DatabaseContextInner>) -> Self {
        Self { context }
    }

    pub fn context(&self) -> &Arc<DatabaseContextInner> {
        &self.context
    }
}

#[pymethods]
impl DbSession {
    #[getter]
    fn request_id(&self) -> String {
        self.context.request_id().to_string()
    }

    fn begin(&self) -> PyResult<()> {
        let ctx = self.context.clone();
        get_db_runtime()
            .block_on(async move { ctx.begin().await })
            .map_err(|e| PyRuntimeError::new_err(e))
    }

    fn commit(&self) -> PyResult<()> {
        let ctx = self.context.clone();
        get_db_runtime()
            .block_on(async move { ctx.commit().await })
            .map_err(|e| PyRuntimeError::new_err(e))
    }

    fn rollback(&self) -> PyResult<()> {
        let ctx = self.context.clone();
        get_db_runtime()
            .block_on(async move { ctx.rollback().await })
            .map_err(|e| PyRuntimeError::new_err(e))
    }

    #[pyo3(signature = (sql, params=None))]
    fn query(
        &self,
        py: Python<'_>,
        sql: &str,
        params: Option<Vec<Py<PyAny>>>,
    ) -> PyResult<Vec<Py<PyAny>>> {
        let ctx = self.context.clone();
        let sql = sql.to_string();
        let params = params.unwrap_or_default();

        let converted_params = RowConverter::convert_params_from_py(py, &params)?;

        let rows = get_db_runtime()
            .block_on(async move { ctx.query(&sql, &converted_params).await })
            .map_err(|e| PyRuntimeError::new_err(e))?;

        rows.iter()
            .map(|row| RowConverter::row_to_py_dict(py, row))
            .collect()
    }

    #[pyo3(signature = (sql, params=None))]
    fn query_one(
        &self,
        py: Python<'_>,
        sql: &str,
        params: Option<Vec<Py<PyAny>>>,
    ) -> PyResult<Py<PyAny>> {
        let ctx = self.context.clone();
        let sql = sql.to_string();
        let params = params.unwrap_or_default();

        let converted_params = RowConverter::convert_params_from_py(py, &params)?;

        let rows = get_db_runtime()
            .block_on(async move { ctx.query(&sql, &converted_params).await })
            .map_err(|e| PyRuntimeError::new_err(e))?;

        let row = rows
            .into_iter()
            .next()
            .ok_or_else(|| PyRuntimeError::new_err("No rows returned"))?;

        RowConverter::row_to_py_dict(py, &row)
    }

    #[pyo3(signature = (sql, params=None))]
    fn execute(&self, py: Python<'_>, sql: &str, params: Option<Vec<Py<PyAny>>>) -> PyResult<u64> {
        let ctx = self.context.clone();
        let sql = sql.to_string();
        let params = params.unwrap_or_default();

        let converted_params = RowConverter::convert_params_from_py(py, &params)?;

        get_db_runtime()
            .block_on(async move { ctx.execute(&sql, &converted_params).await })
            .map_err(|e| PyRuntimeError::new_err(e))
    }

    #[pyo3(signature = (sql, params_list))]
    fn execute_many(
        &self,
        py: Python<'_>,
        sql: &str,
        params_list: Vec<Vec<Py<PyAny>>>,
    ) -> PyResult<u64> {
        let ctx = self.context.clone();
        let sql = sql.to_string();

        let mut total_affected = 0u64;
        for params in params_list {
            let converted_params = RowConverter::convert_params_from_py(py, &params)?;
            let sql_clone = sql.clone();
            let ctx_clone = ctx.clone();

            let affected = get_db_runtime()
                .block_on(async move { ctx_clone.execute(&sql_clone, &converted_params).await })
                .map_err(|e| PyRuntimeError::new_err(e))?;

            total_affected += affected;
        }

        Ok(total_affected)
    }

    fn set_auto_commit(&self, auto_commit: bool) -> PyResult<()> {
        self.context.set_auto_commit(auto_commit);
        Ok(())
    }

    fn set_error(&self) -> PyResult<()> {
        self.context.set_error();
        Ok(())
    }

    fn state(&self) -> PyResult<String> {
        let state = self.context.state();
        Ok(format!("{:?}", state))
    }

    fn __repr__(&self) -> String {
        format!(
            "DbSession(request_id='{}', alias='{}')",
            self.context.request_id(),
            self.context.alias()
        )
    }
}

pub fn create_request_context(request_id: &str, alias: &str) -> Arc<DatabaseContextInner> {
    let ctx = Arc::new(DatabaseContextInner::new(
        request_id.to_string(),
        alias.to_string(),
    ));

    let contexts = get_contexts();
    let mut request_contexts = contexts
        .entry(request_id.to_string())
        .or_insert_with(HashMap::new);
    request_contexts.insert(alias.to_string(), ctx.clone());

    ctx
}

pub fn get_request_context(request_id: &str, alias: &str) -> Option<Arc<DatabaseContextInner>> {
    get_contexts().get(request_id)?.get(alias).cloned()
}

pub async fn finalize_request_context(request_id: &str, alias: &str) -> Result<(), String> {
    // Clone the context out of the DashMap first
    let ctx_opt = {
        get_contexts()
            .get(request_id)
            .and_then(|contexts| contexts.get(alias).cloned())
    };

    if let Some(ctx) = ctx_opt {
        ctx.finalize().await?;
    }
    Ok(())
}

pub async fn finalize_all_request_contexts(request_id: &str) -> Result<(), String> {
    // Clone all contexts for this request
    let contexts_opt = { get_contexts().get(request_id).map(|r| r.clone()) };

    if let Some(contexts) = contexts_opt {
        for (_, ctx) in contexts {
            ctx.finalize().await?;
        }
    }
    Ok(())
}

#[pyfunction]
pub fn get_db(request_id: &str, alias: &str) -> PyResult<DbSession> {
    let ctx = get_request_context(request_id, alias)
        .unwrap_or_else(|| create_request_context(request_id, alias));

    Ok(DbSession::new(ctx))
}

#[pyfunction]
pub fn finalize_db(request_id: &str, alias: &str) -> PyResult<()> {
    let request_id = request_id.to_string();
    let alias = alias.to_string();
    get_db_runtime()
        .block_on(async move { finalize_request_context(&request_id, &alias).await })
        .map_err(|e| PyRuntimeError::new_err(e))
}

#[pyfunction]
pub fn finalize_db_all(request_id: &str) -> PyResult<()> {
    let request_id = request_id.to_string();
    get_db_runtime()
        .block_on(async move { finalize_all_request_contexts(&request_id).await })
        .map_err(|e| PyRuntimeError::new_err(e))
}
