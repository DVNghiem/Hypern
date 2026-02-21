use pyo3::prelude::*;
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicU8, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::{watch, Notify};
use tracing::{info, warn};

// ---------------------------------------------------------------------------
// Health status
// ---------------------------------------------------------------------------

/// Health status levels (mapped to HTTP codes).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum HealthStatus {
    /// Service is starting up (503).
    Starting = 0,
    /// Service is healthy and ready (200).
    Healthy = 1,
    /// Service is draining – accepting no new connections (503 for readiness, 200 for liveness).
    Draining = 2,
    /// Service is unhealthy (503).
    Unhealthy = 3,
}

impl HealthStatus {
    fn from_u8(v: u8) -> Self {
        match v {
            0 => Self::Starting,
            1 => Self::Healthy,
            2 => Self::Draining,
            3 => Self::Unhealthy,
            _ => Self::Unhealthy,
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Starting => "starting",
            Self::Healthy => "healthy",
            Self::Draining => "draining",
            Self::Unhealthy => "unhealthy",
        }
    }

    /// Whether this status should report as *live* (liveness probe).
    pub fn is_live(&self) -> bool {
        matches!(self, Self::Starting | Self::Healthy | Self::Draining)
    }

    /// Whether this status should report as *ready* to accept traffic.
    pub fn is_ready(&self) -> bool {
        matches!(self, Self::Healthy)
    }
}

// ---------------------------------------------------------------------------
// HealthCheck – thread-safe, lock-free health state
// ---------------------------------------------------------------------------

/// Shared health state used by workers and the parent process.
#[derive(Clone)]
pub struct HealthCheck {
    inner: Arc<HealthCheckInner>,
}

struct HealthCheckInner {
    status: AtomicU8,
    /// Number of currently in-flight requests.
    in_flight: AtomicU64,
    /// Monotonic timestamp (nanos since some epoch) when the process started.
    started_at: Instant,
    /// User-defined custom checks (Python callables evaluated lazily).
    custom_checks: parking_lot::Mutex<Vec<String>>,
}

impl HealthCheck {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(HealthCheckInner {
                status: AtomicU8::new(HealthStatus::Starting as u8),
                in_flight: AtomicU64::new(0),
                started_at: Instant::now(),
                custom_checks: parking_lot::Mutex::new(Vec::new()),
            }),
        }
    }

    // -- status --

    pub fn status(&self) -> HealthStatus {
        HealthStatus::from_u8(self.inner.status.load(Ordering::Acquire))
    }

    pub fn set_status(&self, s: HealthStatus) {
        self.inner.status.store(s as u8, Ordering::Release);
    }

    pub fn mark_healthy(&self) {
        self.set_status(HealthStatus::Healthy);
    }

    pub fn mark_draining(&self) {
        self.set_status(HealthStatus::Draining);
    }

    pub fn mark_unhealthy(&self) {
        self.set_status(HealthStatus::Unhealthy);
    }

    // -- in-flight tracking --

    pub fn increment_in_flight(&self) -> u64 {
        self.inner.in_flight.fetch_add(1, Ordering::AcqRel) + 1
    }

    pub fn decrement_in_flight(&self) -> u64 {
        let prev = self.inner.in_flight.fetch_sub(1, Ordering::AcqRel);
        prev.saturating_sub(1)
    }

    pub fn in_flight(&self) -> u64 {
        self.inner.in_flight.load(Ordering::Acquire)
    }

    // -- uptime --

    pub fn uptime(&self) -> Duration {
        self.inner.started_at.elapsed()
    }

    // -- custom checks --

    pub fn add_custom_check(&self, name: String) {
        self.inner.custom_checks.lock().push(name);
    }

    pub fn custom_checks(&self) -> Vec<String> {
        self.inner.custom_checks.lock().clone()
    }

    // -- probe helpers --

    /// JSON body for the health endpoint.
    pub fn to_json(&self) -> String {
        let status = self.status();
        let uptime_secs = self.uptime().as_secs_f64();
        format!(
            r#"{{"status":"{}","live":{},"ready":{},"in_flight":{},"uptime_secs":{:.2}}}"#,
            status.as_str(),
            status.is_live(),
            status.is_ready(),
            self.in_flight(),
            uptime_secs,
        )
    }

    /// HTTP status code for liveness probe.
    pub fn liveness_code(&self) -> u16 {
        if self.status().is_live() {
            200
        } else {
            503
        }
    }

    /// HTTP status code for readiness probe.
    pub fn readiness_code(&self) -> u16 {
        if self.status().is_ready() {
            200
        } else {
            503
        }
    }

    /// HTTP status code for startup probe.
    pub fn startup_code(&self) -> u16 {
        if self.status() != HealthStatus::Starting {
            200
        } else {
            503
        }
    }
}

// ---------------------------------------------------------------------------
// ReloadManager – orchestrates graceful / hot reload
// ---------------------------------------------------------------------------

/// Configuration for the reload manager.
#[derive(Debug, Clone)]
pub struct ReloadConfig {
    /// Seconds to wait for in-flight requests to complete during drain.
    pub drain_timeout_secs: u64,
    /// Seconds between health-check polling loops.
    pub health_poll_interval_ms: u64,
    /// Grace period before marking new workers as ready.
    pub startup_grace_secs: u64,
    /// Whether health probe routes are enabled.
    pub health_probes_enabled: bool,
    /// Path prefix for health probes (default `/health`).
    pub health_path_prefix: String,
}

impl Default for ReloadConfig {
    fn default() -> Self {
        Self {
            drain_timeout_secs: 30,
            health_poll_interval_ms: 100,
            startup_grace_secs: 2,
            health_probes_enabled: true,
            health_path_prefix: "/_health".to_string(),
        }
    }
}

/// Manages zero-downtime reloads (both dev hot-reload and prod graceful reload).
///
/// Architecture:
/// - Parent keeps a `watch::Sender<ReloadSignal>` that workers subscribe to.
/// - On SIGUSR1 (prod) the parent:
///   1. Marks old workers as draining (stop accepting *new* connections).
///   2. Waits for in-flight requests to finish (up to `drain_timeout`).
///   3. Spawns new workers.
///   4. Once new workers pass startup probe, terminates old workers.
/// - On SIGUSR2 / file-change (dev):
///   1. Kills old workers immediately (in-flight requests are dropped).
///   2. Re-spawns workers.
#[derive(Clone)]
pub struct ReloadManager {
    inner: Arc<ReloadManagerInner>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReloadSignal {
    None,
    /// Graceful reload – drain first.
    Graceful,
    /// Hot reload – kill immediately.
    Hot,
    /// Full shutdown.
    Shutdown,
}

struct ReloadManagerInner {
    config: ReloadConfig,
    health: HealthCheck,
    signal_tx: watch::Sender<ReloadSignal>,
    signal_rx: watch::Receiver<ReloadSignal>,
    /// Set to true once drain is initiated.
    draining: AtomicBool,
    /// Notified when in-flight count reaches zero.
    drain_complete: Notify,
}

impl ReloadManager {
    pub fn new(config: ReloadConfig) -> Self {
        let health = HealthCheck::new();
        let (signal_tx, signal_rx) = watch::channel(ReloadSignal::None);
        Self {
            inner: Arc::new(ReloadManagerInner {
                config,
                health,
                signal_tx,
                signal_rx,
                draining: AtomicBool::new(false),
                drain_complete: Notify::new(),
            }),
        }
    }

    pub fn with_defaults() -> Self {
        Self::new(ReloadConfig::default())
    }

    // -- accessors --

    pub fn health(&self) -> &HealthCheck {
        &self.inner.health
    }

    pub fn config(&self) -> &ReloadConfig {
        &self.inner.config
    }

    pub fn subscribe(&self) -> watch::Receiver<ReloadSignal> {
        self.inner.signal_rx.clone()
    }

    // -- signalling --

    pub fn signal_graceful_reload(&self) {
        info!("Signalling graceful reload");
        let _ = self.inner.signal_tx.send(ReloadSignal::Graceful);
    }

    pub fn signal_hot_reload(&self) {
        info!("Signalling hot reload");
        let _ = self.inner.signal_tx.send(ReloadSignal::Hot);
    }

    pub fn signal_shutdown(&self) {
        info!("Signalling shutdown");
        let _ = self.inner.signal_tx.send(ReloadSignal::Shutdown);
    }

    // -- drain --

    /// Begin draining: stop accepting new requests and wait for in-flight to finish.
    pub fn start_drain(&self) {
        if self
            .inner
            .draining
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .is_ok()
        {
            info!("Starting connection drain");
            self.inner.health.mark_draining();
        }
    }

    pub fn is_draining(&self) -> bool {
        self.inner.draining.load(Ordering::Acquire)
    }

    /// Notify that one in-flight request completed. If in_flight == 0, wake drain waiters.
    pub fn on_request_complete(&self) {
        let remaining = self.inner.health.decrement_in_flight();
        if self.is_draining() && remaining == 0 {
            info!("All in-flight requests drained");
            self.inner.drain_complete.notify_waiters();
        }
    }

    /// Wait until all in-flight requests complete or timeout expires.
    pub async fn wait_for_drain(&self) -> bool {
        let timeout = Duration::from_secs(self.inner.config.drain_timeout_secs);

        if self.inner.health.in_flight() == 0 {
            return true;
        }

        tokio::select! {
            _ = self.inner.drain_complete.notified() => {
                info!("Drain completed successfully");
                true
            }
            _ = tokio::time::sleep(timeout) => {
                let remaining = self.inner.health.in_flight();
                warn!("Drain timeout reached with {} requests still in-flight", remaining);
                false
            }
        }
    }

    /// Reset after a reload cycle completes.
    pub fn reset_after_reload(&self) {
        self.inner.draining.store(false, Ordering::Release);
        self.inner.health.set_status(HealthStatus::Healthy);
        let _ = self.inner.signal_tx.send(ReloadSignal::None);
        info!("Reload cycle complete, status reset to healthy");
    }
}

// ---------------------------------------------------------------------------
// PyO3 wrappers
// ---------------------------------------------------------------------------

/// Python-facing health check / probe object.
#[pyclass(name = "HealthCheck", from_py_object)]
#[derive(Clone)]
pub struct PyHealthCheck {
    pub inner: HealthCheck,
}

#[pymethods]
impl PyHealthCheck {
    #[new]
    pub fn new() -> Self {
        Self {
            inner: HealthCheck::new(),
        }
    }

    /// Current health status string: "starting", "healthy", "draining", "unhealthy".
    pub fn status(&self) -> String {
        self.inner.status().as_str().to_string()
    }

    /// Mark the service as healthy and ready.
    pub fn mark_healthy(&self) {
        self.inner.mark_healthy();
    }

    /// Mark the service as draining (no new traffic).
    pub fn mark_draining(&self) {
        self.inner.mark_draining();
    }

    /// Mark the service as unhealthy.
    pub fn mark_unhealthy(&self) {
        self.inner.mark_unhealthy();
    }

    /// Number of in-flight requests.
    pub fn in_flight(&self) -> u64 {
        self.inner.in_flight()
    }

    /// Uptime in seconds.
    pub fn uptime_secs(&self) -> f64 {
        self.inner.uptime().as_secs_f64()
    }

    /// Whether the liveness probe passes.
    pub fn is_live(&self) -> bool {
        self.inner.status().is_live()
    }

    /// Whether the readiness probe passes.
    pub fn is_ready(&self) -> bool {
        self.inner.status().is_ready()
    }

    /// JSON representation of health state.
    pub fn to_json(&self) -> String {
        self.inner.to_json()
    }

    /// Add a named custom check (for display/debugging).
    pub fn add_custom_check(&self, name: String) {
        self.inner.add_custom_check(name);
    }

    pub fn __repr__(&self) -> String {
        format!(
            "HealthCheck(status={}, in_flight={}, uptime={:.1}s)",
            self.inner.status().as_str(),
            self.inner.in_flight(),
            self.inner.uptime().as_secs_f64()
        )
    }
}

/// Python-facing reload configuration.
#[pyclass(name = "ReloadConfig", from_py_object)]
#[derive(Clone)]
pub struct PyReloadConfig {
    pub inner: ReloadConfig,
}

#[pymethods]
impl PyReloadConfig {
    #[new]
    #[pyo3(signature = (
        drain_timeout_secs = 30,
        health_poll_interval_ms = 100,
        startup_grace_secs = 2,
        health_probes_enabled = true,
        health_path_prefix = "/_health".to_string(),
    ))]
    pub fn new(
        drain_timeout_secs: u64,
        health_poll_interval_ms: u64,
        startup_grace_secs: u64,
        health_probes_enabled: bool,
        health_path_prefix: String,
    ) -> Self {
        Self {
            inner: ReloadConfig {
                drain_timeout_secs,
                health_poll_interval_ms,
                startup_grace_secs,
                health_probes_enabled,
                health_path_prefix,
            },
        }
    }

    #[getter]
    pub fn drain_timeout_secs(&self) -> u64 {
        self.inner.drain_timeout_secs
    }

    #[getter]
    pub fn health_poll_interval_ms(&self) -> u64 {
        self.inner.health_poll_interval_ms
    }

    #[getter]
    pub fn startup_grace_secs(&self) -> u64 {
        self.inner.startup_grace_secs
    }

    #[getter]
    pub fn health_probes_enabled(&self) -> bool {
        self.inner.health_probes_enabled
    }

    #[getter]
    pub fn health_path_prefix(&self) -> String {
        self.inner.health_path_prefix.clone()
    }

    pub fn __repr__(&self) -> String {
        format!(
            "ReloadConfig(drain_timeout={}s, health_probes={})",
            self.inner.drain_timeout_secs, self.inner.health_probes_enabled,
        )
    }
}

/// Python-facing reload manager.
#[pyclass(name = "ReloadManager", from_py_object)]
#[derive(Clone)]
pub struct PyReloadManager {
    pub inner: ReloadManager,
}

#[pymethods]
impl PyReloadManager {
    #[new]
    #[pyo3(signature = (config = None))]
    pub fn new(config: Option<PyReloadConfig>) -> Self {
        let cfg = config.map(|c| c.inner).unwrap_or_default();
        Self {
            inner: ReloadManager::new(cfg),
        }
    }

    /// Get the health check instance.
    pub fn health(&self) -> PyHealthCheck {
        PyHealthCheck {
            inner: self.inner.health().clone(),
        }
    }

    /// Trigger a graceful reload (drain + restart workers).
    pub fn graceful_reload(&self) {
        self.inner.signal_graceful_reload();
    }

    /// Trigger a hot reload (immediate restart, dev mode).
    pub fn hot_reload(&self) {
        self.inner.signal_hot_reload();
    }

    /// Trigger shutdown.
    pub fn shutdown(&self) {
        self.inner.signal_shutdown();
    }

    /// Whether the server is currently draining.
    pub fn is_draining(&self) -> bool {
        self.inner.is_draining()
    }

    /// Current health status.
    pub fn status(&self) -> String {
        self.inner.health().status().as_str().to_string()
    }

    /// Number of in-flight requests.
    pub fn in_flight(&self) -> u64 {
        self.inner.health().in_flight()
    }

    pub fn __repr__(&self) -> String {
        format!(
            "ReloadManager(status={}, draining={}, in_flight={})",
            self.inner.health().status().as_str(),
            self.inner.is_draining(),
            self.inner.health().in_flight(),
        )
    }
}
