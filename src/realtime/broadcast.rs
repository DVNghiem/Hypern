use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

use dashmap::DashMap;
use parking_lot::RwLock;
use pyo3::prelude::*;
use tokio::sync::broadcast;

/// Policy for handling backpressure when subscribers are slow
#[pyclass(eq, eq_int)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BackpressurePolicy {
    /// Drop oldest messages when buffer is full (default)
    DropOldest = 0,
    /// Return error when buffer is full
    Error = 1,
}

/// Configuration for a broadcast channel
#[pyclass]
#[derive(Clone, Debug)]
pub struct BroadcastConfig {
    /// Maximum number of messages to buffer per subscriber
    #[pyo3(get, set)]
    pub buffer_size: usize,
    /// Backpressure policy
    #[pyo3(get, set)]
    pub policy: BackpressurePolicy,
    /// Enable message deduplication by ID
    #[pyo3(get, set)]
    pub dedup_enabled: bool,
    /// Maximum number of recent message IDs to track for dedup
    #[pyo3(get, set)]
    pub dedup_window: usize,
}

#[pymethods]
impl BroadcastConfig {
    #[new]
    #[pyo3(signature = (buffer_size=256, policy=BackpressurePolicy::DropOldest, dedup_enabled=false, dedup_window=1000))]
    pub fn new(
        buffer_size: usize,
        policy: BackpressurePolicy,
        dedup_enabled: bool,
        dedup_window: usize,
    ) -> Self {
        Self {
            buffer_size,
            policy,
            dedup_enabled,
            dedup_window,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "BroadcastConfig(buffer={}, policy={:?}, dedup={})",
            self.buffer_size, self.policy, self.dedup_enabled
        )
    }
}

impl Default for BroadcastConfig {
    fn default() -> Self {
        Self {
            buffer_size: 256,
            policy: BackpressurePolicy::DropOldest,
            dedup_enabled: false,
            dedup_window: 1000,
        }
    }
}

/// Statistics for broadcast operations
#[pyclass]
#[derive(Clone, Debug, Default)]
pub struct BroadcastStats {
    /// Total messages sent
    #[pyo3(get)]
    pub total_sent: u64,
    /// Total messages dropped (due to backpressure)
    #[pyo3(get)]
    pub total_dropped: u64,
    /// Total messages deduplicated (skipped)
    #[pyo3(get)]
    pub total_deduped: u64,
    /// Current number of active subscribers
    #[pyo3(get)]
    pub active_subscribers: usize,
    /// Number of broadcast channels
    #[pyo3(get)]
    pub channel_count: usize,
}

#[pymethods]
impl BroadcastStats {
    fn __repr__(&self) -> String {
        format!(
            "BroadcastStats(sent={}, dropped={}, deduped={}, subs={}, channels={})",
            self.total_sent,
            self.total_dropped,
            self.total_deduped,
            self.active_subscribers,
            self.channel_count,
        )
    }
}

/// Internal broadcast channel data
struct BroadcastInner {
    sender: broadcast::Sender<String>,
    config: BroadcastConfig,
    total_sent: AtomicU64,
    total_dropped: AtomicU64,
    total_deduped: AtomicU64,
    subscriber_count: AtomicU64,
    /// Ring buffer of recent message IDs for deduplication
    recent_ids: RwLock<Vec<String>>,
}

/// Backpressure-aware broadcast system
///
/// Supports multiple named broadcast channels with configurable
/// backpressure policies and optional message deduplication.
///
/// Example (Python):
///     broadcast = RealtimeBroadcast()
///     config = BroadcastConfig(buffer_size=128, policy=BackpressurePolicy.DropOldest)
///     broadcast.create("notifications", config)
///     rx = broadcast.subscribe("notifications")
///     count = broadcast.send("notifications", '{"type": "alert", "msg": "hello"}')
///     msg = rx.try_recv()  # '{"type": "alert", "msg": "hello"}'
#[pyclass]
pub struct RealtimeBroadcast {
    channels: Arc<DashMap<String, BroadcastInner>>,
}

/// Subscriber handle for receiving broadcast messages
#[pyclass]
pub struct BroadcastSubscriber {
    channel_name: String,
    receiver: Arc<RwLock<broadcast::Receiver<String>>>,
    received: AtomicU64,
    lagged: AtomicU64,
}

#[pymethods]
impl BroadcastSubscriber {
    /// Channel name
    #[getter]
    pub fn channel_name(&self) -> &str {
        &self.channel_name
    }

    /// Try to receive the next message (non-blocking)
    pub fn try_recv(&self) -> PyResult<Option<String>> {
        let mut rx = self.receiver.write();
        match rx.try_recv() {
            Ok(msg) => {
                self.received.fetch_add(1, Ordering::Relaxed);
                Ok(Some(msg))
            }
            Err(broadcast::error::TryRecvError::Empty) => Ok(None),
            Err(broadcast::error::TryRecvError::Lagged(n)) => {
                self.lagged.fetch_add(n, Ordering::Relaxed);
                match rx.try_recv() {
                    Ok(msg) => {
                        self.received.fetch_add(1, Ordering::Relaxed);
                        Ok(Some(msg))
                    }
                    _ => Ok(None),
                }
            }
            Err(broadcast::error::TryRecvError::Closed) => Ok(None),
        }
    }

    /// Drain all pending messages
    pub fn drain(&self) -> Vec<String> {
        let mut messages = Vec::new();
        let mut rx = self.receiver.write();
        loop {
            match rx.try_recv() {
                Ok(msg) => {
                    self.received.fetch_add(1, Ordering::Relaxed);
                    messages.push(msg);
                }
                Err(broadcast::error::TryRecvError::Lagged(n)) => {
                    self.lagged.fetch_add(n, Ordering::Relaxed);
                    continue;
                }
                Err(_) => break,
            }
        }
        messages
    }

    /// Get count of received messages
    #[getter]
    pub fn received_count(&self) -> u64 {
        self.received.load(Ordering::Relaxed)
    }

    /// Get count of messages missed due to lag
    #[getter]
    pub fn lagged_count(&self) -> u64 {
        self.lagged.load(Ordering::Relaxed)
    }

    fn __repr__(&self) -> String {
        format!(
            "BroadcastSubscriber(channel={:?}, received={}, lagged={})",
            self.channel_name,
            self.received.load(Ordering::Relaxed),
            self.lagged.load(Ordering::Relaxed),
        )
    }
}

#[pymethods]
impl RealtimeBroadcast {
    #[new]
    pub fn new() -> Self {
        Self {
            channels: Arc::new(DashMap::new()),
        }
    }

    /// Create a broadcast channel with configuration
    #[pyo3(signature = (name, config=None))]
    pub fn create(&self, name: &str, config: Option<BroadcastConfig>) -> bool {
        if self.channels.contains_key(name) {
            return false;
        }

        let cfg = config.unwrap_or_default();
        let (sender, _) = broadcast::channel(cfg.buffer_size);

        self.channels.insert(
            name.to_string(),
            BroadcastInner {
                sender,
                config: cfg.clone(),
                total_sent: AtomicU64::new(0),
                total_dropped: AtomicU64::new(0),
                total_deduped: AtomicU64::new(0),
                subscriber_count: AtomicU64::new(0),
                recent_ids: RwLock::new(Vec::with_capacity(cfg.dedup_window)),
            },
        );
        true
    }

    /// Remove a broadcast channel
    pub fn remove(&self, name: &str) -> bool {
        self.channels.remove(name).is_some()
    }

    /// Subscribe to a broadcast channel
    pub fn subscribe(&self, name: &str) -> PyResult<BroadcastSubscriber> {
        let channel = self.channels.get(name).ok_or_else(|| {
            pyo3::exceptions::PyKeyError::new_err(format!(
                "Broadcast channel '{}' does not exist",
                name
            ))
        })?;

        let rx = channel.sender.subscribe();
        channel.subscriber_count.fetch_add(1, Ordering::Relaxed);

        Ok(BroadcastSubscriber {
            channel_name: name.to_string(),
            receiver: Arc::new(RwLock::new(rx)),
            received: AtomicU64::new(0),
            lagged: AtomicU64::new(0),
        })
    }

    /// Send a message to a broadcast channel
    /// Returns number of receivers, or raises on error if policy is Error
    #[pyo3(signature = (name, message, message_id=None))]
    pub fn send(
        &self,
        name: &str,
        message: &str,
        message_id: Option<&str>,
    ) -> PyResult<usize> {
        let channel = self.channels.get(name).ok_or_else(|| {
            pyo3::exceptions::PyKeyError::new_err(format!(
                "Broadcast channel '{}' does not exist",
                name
            ))
        })?;

        // Deduplication check
        if channel.config.dedup_enabled {
            if let Some(msg_id) = message_id {
                let mut recent = channel.recent_ids.write();
                if recent.contains(&msg_id.to_string()) {
                    channel.total_deduped.fetch_add(1, Ordering::Relaxed);
                    return Ok(0);
                }
                recent.push(msg_id.to_string());
                // Evict old IDs if over window
                if recent.len() > channel.config.dedup_window {
                    let excess = recent.len() - channel.config.dedup_window;
                    recent.drain(0..excess);
                }
            }
        }

        channel.total_sent.fetch_add(1, Ordering::Relaxed);

        match channel.sender.send(message.to_string()) {
            Ok(n) => Ok(n),
            Err(_) => {
                // No receivers
                match channel.config.policy {
                    BackpressurePolicy::Error => Err(pyo3::exceptions::PyRuntimeError::new_err(
                        "No active subscribers",
                    )),
                    BackpressurePolicy::DropOldest => {
                        channel.total_dropped.fetch_add(1, Ordering::Relaxed);
                        Ok(0)
                    }
                }
            }
        }
    }

    /// Send a message to multiple broadcast channels at once
    pub fn send_many(&self, names: Vec<String>, message: &str) -> HashMap<String, usize> {
        let mut results = HashMap::new();
        for name in &names {
            if let Some(channel) = self.channels.get(name.as_str()) {
                channel.total_sent.fetch_add(1, Ordering::Relaxed);
                let count = channel.sender.send(message.to_string()).unwrap_or(0);
                results.insert(name.clone(), count);
            }
        }
        results
    }

    /// Get stats for a broadcast channel
    pub fn stats(&self, name: &str) -> PyResult<BroadcastStats> {
        let channel = self.channels.get(name).ok_or_else(|| {
            pyo3::exceptions::PyKeyError::new_err(format!(
                "Broadcast channel '{}' does not exist",
                name
            ))
        })?;

        Ok(BroadcastStats {
            total_sent: channel.total_sent.load(Ordering::Relaxed),
            total_dropped: channel.total_dropped.load(Ordering::Relaxed),
            total_deduped: channel.total_deduped.load(Ordering::Relaxed),
            active_subscribers: channel.subscriber_count.load(Ordering::Relaxed) as usize,
            channel_count: 1,
        })
    }

    /// Get aggregated stats across all broadcast channels
    pub fn global_stats(&self) -> BroadcastStats {
        let mut stats = BroadcastStats::default();
        stats.channel_count = self.channels.len();

        for entry in self.channels.iter() {
            stats.total_sent += entry.total_sent.load(Ordering::Relaxed);
            stats.total_dropped += entry.total_dropped.load(Ordering::Relaxed);
            stats.total_deduped += entry.total_deduped.load(Ordering::Relaxed);
            stats.active_subscribers += entry.subscriber_count.load(Ordering::Relaxed) as usize;
        }

        stats
    }

    /// List all broadcast channel names
    pub fn list_channels(&self) -> Vec<String> {
        self.channels.iter().map(|e| e.key().clone()).collect()
    }

    /// Check if a channel exists
    pub fn has_channel(&self, name: &str) -> bool {
        self.channels.contains_key(name)
    }

    /// Clear all channels
    pub fn clear(&self) {
        self.channels.clear();
    }

    fn __repr__(&self) -> String {
        format!("RealtimeBroadcast(channels={})", self.channels.len())
    }
}

impl Default for RealtimeBroadcast {
    fn default() -> Self {
        Self::new()
    }
}
