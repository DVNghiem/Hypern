use pyo3::prelude::*;
use sqlx::{
    postgres::{PgConnectOptions, PgPoolOptions},
    ConnectOptions, Pool,
};
use std::collections::HashMap;
use std::time::Duration;
use tracing::log::LevelFilter;

#[derive(Debug, Clone, Default)]
#[pyclass(from_py_object)]
pub struct DatabaseConfig {
    pub url: String,
    pub max_connections: u32,
    pub min_connections: u32,
    pub idle_timeout: u64,
    pub options: Option<HashMap<String, String>>,
}

#[pymethods]
impl DatabaseConfig {
    #[new]
    fn new(
        url: &str,
        max_connections: u32,
        min_connections: u32,
        idle_timeout: u64,
        options: Option<HashMap<String, String>>,
    ) -> Self {
        DatabaseConfig {
            url: url.to_string(),
            max_connections,
            min_connections,
            idle_timeout,
            options,
        }
    }
}

impl DatabaseConfig {
    pub async fn create_postgres_pool(&self) -> Result<Pool<sqlx::Postgres>, sqlx::Error> {
        let mut connect_options = self.url.parse::<PgConnectOptions>()?;
        connect_options = connect_options.log_statements(LevelFilter::Debug);
        PgPoolOptions::new()
            .max_connections(self.max_connections)
            .min_connections(self.min_connections)
            .idle_timeout(Some(Duration::from_secs(self.idle_timeout)))
            .acquire_timeout(Duration::from_secs(self.idle_timeout))
            .connect_with(connect_options)
            .await
    }

    pub async fn create_pool(&self) -> Result<Box<dyn DatabasePoolTrait>, sqlx::Error> {
        let pool = self.create_postgres_pool().await?;
        Ok(Box::new(pool))
    }

    pub fn default_postgres(url: &str) -> Self {
        DatabaseConfig {
            url: url.to_string(),
            max_connections: 10,
            min_connections: 1,
            idle_timeout: 600,
            options: None,
        }
    }
}

pub trait DatabasePoolTrait: Send + Sync {}
impl DatabasePoolTrait for Pool<sqlx::Postgres> {}
