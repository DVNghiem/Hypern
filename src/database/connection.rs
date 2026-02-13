use std::sync::Arc;

use super::{config::DatabaseConfig, transaction::DatabaseTransaction};
use sqlx::Postgres;
use sqlx::{Error as SqlxError, Pool};
use tokio::sync::Mutex;

#[derive(Clone)]
pub struct DatabaseConnection {
    connection: Arc<Pool<sqlx::Postgres>>,
}

impl DatabaseConnection {
    pub async fn new(config: DatabaseConfig) -> Self {
        let pool = config.create_postgres_pool().await.unwrap();
        Self {
            connection: Arc::new(pool),
        }
    }

    // get transaction
    pub async fn transaction(&self) -> DatabaseTransaction {
        let transaction = self
            .connection
            .begin()
            .await
            .map_err(|e| SqlxError::Configuration(e.to_string().into()));
        DatabaseTransaction::from_transaction(Arc::new(Mutex::new(Some(transaction.unwrap()))))
    }

    pub async fn begin_transaction(&self) -> Option<Box<dyn std::any::Any + Send>> {
        let transaction: sqlx::Transaction<Postgres> = self.connection.begin().await.ok()?;
        Some(Box::new(transaction))
    }
}
