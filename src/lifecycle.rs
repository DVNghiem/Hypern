use pyo3::prelude::*;
use std::sync::{Arc, Mutex};
use std::collections::HashMap;
use tokio::sync::Notify;

/// Application lifecycle state
#[derive(Debug, Clone, PartialEq)]
pub enum AppState {
    Created,
    Starting,
    Running,
    Stopping,
    Stopped,
    Error,
}

/// Lifecycle hook types
#[derive(Debug, Clone, Hash, PartialEq, Eq)]
pub enum LifecycleHook {
    BeforeStart,
    AfterStart,
    BeforeStop,
    AfterStop,
    OnError,
}

/// Application lifecycle manager
#[pyclass]
pub struct LifecycleManager {
    state: Arc<Mutex<AppState>>,
    hooks: Arc<Mutex<HashMap<LifecycleHook, Vec<PyObject>>>>,
    shutdown_notify: Arc<Notify>,
    error_count: Arc<Mutex<u32>>,
}

#[pymethods]
impl LifecycleManager {
    #[new]
    pub fn new() -> Self {
        Self {
            state: Arc::new(Mutex::new(AppState::Created)),
            hooks: Arc::new(Mutex::new(HashMap::new())),
            shutdown_notify: Arc::new(Notify::new()),
            error_count: Arc::new(Mutex::new(0)),
        }
    }

    /// Get current application state
    #[getter]
    pub fn state(&self) -> String {
        let state = self.state.lock().unwrap();
        match *state {
            AppState::Created => "created".to_string(),
            AppState::Starting => "starting".to_string(),
            AppState::Running => "running".to_string(),
            AppState::Stopping => "stopping".to_string(),
            AppState::Stopped => "stopped".to_string(),
            AppState::Error => "error".to_string(),
        }
    }

    /// Register a lifecycle hook
    pub fn on(&mut self, event: &str, callback: PyObject) -> PyResult<()> {
        let hook = match event.to_lowercase().as_str() {
            "before_start" | "beforestart" => LifecycleHook::BeforeStart,
            "after_start" | "afterstart" => LifecycleHook::AfterStart,
            "before_stop" | "beforestop" => LifecycleHook::BeforeStop,
            "after_stop" | "afterstop" => LifecycleHook::AfterStop,
            "on_error" | "onerror" | "error" => LifecycleHook::OnError,
            _ => {
                return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
                    format!("Unknown lifecycle event: {}", event)
                ));
            }
        };

        let mut hooks = self.hooks.lock().unwrap();
        hooks.entry(hook).or_insert_with(Vec::new).push(callback);
        Ok(())
    }

    /// Remove all hooks for a specific event
    pub fn off(&mut self, event: &str) -> PyResult<()> {
        let hook = match event.to_lowercase().as_str() {
            "before_start" | "beforestart" => LifecycleHook::BeforeStart,
            "after_start" | "afterstart" => LifecycleHook::AfterStart,
            "before_stop" | "beforestop" => LifecycleHook::BeforeStop,
            "after_stop" | "afterstop" => LifecycleHook::AfterStop,
            "on_error" | "onerror" | "error" => LifecycleHook::OnError,
            _ => {
                return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
                    format!("Unknown lifecycle event: {}", event)
                ));
            }
        };

        let mut hooks = self.hooks.lock().unwrap();
        hooks.remove(&hook);
        Ok(())
    }

    /// Start the application
    pub fn start(&self) -> PyResult<()> {
        {
            let mut state = self.state.lock().unwrap();
            if *state != AppState::Created && *state != AppState::Stopped {
                return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                    format!("Cannot start application in state: {:?}", *state)
                ));
            }
            *state = AppState::Starting;
        }

        // Execute before_start hooks
        if let Err(e) = self.execute_hooks(&LifecycleHook::BeforeStart) {
            self.set_error_state();
            return Err(e);
        }

        // Set running state
        {
            let mut state = self.state.lock().unwrap();
            *state = AppState::Running;
        }

        // Execute after_start hooks
        if let Err(e) = self.execute_hooks(&LifecycleHook::AfterStart) {
            self.set_error_state();
            return Err(e);
        }

        Ok(())
    }

    /// Stop the application
    pub fn stop(&self) -> PyResult<()> {
        {
            let mut state = self.state.lock().unwrap();
            if *state != AppState::Running {
                return Err(PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                    format!("Cannot stop application in state: {:?}", *state)
                ));
            }
            *state = AppState::Stopping;
        }

        // Execute before_stop hooks
        if let Err(e) = self.execute_hooks(&LifecycleHook::BeforeStop) {
            self.set_error_state();
            return Err(e);
        }

        // Notify shutdown
        self.shutdown_notify.notify_waiters();

        // Set stopped state
        {
            let mut state = self.state.lock().unwrap();
            *state = AppState::Stopped;
        }

        // Execute after_stop hooks
        if let Err(e) = self.execute_hooks(&LifecycleHook::AfterStop) {
            self.set_error_state();
            return Err(e);
        }

        Ok(())
    }

    /// Graceful shutdown with timeout
    pub fn shutdown(&self, timeout_seconds: Option<f32>) -> PyResult<()> {
        let timeout = timeout_seconds.unwrap_or(30.0);
        
        // Start shutdown process
        self.stop()?;
        
        // Wait for shutdown to complete (simulated for now)
        std::thread::sleep(std::time::Duration::from_secs_f32(timeout.min(5.0)));
        
        Ok(())
    }

    /// Check if application is running
    pub fn is_running(&self) -> bool {
        let state = self.state.lock().unwrap();
        *state == AppState::Running
    }

    /// Check if application is stopped
    pub fn is_stopped(&self) -> bool {
        let state = self.state.lock().unwrap();
        *state == AppState::Stopped
    }

    /// Check if application has errors
    pub fn has_errors(&self) -> bool {
        let state = self.state.lock().unwrap();
        *state == AppState::Error
    }

    /// Get error count
    #[getter]
    pub fn error_count(&self) -> u32 {
        *self.error_count.lock().unwrap()
    }

    /// Report an error to the lifecycle manager
    pub fn report_error(&self, error: PyObject) -> PyResult<()> {
        {
            let mut count = self.error_count.lock().unwrap();
            *count += 1;
        }

        // Execute error hooks
        if let Err(e) = self.execute_error_hooks(error) {
            eprintln!("Error in error handler: {:?}", e);
        }

        Ok(())
    }

    /// Reset error count
    pub fn reset_errors(&self) -> PyResult<()> {
        let mut count = self.error_count.lock().unwrap();
        *count = 0;
        Ok(())
    }

    /// Get all registered hooks for debugging
    pub fn get_hooks(&self) -> PyResult<HashMap<String, usize>> {
        let hooks = self.hooks.lock().unwrap();
        let mut result = HashMap::new();
        
        for (hook_type, hook_list) in hooks.iter() {
            let key = match hook_type {
                LifecycleHook::BeforeStart => "before_start",
                LifecycleHook::AfterStart => "after_start",
                LifecycleHook::BeforeStop => "before_stop",
                LifecycleHook::AfterStop => "after_stop",
                LifecycleHook::OnError => "on_error",
            };
            result.insert(key.to_string(), hook_list.len());
        }
        
        Ok(result)
    }

    fn __str__(&self) -> String {
        format!("LifecycleManager(state='{}', errors={})", 
                self.state(), self.error_count())
    }

    fn __repr__(&self) -> String {
        let hooks = self.hooks.lock().unwrap();
        format!("LifecycleManager(state='{}', hooks={}, errors={})", 
                self.state(), hooks.len(), self.error_count())
    }
}

impl LifecycleManager {
    /// Execute hooks for a specific lifecycle event
    fn execute_hooks(&self, hook_type: &LifecycleHook) -> PyResult<()> {
        let hooks = self.hooks.lock().unwrap();
        if let Some(hook_list) = hooks.get(hook_type) {
            for hook in hook_list {
                Python::with_gil(|py| {
                    if let Err(e) = hook.call0(py) {
                        eprintln!("Error executing {:?} hook: {:?}", hook_type, e);
                        return Err(e);
                    }
                    Ok(())
                })?;
            }
        }
        Ok(())
    }

    /// Execute error hooks with the error object
    fn execute_error_hooks(&self, error: PyObject) -> PyResult<()> {
        let hooks = self.hooks.lock().unwrap();
        if let Some(hook_list) = hooks.get(&LifecycleHook::OnError) {
            for hook in hook_list {
                Python::with_gil(|py| {
                    if let Err(e) = hook.call1(py, (error.clone_ref(py),)) {
                        eprintln!("Error executing error hook: {:?}", e);
                        return Err(e);
                    }
                    Ok(())
                })?;
            }
        }
        Ok(())
    }

    /// Set application to error state
    fn set_error_state(&self) {
        let mut state = self.state.lock().unwrap();
        *state = AppState::Error;
    }

    /// Get shutdown notifier for internal use
    pub fn get_shutdown_notify(&self) -> Arc<Notify> {
        self.shutdown_notify.clone()
    }
}

impl Default for LifecycleManager {
    fn default() -> Self {
        Self::new()
    }
}

/// Configuration for the application
#[pyclass]
pub struct AppConfig {
    #[pyo3(get, set)]
    pub host: String,
    
    #[pyo3(get, set)]
    pub port: u16,
    
    #[pyo3(get, set)]
    pub workers: usize,
    
    #[pyo3(get, set)]
    pub max_blocking_threads: usize,
    
    #[pyo3(get, set)]
    pub enable_http2: bool,
    
    #[pyo3(get, set)]
    pub keep_alive_timeout: u64,
    
    #[pyo3(get, set)]
    pub request_timeout: u64,
    
    #[pyo3(get, set)]
    pub max_request_size: usize,
    
    /// Custom configuration as key-value pairs
    custom: HashMap<String, PyObject>,
}

impl Clone for AppConfig {
    fn clone(&self) -> Self {
        Python::with_gil(|py| {
            let mut custom_clone = HashMap::new();
            for (key, value) in &self.custom {
                custom_clone.insert(key.clone(), value.clone_ref(py));
            }
            
            Self {
                host: self.host.clone(),
                port: self.port,
                workers: self.workers,
                max_blocking_threads: self.max_blocking_threads,
                enable_http2: self.enable_http2,
                keep_alive_timeout: self.keep_alive_timeout,
                request_timeout: self.request_timeout,
                max_request_size: self.max_request_size,
                custom: custom_clone,
            }
        })
    }
}

#[pymethods]
impl AppConfig {
    #[new]
    #[pyo3(signature = (host = "127.0.0.1".to_string(), port = 8000, workers = 0, max_blocking_threads = 512))]
    pub fn new(host: String, port: u16, workers: usize, max_blocking_threads: usize) -> Self {
        let workers = if workers == 0 { 
            std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4)
        } else { 
            workers 
        };

        Self {
            host,
            port,
            workers,
            max_blocking_threads,
            enable_http2: false,
            keep_alive_timeout: 60,
            request_timeout: 30,
            max_request_size: 1024 * 1024 * 16, // 16MB
            custom: HashMap::new(),
        }
    }

    /// Set custom configuration value
    pub fn set(&mut self, key: String, value: PyObject) -> PyResult<()> {
        self.custom.insert(key, value);
        Ok(())
    }

    /// Get custom configuration value
    pub fn get(&self, key: &str) -> Option<PyObject> {
        self.custom.get(key).map(|v| Python::with_gil(|py| v.clone_ref(py)))
    }

    /// Get all custom configuration keys
    pub fn keys(&self) -> Vec<String> {
        self.custom.keys().cloned().collect()
    }

    /// Load configuration from dictionary
    pub fn from_dict(&mut self, config: HashMap<String, PyObject>) -> PyResult<()> {
        Python::with_gil(|py| {
            for (key, value) in config {
                match key.as_str() {
                    "host" => {
                        if let Ok(host) = value.extract::<String>(py) {
                            self.host = host;
                        }
                    }
                    "port" => {
                        if let Ok(port) = value.extract::<u16>(py) {
                            self.port = port;
                        }
                    }
                    "workers" => {
                        if let Ok(workers) = value.extract::<usize>(py) {
                            self.workers = workers;
                        }
                    }
                    "max_blocking_threads" => {
                        if let Ok(threads) = value.extract::<usize>(py) {
                            self.max_blocking_threads = threads;
                        }
                    }
                    "enable_http2" => {
                        if let Ok(http2) = value.extract::<bool>(py) {
                            self.enable_http2 = http2;
                        }
                    }
                    _ => {
                        self.custom.insert(key, value);
                    }
                }
            }
            Ok(())
        })
    }

    fn __str__(&self) -> String {
        format!("AppConfig(host='{}', port={}, workers={}, http2={})", 
                self.host, self.port, self.workers, self.enable_http2)
    }
}

impl Default for AppConfig {
    fn default() -> Self {
        Self::new("127.0.0.1".to_string(), 8000, 0, 512)
    }
}