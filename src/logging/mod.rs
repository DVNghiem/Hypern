use crossbeam_channel::{bounded, Sender, Receiver};
use parking_lot::RwLock;
use pyo3::prelude::*;
use std::fmt;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

// ---------------------------------------------------------------------------
// Log Level
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum LogLevel {
    Trace = 0,
    Debug = 1,
    Info = 2,
    Warn = 3,
    Error = 4,
    Off = 5,
}

impl LogLevel {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Trace => "TRACE",
            Self::Debug => "DEBUG",
            Self::Info => "INFO",
            Self::Warn => "WARN",
            Self::Error => "ERROR",
            Self::Off => "OFF",
        }
    }

    pub fn from_str(s: &str) -> Self {
        match s.to_lowercase().as_str() {
            "trace" => Self::Trace,
            "debug" => Self::Debug,
            "info" => Self::Info,
            "warn" | "warning" => Self::Warn,
            "error" => Self::Error,
            "off" | "none" | "disabled" => Self::Off,
            _ => Self::Info,
        }
    }

    fn color_code(&self) -> &'static str {
        match self {
            Self::Trace => "\x1b[90m",   // gray
            Self::Debug => "\x1b[36m",   // cyan
            Self::Info => "\x1b[32m",    // green
            Self::Warn => "\x1b[33m",    // yellow
            Self::Error => "\x1b[31m",   // red
            Self::Off => "",
        }
    }
}

impl fmt::Display for LogLevel {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

// ---------------------------------------------------------------------------
// Log Entry
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct LogEntry {
    pub timestamp: f64,
    pub level: LogLevel,
    pub message: String,
    pub target: Option<String>,
    /// For request/response logs
    pub request_id: Option<String>,
    pub method: Option<String>,
    pub path: Option<String>,
    pub status: Option<u16>,
    pub duration_ms: Option<f64>,
    pub worker_id: Option<usize>,
}

impl LogEntry {
    pub fn new(level: LogLevel, message: impl Into<String>) -> Self {
        Self {
            timestamp: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs_f64(),
            level,
            message: message.into(),
            target: None,
            request_id: None,
            method: None,
            path: None,
            status: None,
            duration_ms: None,
            worker_id: None,
        }
    }

    pub fn with_target(mut self, target: impl Into<String>) -> Self {
        self.target = Some(target.into());
        self
    }

    pub fn with_worker(mut self, worker_id: usize) -> Self {
        self.worker_id = Some(worker_id);
        self
    }

    pub fn request(
        method: &str,
        path: &str,
        request_id: Option<&str>,
    ) -> Self {
        Self {
            timestamp: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs_f64(),
            level: LogLevel::Info,
            message: String::new(),
            target: Some("request".into()),
            request_id: request_id.map(|s| s.to_string()),
            method: Some(method.to_string()),
            path: Some(path.to_string()),
            status: None,
            duration_ms: None,
            worker_id: None,
        }
    }

    pub fn response(
        method: &str,
        path: &str,
        status: u16,
        duration_ms: f64,
        request_id: Option<&str>,
    ) -> Self {
        Self {
            timestamp: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs_f64(),
            level: LogLevel::Info,
            message: String::new(),
            target: Some("response".into()),
            request_id: request_id.map(|s| s.to_string()),
            method: Some(method.to_string()),
            path: Some(path.to_string()),
            status: Some(status),
            duration_ms: Some(duration_ms),
            worker_id: None,
        }
    }

    /// Format the log entry as a colored string for terminal output.
    fn format_colored(&self) -> String {
        let reset = "\x1b[0m";
        let dim = "\x1b[2m";
        let color = self.level.color_code();

        let ts = format_timestamp(self.timestamp);

        // Request log
        if self.target.as_deref() == Some("request") {
            let method = self.method.as_deref().unwrap_or("?");
            let path = self.path.as_deref().unwrap_or("?");
            let rid = self.request_id.as_deref().unwrap_or("-");
            return format!(
                "{dim}{ts}{reset} {color}{:<5}{reset} \x1b[35m-->{reset} {method} {path} {dim}[{rid}]{reset}",
                self.level.as_str(),
            );
        }

        // Response log
        if self.target.as_deref() == Some("response") {
            let method = self.method.as_deref().unwrap_or("?");
            let path = self.path.as_deref().unwrap_or("?");
            let status = self.status.unwrap_or(0);
            let dur = self.duration_ms.unwrap_or(0.0);
            let rid = self.request_id.as_deref().unwrap_or("-");
            let status_color = match status {
                200..=299 => "\x1b[32m",  // green
                300..=399 => "\x1b[36m",  // cyan
                400..=499 => "\x1b[33m",  // yellow
                500..=599 => "\x1b[31m",  // red
                _ => "\x1b[37m",          // white
            };
            return format!(
                "{dim}{ts}{reset} {color}{:<5}{reset} \x1b[35m<--{reset} {method} {path} {status_color}{status}{reset} {dim}{dur:.2}ms{reset} {dim}[{rid}]{reset}",
                self.level.as_str(),
            );
        }

        // General log
        let worker = self
            .worker_id
            .map(|w| format!(" {dim}[worker-{w}]{reset}"))
            .unwrap_or_default();
        let target = self
            .target
            .as_deref()
            .map(|t| format!(" {dim}{t}{reset}"))
            .unwrap_or_default();

        format!(
            "{dim}{ts}{reset} {color}{:<5}{reset}{target}{worker} {}",
            self.level.as_str(),
            self.message,
        )
    }
}

fn format_timestamp(ts: f64) -> String {
    use chrono::{DateTime, TimeZone, Utc};
    let secs = ts as i64;
    let micros = ((ts - secs as f64) * 1_000_000.0) as u32;
    let dt: DateTime<Utc> = Utc.timestamp_opt(secs, micros * 1_000).single()
        .unwrap_or_else(Utc::now);
    // e.g. 2026-02-27T02:17:25.113520+00:00
    dt.format("%Y-%m-%dT%H:%M:%S%.6f+00:00").to_string()
}

// ---------------------------------------------------------------------------
// Log Config
// ---------------------------------------------------------------------------

/// Configuration for the logging system.
#[derive(Debug, Clone)]
pub struct LogConfig {
    /// Minimum log level to output.
    pub level: LogLevel,
    /// Enable request logging (incoming request).
    pub log_request: bool,
    /// Enable response logging (outgoing response with status and duration).
    pub log_response: bool,
    /// Queue capacity.
    pub queue_size: usize,
    /// Paths to skip logging for (e.g., health check endpoints).
    pub skip_paths: Vec<String>,
}

impl Default for LogConfig {
    fn default() -> Self {
        Self {
            level: LogLevel::Info,
            log_request: true,
            log_response: true,
            queue_size: 10_000,
            skip_paths: vec![
                "/_health".to_string(),
                "/_health/live".to_string(),
                "/_health/ready".to_string(),
                "/_health/startup".to_string(),
                "/favicon.ico".to_string(),
            ],
        }
    }
}

impl LogConfig {
    pub fn should_skip_path(&self, path: &str) -> bool {
        self.skip_paths.iter().any(|p| path.starts_with(p))
    }
}

// ---------------------------------------------------------------------------
// Log Queue (global singleton, fork-safe via re-initializable RwLock)
// ---------------------------------------------------------------------------

static LOG_QUEUE: RwLock<Option<LogQueueInner>> = RwLock::new(None);

struct LogQueueInner {
    sender: Sender<LogEntry>,
    config: Arc<RwLock<LogConfig>>,
    running: Arc<AtomicBool>,
}

pub struct LogQueue;

impl LogQueue {
    /// Initialize (or re-initialize) the global log queue.
    /// Safe to call multiple times (e.g. in child processes after fork).
    pub fn init(config: LogConfig) {
        // Shut down any previous instance (important after fork)
        Self::shutdown();

        let queue_size = config.queue_size;
        let (sender, receiver) = bounded::<LogEntry>(queue_size);
        let running = Arc::new(AtomicBool::new(true));
        let cfg = Arc::new(RwLock::new(config));

        let inner = LogQueueInner {
            sender,
            config: cfg.clone(),
            running: running.clone(),
        };

        // Store globally before spawning consumer
        *LOG_QUEUE.write() = Some(inner);

        // Spawn the consumer thread
        std::thread::Builder::new()
            .name("hypern-logger".into())
            .spawn(move || {
                log_consumer(receiver, cfg, running);
            })
            .expect("Failed to spawn logger thread");
    }

    /// Update log config at runtime.
    pub fn update_config(config: LogConfig) {
        let guard = LOG_QUEUE.read();
        if let Some(ref inner) = *guard {
            *inner.config.write() = config;
        }
    }

    /// Shut down the log queue, flushing remaining entries.
    pub fn shutdown() {
        let guard = LOG_QUEUE.read();
        if let Some(ref inner) = *guard {
            inner.running.store(false, Ordering::SeqCst);
        }
        drop(guard);
        // Drop the old sender so the consumer thread exits
        *LOG_QUEUE.write() = None;
    }

    /// Get a copy of the current log config.
    pub fn config() -> Option<LogConfig> {
        let guard = LOG_QUEUE.read();
        guard.as_ref().map(|inner| inner.config.read().clone())
    }

    /// Re-initialize the log queue after fork().
    /// Reads the existing config from the (now-dead) parent copy and creates
    /// a fresh channel + consumer thread in the child process.
    pub fn reinit_after_fork() {
        let config = {
            let guard = LOG_QUEUE.read();
            guard.as_ref().map(|inner| inner.config.read().clone())
        };
        if let Some(cfg) = config {
            // Force-drop the old (dead) inner without signalling the old consumer
            // (it doesn't exist in this process after fork)
            *LOG_QUEUE.write() = None;
            Self::init(cfg);
        }
    }
}

/// Send a log entry to the queue (non-blocking, drops if full).
#[inline]
pub fn log_entry(entry: LogEntry) {
    let guard = LOG_QUEUE.read();
    if let Some(ref inner) = *guard {
        let cfg = inner.config.read();
        if entry.level < cfg.level {
            return;
        }
        drop(cfg);
        // Don't block if queue is full – drop the message
        let _ = inner.sender.try_send(entry);
    }
}

/// Convenience: log a message at the given level.
#[inline]
pub fn log(level: LogLevel, message: impl Into<String>) {
    log_entry(LogEntry::new(level, message));
}

/// Convenience: log a request.
#[inline]
pub fn log_request(method: &str, path: &str, request_id: Option<&str>) {
    {
        let guard = LOG_QUEUE.read();
        if let Some(ref inner) = *guard {
            let cfg = inner.config.read();
            if !cfg.log_request || cfg.should_skip_path(path) {
                return;
            }
        } else {
            return;
        }
    }
    log_entry(LogEntry::request(method, path, request_id));
}

/// Convenience: log a response.
#[inline]
pub fn log_response(
    method: &str,
    path: &str,
    status: u16,
    duration_ms: f64,
    request_id: Option<&str>,
) {
    {
        let guard = LOG_QUEUE.read();
        if let Some(ref inner) = *guard {
            let cfg = inner.config.read();
            if !cfg.log_response || cfg.should_skip_path(path) {
                return;
            }
        } else {
            return;
        }
    }
    log_entry(LogEntry::response(method, path, status, duration_ms, request_id));
}

/// Consumer thread: drains the queue and writes to stderr.
fn log_consumer(
    receiver: Receiver<LogEntry>,
    config: Arc<RwLock<LogConfig>>,
    running: Arc<AtomicBool>,
) {
    use std::io::Write;

    let stderr = std::io::stderr();

    while running.load(Ordering::SeqCst) {
        match receiver.recv_timeout(std::time::Duration::from_millis(100)) {
            Ok(entry) => {
                let cfg = config.read();
                if entry.level >= cfg.level {
                    let line = entry.format_colored();
                    let mut handle = stderr.lock();
                    let _ = writeln!(handle, "{}", line);
                }
            }
            Err(crossbeam_channel::RecvTimeoutError::Timeout) => continue,
            Err(crossbeam_channel::RecvTimeoutError::Disconnected) => break,
        }
    }

    // Flush remaining entries
    for entry in receiver.try_iter() {
        let cfg = config.read();
        if entry.level >= cfg.level {
            let line = entry.format_colored();
            eprintln!("{}", line);
        }
    }
}

// ---------------------------------------------------------------------------
// Convenience macros (internal use)
// ---------------------------------------------------------------------------

/// Log at trace level.
#[macro_export]
macro_rules! hlog_trace {
    ($($arg:tt)*) => {
        $crate::logging::log($crate::logging::LogLevel::Trace, format!($($arg)*))
    };
}

/// Log at debug level.
#[macro_export]
macro_rules! hlog_debug {
    ($($arg:tt)*) => {
        $crate::logging::log($crate::logging::LogLevel::Debug, format!($($arg)*))
    };
}

/// Log at info level.
#[macro_export]
macro_rules! hlog_info {
    ($($arg:tt)*) => {
        $crate::logging::log($crate::logging::LogLevel::Info, format!($($arg)*))
    };
}

/// Log at warn level.
#[macro_export]
macro_rules! hlog_warn {
    ($($arg:tt)*) => {
        $crate::logging::log($crate::logging::LogLevel::Warn, format!($($arg)*))
    };
}

/// Log at error level.
#[macro_export]
macro_rules! hlog_error {
    ($($arg:tt)*) => {
        $crate::logging::log($crate::logging::LogLevel::Error, format!($($arg)*))
    };
}

// ---------------------------------------------------------------------------
// PyO3 Bindings
// ---------------------------------------------------------------------------

/// Python-facing log configuration.
#[pyclass(name = "LogConfig", from_py_object)]
#[derive(Clone)]
pub struct PyLogConfig {
    pub(crate) inner: LogConfig,
}

#[pymethods]
impl PyLogConfig {
    /// Create a new log configuration.
    ///
    /// Args:
    ///     level: Log level - "trace", "debug", "info", "warn", "error", "off" (default: "info")
    ///     log_request: Enable logging of incoming requests (default: true)
    ///     log_response: Enable logging of outgoing responses (default: true)
    ///     queue_size: Internal log queue capacity (default: 10000)
    ///     skip_paths: Paths to exclude from request/response logging
    #[new]
    #[pyo3(signature = (
        level = "info",
        log_request = true,
        log_response = true,
        queue_size = 10_000,
        skip_paths = None,
    ))]
    pub fn new(
        level: &str,
        log_request: bool,
        log_response: bool,
        queue_size: usize,
        skip_paths: Option<Vec<String>>,
    ) -> Self {
        let mut config = LogConfig {
            level: LogLevel::from_str(level),
            log_request,
            log_response,
            queue_size,
            ..LogConfig::default()
        };
        if let Some(paths) = skip_paths {
            config.skip_paths = paths;
        }
        Self { inner: config }
    }

    /// Disable all logging.
    #[staticmethod]
    pub fn disabled() -> Self {
        Self {
            inner: LogConfig {
                level: LogLevel::Off,
                log_request: false,
                log_response: false,
                queue_size: 1,
                skip_paths: vec![],
            },
        }
    }

    /// Enable only error logging.
    #[staticmethod]
    pub fn errors_only() -> Self {
        Self {
            inner: LogConfig {
                level: LogLevel::Error,
                log_request: false,
                log_response: false,
                ..LogConfig::default()
            },
        }
    }

    /// Enable verbose logging (debug level with request/response).
    #[staticmethod]
    pub fn verbose() -> Self {
        Self {
            inner: LogConfig {
                level: LogLevel::Debug,
                log_request: true,
                log_response: true,
                ..LogConfig::default()
            },
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "LogConfig(level='{}', log_request={}, log_response={})",
            self.inner.level.as_str().to_lowercase(),
            self.inner.log_request,
            self.inner.log_response,
        )
    }
}
