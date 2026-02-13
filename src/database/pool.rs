use deadpool_postgres::{Config, ManagerConfig, Pool, RecyclingMethod, Runtime};
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use std::collections::HashMap;
use std::sync::{OnceLock, RwLock};
use std::time::Duration;
use tokio_postgres::NoTls;

static GLOBAL_POOLS: OnceLock<RwLock<HashMap<String, Pool>>> = OnceLock::new();

static DB_RUNTIME: OnceLock<tokio::runtime::Runtime> = OnceLock::new();

pub fn get_db_runtime() -> &'static tokio::runtime::Runtime {
    DB_RUNTIME.get_or_init(|| {
        tokio::runtime::Builder::new_multi_thread()
            .worker_threads(4)
            .enable_all()
            .build()
            .expect("Failed to create database runtime")
    })
}

fn get_pools() -> &'static RwLock<HashMap<String, Pool>> {
    GLOBAL_POOLS.get_or_init(|| RwLock::new(HashMap::new()))
}

#[derive(Debug, Clone)]
#[pyclass]
pub struct PoolConfig {
    #[pyo3(get, set)]
    pub url: String,
    #[pyo3(get, set)]
    pub max_size: usize,
    #[pyo3(get, set)]
    pub min_idle: Option<usize>,
    #[pyo3(get, set)]
    pub connect_timeout_secs: u64,
    #[pyo3(get, set)]
    pub idle_timeout_secs: Option<u64>,
    #[pyo3(get, set)]
    pub max_lifetime_secs: Option<u64>,
    #[pyo3(get, set)]
    pub test_before_acquire: bool,
    #[pyo3(get, set)]
    pub keepalive_secs: Option<u64>,
}

impl Default for PoolConfig {
    fn default() -> Self {
        Self {
            url: String::new(),
            max_size: 16,
            min_idle: Some(2),
            connect_timeout_secs: 30,
            idle_timeout_secs: Some(600),
            max_lifetime_secs: Some(1800),
            test_before_acquire: false,
            keepalive_secs: None,
        }
    }
}

#[pymethods]
impl PoolConfig {
    #[new]
    #[pyo3(signature = (url, max_size=16, min_idle=None, connect_timeout_secs=30, idle_timeout_secs=None, max_lifetime_secs=None, test_before_acquire=false, keepalive_secs=None))]
    pub fn new(
        url: String,
        max_size: usize,
        min_idle: Option<usize>,
        connect_timeout_secs: u64,
        idle_timeout_secs: Option<u64>,
        max_lifetime_secs: Option<u64>,
        test_before_acquire: bool,
        keepalive_secs: Option<u64>,
    ) -> Self {
        Self {
            url,
            max_size,
            min_idle,
            connect_timeout_secs,
            idle_timeout_secs,
            max_lifetime_secs,
            test_before_acquire,
            keepalive_secs,
        }
    }
}

pub struct ConnectionPoolManager;

impl ConnectionPoolManager {
    fn parse_url(url: &str) -> Result<Config, String> {
        // URL format: postgresql://user:password@host:port/database
        let url = url
            .strip_prefix("postgresql://")
            .or_else(|| url.strip_prefix("postgres://"))
            .ok_or_else(|| "Invalid PostgreSQL URL format".to_string())?;

        // Split user:password@host:port/database
        let (auth, rest) = url
            .split_once('@')
            .ok_or_else(|| "Missing @ in URL".to_string())?;

        let (user, password) = auth
            .split_once(':')
            .map(|(u, p)| (u.to_string(), Some(p.to_string())))
            .unwrap_or_else(|| (auth.to_string(), None));

        let (host_port, dbname) = rest
            .split_once('/')
            .ok_or_else(|| "Missing database name in URL".to_string())?;

        // Handle query parameters
        let dbname = dbname.split('?').next().unwrap_or(dbname);

        let (host, port) = if let Some((h, p)) = host_port.split_once(':') {
            (h.to_string(), p.parse::<u16>().ok())
        } else {
            (host_port.to_string(), Some(5432))
        };

        let mut cfg = Config::new();
        cfg.user = Some(user);
        cfg.password = password;
        cfg.host = Some(host);
        cfg.port = port;
        cfg.dbname = Some(dbname.to_string());
        cfg.manager = Some(ManagerConfig {
            recycling_method: RecyclingMethod::Fast,
        });

        Ok(cfg)
    }

    pub fn initialize_sync_with_alias(config: &PoolConfig, alias: &str) -> Result<(), String> {
        let pools = get_pools();
        let pools_read = pools.read().unwrap();

        if pools_read.contains_key(alias) {
            return Err(format!(
                "Connection pool for alias '{}' already initialized",
                alias
            ));
        }
        drop(pools_read);

        let mut cfg = Self::parse_url(&config.url)?;

        // Set recycling method based on test_before_acquire
        cfg.manager = Some(ManagerConfig {
            recycling_method: if config.test_before_acquire {
                RecyclingMethod::Verified
            } else {
                RecyclingMethod::Fast
            },
        });

        cfg.pool = Some(deadpool_postgres::PoolConfig {
            max_size: config.max_size,
            timeouts: deadpool_postgres::Timeouts {
                wait: Some(Duration::from_secs(config.connect_timeout_secs)),
                create: Some(Duration::from_secs(config.connect_timeout_secs)),
                recycle: Some(Duration::from_secs(5)),
            },
            ..Default::default()
        });

        // Apply keepalive if configured
        if let Some(keepalive_secs) = config.keepalive_secs {
            cfg.keepalives = Some(true);
            cfg.keepalives_idle = Some(Duration::from_secs(keepalive_secs));
        }

        // Create the pool within the db runtime context
        let pool = get_db_runtime()
            .block_on(async { cfg.create_pool(Some(Runtime::Tokio1), NoTls) })
            .map_err(|e| format!("Failed to create pool: {}", e))?;

        let mut pools_write = pools.write().unwrap();
        pools_write.insert(alias.to_string(), pool);

        Ok(())
    }

    // Legacy method for backward compatibility
    pub fn initialize_sync(config: &PoolConfig) -> Result<(), String> {
        Self::initialize_sync_with_alias(config, "default")
    }

    pub fn get_pool_by_alias(alias: &str) -> Option<Pool> {
        let pools = get_pools();
        let pools_read = pools.read().unwrap();
        pools_read.get(alias).cloned()
    }

    // Legacy method for backward compatibility
    pub fn get_pool() -> Option<Pool> {
        Self::get_pool_by_alias("default")
    }

    pub fn pool_status_by_alias(alias: &str) -> Option<PoolStatus> {
        Self::get_pool_by_alias(alias).map(|pool| {
            let status = pool.status();
            PoolStatus {
                size: status.size,
                available: status.available,
                max_size: status.max_size,
            }
        })
    }

    // Legacy method for backward compatibility
    pub fn pool_status() -> Option<PoolStatus> {
        Self::pool_status_by_alias("default")
    }

    pub fn close_alias(alias: &str) {
        let pools = get_pools();
        let mut pools_write = pools.write().unwrap();
        if let Some(pool) = pools_write.remove(alias) {
            pool.close();
        }
    }

    pub fn close_all() {
        let pools = get_pools();
        let mut pools_write = pools.write().unwrap();
        for (_, pool) in pools_write.drain() {
            pool.close();
        }
    }

    // Legacy method for backward compatibility
    pub fn close() {
        Self::close_alias("default");
    }
}

#[derive(Debug, Clone)]
#[pyclass]
pub struct PoolStatus {
    #[pyo3(get)]
    pub size: usize,
    #[pyo3(get)]
    pub available: usize,
    #[pyo3(get)]
    pub max_size: usize,
}

#[pymethods]
impl PoolStatus {
    fn __repr__(&self) -> String {
        format!(
            "PoolStatus(size={}, available={}, max_size={})",
            self.size, self.available, self.max_size
        )
    }
}

#[pyclass]
pub struct ConnectionPool;

#[pymethods]
impl ConnectionPool {
    #[new]
    fn new() -> Self {
        Self
    }

    #[staticmethod]
    fn initialize_with_alias(config: &PoolConfig, alias: &str) -> PyResult<()> {
        ConnectionPoolManager::initialize_sync_with_alias(config, alias)
            .map_err(|e| PyRuntimeError::new_err(e))
    }

    // Legacy method for backward compatibility
    #[staticmethod]
    fn initialize(config: &PoolConfig) -> PyResult<()> {
        ConnectionPoolManager::initialize_sync(config).map_err(|e| PyRuntimeError::new_err(e))
    }

    #[staticmethod]
    fn status_for_alias(alias: &str) -> PyResult<Option<PoolStatus>> {
        Ok(ConnectionPoolManager::pool_status_by_alias(alias))
    }

    // Legacy method for backward compatibility
    #[staticmethod]
    fn status() -> PyResult<Option<PoolStatus>> {
        Ok(ConnectionPoolManager::pool_status())
    }

    #[staticmethod]
    fn is_initialized_with_alias(alias: &str) -> bool {
        ConnectionPoolManager::get_pool_by_alias(alias).is_some()
    }

    // Legacy method for backward compatibility
    #[staticmethod]
    fn is_initialized() -> bool {
        ConnectionPoolManager::get_pool().is_some()
    }

    #[staticmethod]
    fn close_alias(alias: &str) -> PyResult<()> {
        ConnectionPoolManager::close_alias(alias);
        Ok(())
    }

    #[staticmethod]
    fn close_all() -> PyResult<()> {
        ConnectionPoolManager::close_all();
        Ok(())
    }

    // Legacy method for backward compatibility
    #[staticmethod]
    fn close() -> PyResult<()> {
        ConnectionPoolManager::close();
        Ok(())
    }
}
