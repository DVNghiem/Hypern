use pyo3::prelude::*;
use std::sync::OnceLock;

static REDIS_RT: OnceLock<tokio::runtime::Runtime> = OnceLock::new();

fn redis_runtime() -> &'static tokio::runtime::Runtime {
    REDIS_RT.get_or_init(|| {
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("failed to create Redis runtime")
    })
}

/// A Redis connection pool backed by `deadpool-redis`.
#[pyclass]
pub struct RedisPool {
    pool: deadpool_redis::Pool,
}

#[pymethods]
impl RedisPool {
    /// Create a new Redis pool.
    ///
    /// Args:
    ///     url: Redis connection URL (e.g. ``redis://127.0.0.1/``)
    ///     pool_size: Maximum number of connections (default: 16)
    #[new]
    #[pyo3(signature = (url, pool_size = 16))]
    pub fn new(url: &str, pool_size: usize) -> PyResult<Self> {
        let cfg = deadpool_redis::Config::from_url(url);
        let pool = cfg
            .builder()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?
            .max_size(pool_size)
            .build()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
        Ok(Self { pool })
    }

    /// GET a key. Returns ``None`` if the key does not exist.
    pub fn get(&self, key: &str) -> PyResult<Option<String>> {
        let pool = self.pool.clone();
        let key = key.to_owned();
        redis_runtime().block_on(async {
            let mut conn = pool
                .get()
                .await
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
            let val: Option<String> = redis::AsyncCommands::get(&mut conn, &key)
                .await
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
            Ok(val)
        })
    }

    /// SET a key with optional expiry in seconds.
    #[pyo3(signature = (key, value, ex = None))]
    pub fn set(&self, key: &str, value: &str, ex: Option<u64>) -> PyResult<()> {
        let pool = self.pool.clone();
        let key = key.to_owned();
        let value = value.to_owned();
        redis_runtime().block_on(async {
            let mut conn = pool
                .get()
                .await
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
            if let Some(seconds) = ex {
                redis::AsyncCommands::set_ex::<_, _, ()>(&mut conn, &key, &value, seconds)
                    .await
                    .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
            } else {
                redis::AsyncCommands::set::<_, _, ()>(&mut conn, &key, &value)
                    .await
                    .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
            }
            Ok(())
        })
    }

    /// DEL a key. Returns the number of keys removed.
    pub fn delete(&self, key: &str) -> PyResult<u64> {
        let pool = self.pool.clone();
        let key = key.to_owned();
        redis_runtime().block_on(async {
            let mut conn = pool
                .get()
                .await
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
            let n: u64 = redis::AsyncCommands::del(&mut conn, &key)
                .await
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
            Ok(n)
        })
    }

    /// Set an expiry (in seconds) on an existing key.
    pub fn expire(&self, key: &str, seconds: u64) -> PyResult<bool> {
        let pool = self.pool.clone();
        let key = key.to_owned();
        redis_runtime().block_on(async {
            let mut conn = pool
                .get()
                .await
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
            let ok: bool = redis::AsyncCommands::expire(&mut conn, &key, seconds as i64)
                .await
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
            Ok(ok)
        })
    }

    /// INCR a key by 1. Returns the new value.
    pub fn incr(&self, key: &str) -> PyResult<i64> {
        let pool = self.pool.clone();
        let key = key.to_owned();
        redis_runtime().block_on(async {
            let mut conn = pool
                .get()
                .await
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
            let val: i64 = redis::AsyncCommands::incr(&mut conn, &key, 1i64)
                .await
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
            Ok(val)
        })
    }

    /// PUBLISH a message to a channel. Returns the number of subscribers that received it.
    pub fn publish(&self, channel: &str, message: &str) -> PyResult<u64> {
        let pool = self.pool.clone();
        let channel = channel.to_owned();
        let message = message.to_owned();
        redis_runtime().block_on(async {
            let mut conn = pool
                .get()
                .await
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
            let n: u64 = redis::AsyncCommands::publish(&mut conn, &channel, &message)
                .await
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
            Ok(n)
        })
    }

    /// Check if the Redis server is reachable.
    pub fn ping(&self) -> PyResult<bool> {
        let pool = self.pool.clone();
        redis_runtime().block_on(async {
            let mut conn = pool
                .get()
                .await
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
            let _: String = redis::cmd("PING")
                .query_async(&mut conn)
                .await
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
            Ok(true)
        })
    }

    fn __repr__(&self) -> String {
        format!(
            "RedisPool(max_size={})",
            self.pool.status().max_size
        )
    }
}
