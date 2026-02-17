use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use dashmap::DashMap;
use pyo3::prelude::*;

/// Configuration for heartbeat monitoring
#[pyclass]
#[derive(Clone, Debug)]
pub struct HeartbeatConfig {
    /// Interval between heartbeat pings (seconds)
    #[pyo3(get, set)]
    pub interval_secs: f64,
    /// Timeout to consider a client dead (seconds)
    #[pyo3(get, set)]
    pub timeout_secs: f64,
    /// Maximum reconnection attempts before giving up
    #[pyo3(get, set)]
    pub max_retries: u32,
    /// SSE retry field value in milliseconds (sent to clients for auto-reconnect)
    #[pyo3(get, set)]
    pub sse_retry_ms: u64,
    /// Whether to send keepalive comments for SSE
    #[pyo3(get, set)]
    pub send_keepalive: bool,
}

#[pymethods]
impl HeartbeatConfig {
    #[new]
    #[pyo3(signature = (interval_secs=30.0, timeout_secs=90.0, max_retries=5, sse_retry_ms=3000, send_keepalive=true))]
    pub fn new(
        interval_secs: f64,
        timeout_secs: f64,
        max_retries: u32,
        sse_retry_ms: u64,
        send_keepalive: bool,
    ) -> Self {
        Self {
            interval_secs,
            timeout_secs,
            max_retries,
            sse_retry_ms,
            send_keepalive,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "HeartbeatConfig(interval={}s, timeout={}s, retries={}, sse_retry={}ms, keepalive={})",
            self.interval_secs,
            self.timeout_secs,
            self.max_retries,
            self.sse_retry_ms,
            self.send_keepalive,
        )
    }
}

impl Default for HeartbeatConfig {
    fn default() -> Self {
        Self {
            interval_secs: 30.0,
            timeout_secs: 90.0,
            max_retries: 5,
            sse_retry_ms: 3000,
            send_keepalive: true,
        }
    }
}

/// Stats for heartbeat monitoring
#[pyclass]
#[derive(Clone, Debug, Default)]
pub struct HeartbeatStats {
    /// Number of clients being monitored
    #[pyo3(get)]
    pub monitored_clients: usize,
    /// Total pings sent
    #[pyo3(get)]
    pub total_pings: u64,
    /// Total pongs received
    #[pyo3(get)]
    pub total_pongs: u64,
    /// Total timeouts detected
    #[pyo3(get)]
    pub total_timeouts: u64,
    /// Currently timed-out clients
    #[pyo3(get)]
    pub timed_out_clients: usize,
}

#[pymethods]
impl HeartbeatStats {
    fn __repr__(&self) -> String {
        format!(
            "HeartbeatStats(monitored={}, pings={}, pongs={}, timeouts={}, timed_out={})",
            self.monitored_clients,
            self.total_pings,
            self.total_pongs,
            self.total_timeouts,
            self.timed_out_clients,
        )
    }
}

/// Per-client heartbeat state
struct ClientHeartbeat {
    last_ping: f64,
    last_pong: f64,
    retry_count: u32,
    is_alive: AtomicBool,
    last_event_id: Option<String>,
}

/// Server-side heartbeat monitor for SSE and WebSocket connections
///
/// Tracks client liveness via ping/pong cycles and detects dead connections.
/// Also provides SSE Last-Event-ID tracking for resumable streams.
///
/// Example (Python):
///     config = HeartbeatConfig(interval_secs=15, timeout_secs=45)
///     monitor = HeartbeatMonitor(config)
///     monitor.register("client-1")
///     monitor.ping("client-1")  # record that we sent a ping
///     monitor.pong("client-1")  # record that client responded
///     dead = monitor.check_timeouts()  # list of timed-out client IDs
#[pyclass]
pub struct HeartbeatMonitor {
    config: HeartbeatConfig,
    clients: Arc<DashMap<String, ClientHeartbeat>>,
    total_pings: AtomicU64,
    total_pongs: AtomicU64,
    total_timeouts: AtomicU64,
}

#[pymethods]
impl HeartbeatMonitor {
    #[new]
    #[pyo3(signature = (config=None))]
    pub fn new(config: Option<HeartbeatConfig>) -> Self {
        Self {
            config: config.unwrap_or_default(),
            clients: Arc::new(DashMap::new()),
            total_pings: AtomicU64::new(0),
            total_pongs: AtomicU64::new(0),
            total_timeouts: AtomicU64::new(0),
        }
    }

    /// Get the heartbeat configuration
    #[getter]
    pub fn config(&self) -> HeartbeatConfig {
        self.config.clone()
    }

    /// Register a client for heartbeat monitoring
    #[pyo3(signature = (client_id, last_event_id=None))]
    pub fn register(&self, client_id: &str, last_event_id: Option<String>) {
        let now = now_secs();
        self.clients.insert(
            client_id.to_string(),
            ClientHeartbeat {
                last_ping: now,
                last_pong: now,
                retry_count: 0,
                is_alive: AtomicBool::new(true),
                last_event_id,
            },
        );
    }

    /// Unregister a client
    pub fn unregister(&self, client_id: &str) -> bool {
        self.clients.remove(client_id).is_some()
    }

    /// Record that a ping was sent to a client
    pub fn ping(&self, client_id: &str) -> bool {
        if let Some(mut client) = self.clients.get_mut(client_id) {
            client.last_ping = now_secs();
            self.total_pings.fetch_add(1, Ordering::Relaxed);
            true
        } else {
            false
        }
    }

    /// Record that a pong was received from a client
    pub fn pong(&self, client_id: &str) -> bool {
        if let Some(mut client) = self.clients.get_mut(client_id) {
            client.last_pong = now_secs();
            client.retry_count = 0;
            client.is_alive.store(true, Ordering::Relaxed);
            self.total_pongs.fetch_add(1, Ordering::Relaxed);
            true
        } else {
            false
        }
    }

    /// Check for timed-out clients
    /// Returns list of client IDs that have exceeded the timeout
    pub fn check_timeouts(&self) -> Vec<String> {
        let now = now_secs();
        let timeout = self.config.timeout_secs;
        let mut timed_out = Vec::new();

        for mut entry in self.clients.iter_mut() {
            let client = entry.value_mut();
            if now - client.last_pong > timeout {
                if client.is_alive.load(Ordering::Relaxed) {
                    client.is_alive.store(false, Ordering::Relaxed);
                    client.retry_count += 1;
                    self.total_timeouts.fetch_add(1, Ordering::Relaxed);
                    timed_out.push(entry.key().clone());
                }
            }
        }

        timed_out
    }

    /// Check if a specific client has timed out
    pub fn is_timed_out(&self, client_id: &str) -> bool {
        self.clients
            .get(client_id)
            .map(|c| !c.is_alive.load(Ordering::Relaxed))
            .unwrap_or(true)
    }

    /// Check if a client is alive
    pub fn is_alive(&self, client_id: &str) -> bool {
        self.clients
            .get(client_id)
            .map(|c| c.is_alive.load(Ordering::Relaxed))
            .unwrap_or(false)
    }

    /// Get clients that exceeded max retries (should be disconnected)
    pub fn get_dead_clients(&self) -> Vec<String> {
        let max_retries = self.config.max_retries;
        self.clients
            .iter()
            .filter(|e| e.retry_count > max_retries)
            .map(|e| e.key().clone())
            .collect()
    }

    /// Remove dead clients (exceeded max retries) and return their IDs
    pub fn evict_dead(&self) -> Vec<String> {
        let dead = self.get_dead_clients();
        for client_id in &dead {
            self.clients.remove(client_id);
        }
        dead
    }

    /// Update the Last-Event-ID for a client (for SSE stream resumption)
    pub fn set_last_event_id(&self, client_id: &str, event_id: &str) -> bool {
        if let Some(mut client) = self.clients.get_mut(client_id) {
            client.last_event_id = Some(event_id.to_string());
            true
        } else {
            false
        }
    }

    /// Get the Last-Event-ID for a client (for SSE stream resumption)
    pub fn get_last_event_id(&self, client_id: &str) -> Option<String> {
        self.clients
            .get(client_id)
            .and_then(|c| c.last_event_id.clone())
    }

    /// Get all clients that need a ping (last_ping older than interval)
    pub fn clients_needing_ping(&self) -> Vec<String> {
        let now = now_secs();
        let interval = self.config.interval_secs;

        self.clients
            .iter()
            .filter(|e| {
                let c = e.value();
                c.is_alive.load(Ordering::Relaxed) && (now - c.last_ping > interval)
            })
            .map(|e| e.key().clone())
            .collect()
    }

    /// Generate an SSE keepalive comment string
    pub fn sse_keepalive_comment(&self) -> String {
        ": keepalive\n\n".to_string()
    }

    /// Generate an SSE retry field string
    pub fn sse_retry_field(&self) -> String {
        format!("retry: {}\n\n", self.config.sse_retry_ms)
    }

    /// Generate a full SSE heartbeat event (includes retry + keepalive comment)
    pub fn sse_heartbeat_event(&self) -> String {
        let mut event = String::new();
        if self.config.sse_retry_ms > 0 {
            event.push_str(&format!("retry: {}\n", self.config.sse_retry_ms));
        }
        event.push_str(": heartbeat\n\n");
        event
    }

    /// Get the retry count for a client
    pub fn retry_count(&self, client_id: &str) -> u32 {
        self.clients
            .get(client_id)
            .map(|c| c.retry_count)
            .unwrap_or(0)
    }

    /// Get monitor statistics
    pub fn stats(&self) -> HeartbeatStats {
        let now = now_secs();
        let timeout = self.config.timeout_secs;
        let timed_out = self
            .clients
            .iter()
            .filter(|e| now - e.last_pong > timeout)
            .count();

        HeartbeatStats {
            monitored_clients: self.clients.len(),
            total_pings: self.total_pings.load(Ordering::Relaxed),
            total_pongs: self.total_pongs.load(Ordering::Relaxed),
            total_timeouts: self.total_timeouts.load(Ordering::Relaxed),
            timed_out_clients: timed_out,
        }
    }

    /// Get all monitored client IDs
    pub fn client_ids(&self) -> Vec<String> {
        self.clients.iter().map(|e| e.key().clone()).collect()
    }

    /// Get metadata map of all clients: {client_id: {alive, retries, last_pong_ago}}
    pub fn client_info(&self) -> HashMap<String, HashMap<String, String>> {
        let now = now_secs();
        let mut result = HashMap::new();

        for entry in self.clients.iter() {
            let mut info = HashMap::new();
            info.insert(
                "alive".to_string(),
                entry.is_alive.load(Ordering::Relaxed).to_string(),
            );
            info.insert("retries".to_string(), entry.retry_count.to_string());
            info.insert(
                "last_pong_ago_secs".to_string(),
                format!("{:.1}", now - entry.last_pong),
            );
            if let Some(ref eid) = entry.last_event_id {
                info.insert("last_event_id".to_string(), eid.clone());
            }
            result.insert(entry.key().clone(), info);
        }

        result
    }

    /// Clear all monitored clients
    pub fn clear(&self) {
        self.clients.clear();
    }

    /// Total number of monitored clients
    pub fn client_count(&self) -> usize {
        self.clients.len()
    }

    fn __repr__(&self) -> String {
        format!(
            "HeartbeatMonitor(clients={}, config={})",
            self.clients.len(),
            self.config.__repr__(),
        )
    }
}

impl Default for HeartbeatMonitor {
    fn default() -> Self {
        Self::new(None)
    }
}

fn now_secs() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}
