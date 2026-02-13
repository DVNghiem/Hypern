use pyo3::prelude::*;
use std::sync::Arc;
use tokio::sync::Mutex;

use crate::database::operation::{DatabaseOperations, RowStream};

#[pyclass]
#[derive(Clone, Debug)]
pub struct DatabaseTransaction {
    transaction: Arc<Mutex<Option<sqlx::Transaction<'static, sqlx::Postgres>>>>,
    operations: DatabaseOperations,
}

impl DatabaseTransaction {
    pub fn from_transaction(
        transaction: Arc<Mutex<Option<sqlx::Transaction<'static, sqlx::Postgres>>>>,
    ) -> Self {
        Self {
            transaction,
            operations: DatabaseOperations {},
        }
    }
}

#[pymethods]
impl DatabaseTransaction {
    fn execute(&self, py: Python<'_>, query: &str, params: Vec<Py<PyAny>>) -> PyResult<u64> {
        let transaction = self.transaction.clone();
        let operations = self.operations.clone();
        let result = futures::executor::block_on(async move {
            operations.execute(py, transaction, query, params).await
        })?;
        Ok(result)
    }

    fn fetch_all(
        &self,
        py: Python<'_>,
        query: &str,
        params: Vec<Py<PyAny>>,
    ) -> Result<Vec<Py<PyAny>>, PyErr> {
        let transaction = self.transaction.clone();
        let operations = self.operations.clone();
        let result = futures::executor::block_on(async move {
            operations.fetch_all(py, transaction, query, params).await
        })?;
        Ok(result)
    }

    /// Stream data in chunks. Returns a RowStream iterator that yields chunks lazily.
    fn stream_data(
        &self,
        py: Python<'_>,
        query: &str,
        params: Vec<Py<PyAny>>,
        chunk_size: usize,
    ) -> PyResult<RowStream> {
        let transaction = self.transaction.clone();
        let operations = self.operations.clone();
        let result = futures::executor::block_on(async move {
            operations.stream_data(py, transaction, query, params, chunk_size).await
        })?;
        Ok(result)
    }

    fn bulk_change(
        &self,
        py: Python<'_>,
        query: &str,
        params: Vec<Vec<Py<PyAny>>>,
        batch_size: usize,
    ) -> PyResult<u64> {
        let transaction = self.transaction.clone();
        let operations = self.operations.clone();
        let result = futures::executor::block_on(async move {
            operations.bulk_change(py, transaction, query, params, batch_size).await
        })?;
        Ok(result)
    }

    fn commit(&mut self) -> PyResult<()> {
        let transaction = self.transaction.clone();
        let _ = futures::executor::block_on(async move {
            let mut guard = transaction.lock().await;
            let transaction = guard.take().unwrap();
            transaction.commit().await.ok();
        });
        Ok(())
    }

    fn rollback(&mut self) -> PyResult<()> {
        let transaction = self.transaction.clone();
        let _ = futures::executor::block_on(async move {
            let mut guard = transaction.lock().await;
            let transaction = guard.take().unwrap();
            transaction.rollback().await.ok();
        });
        Ok(())
    }
}
