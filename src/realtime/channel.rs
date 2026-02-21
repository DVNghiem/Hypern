use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

use dashmap::DashMap;
use parking_lot::RwLock;
use pyo3::prelude::*;
use tokio::sync::broadcast;

/// Statistics for a single channel
#[pyclass(from_py_object)]
#[derive(Clone, Debug)]
pub struct ChannelStats {
    /// Channel name
    #[pyo3(get)]
    pub name: String,
    /// Number of active subscribers
    #[pyo3(get)]
    pub subscriber_count: usize,
    /// Total messages published
    #[pyo3(get)]
    pub total_messages: u64,
    /// Messages dropped due to lagging subscribers
    #[pyo3(get)]
    pub dropped_messages: u64,
    /// Channel metadata
    #[pyo3(get)]
    pub metadata: HashMap<String, String>,
}

#[pymethods]
impl ChannelStats {
    fn __repr__(&self) -> String {
        format!(
            "ChannelStats(name={:?}, subscribers={}, total_msgs={}, dropped={}, metadata={:?})",
            self.name, self.subscriber_count, self.total_messages, self.dropped_messages, self.metadata
        )
    }
}

/// Internal channel data
struct ChannelInner {
    sender: broadcast::Sender<String>,
    subscribers: HashSet<String>,
    total_messages: AtomicU64,
    dropped_messages: AtomicU64,
    metadata: HashMap<String, String>,
}

/// A subscriber handle that receives messages from a channel
#[pyclass]
pub struct Subscriber {
    channel_name: String,
    client_id: String,
    receiver: Arc<RwLock<broadcast::Receiver<String>>>,
    received_count: AtomicU64,
    missed_count: AtomicU64,
}

#[pymethods]
impl Subscriber {
    /// Get the channel name this subscriber is listening to
    #[getter]
    pub fn channel_name(&self) -> &str {
        &self.channel_name
    }

    /// Get the client ID
    #[getter]
    pub fn client_id(&self) -> &str {
        &self.client_id
    }

    /// Try to receive the next message (non-blocking)
    /// Returns None if no message is available
    pub fn try_recv(&self) -> PyResult<Option<String>> {
        let mut rx = self.receiver.write();
        match rx.try_recv() {
            Ok(msg) => {
                self.received_count.fetch_add(1, Ordering::Relaxed);
                Ok(Some(msg))
            }
            Err(broadcast::error::TryRecvError::Empty) => Ok(None),
            Err(broadcast::error::TryRecvError::Lagged(n)) => {
                self.missed_count.fetch_add(n, Ordering::Relaxed);
                // Try again after lag
                match rx.try_recv() {
                    Ok(msg) => {
                        self.received_count.fetch_add(1, Ordering::Relaxed);
                        Ok(Some(msg))
                    }
                    _ => Ok(None),
                }
            }
            Err(broadcast::error::TryRecvError::Closed) => Ok(None),
        }
    }

    /// Receive all pending messages (non-blocking drain)
    pub fn drain(&self) -> PyResult<Vec<String>> {
        let mut messages = Vec::new();
        let mut rx = self.receiver.write();
        loop {
            match rx.try_recv() {
                Ok(msg) => {
                    self.received_count.fetch_add(1, Ordering::Relaxed);
                    messages.push(msg);
                }
                Err(broadcast::error::TryRecvError::Lagged(n)) => {
                    self.missed_count.fetch_add(n, Ordering::Relaxed);
                    continue;
                }
                Err(_) => break,
            }
        }
        Ok(messages)
    }

    /// Get count of received messages
    #[getter]
    pub fn received_count(&self) -> u64 {
        self.received_count.load(Ordering::Relaxed)
    }

    /// Get count of missed messages (due to lag)
    #[getter]
    pub fn missed_count(&self) -> u64 {
        self.missed_count.load(Ordering::Relaxed)
    }

    fn __repr__(&self) -> String {
        format!(
            "Subscriber(channel={:?}, client={:?}, received={}, missed={})",
            self.channel_name,
            self.client_id,
            self.received_count.load(Ordering::Relaxed),
            self.missed_count.load(Ordering::Relaxed),
        )
    }
}

/// Pattern-based topic matching for pub/sub routing
///
/// Supports:
/// - Exact match: "chat:room1"
/// - Wildcard: "chat:*" matches "chat:room1", "chat:room2"
/// - Multi-level wildcard: "events:#" matches "events:user:login", "events:system:alert"
#[pyclass(from_py_object)]
#[derive(Clone)]
pub struct TopicMatcher {
    /// Pattern → set of subscriber client IDs
    patterns: Arc<DashMap<String, HashSet<String>>>,
}

#[pymethods]
impl TopicMatcher {
    #[new]
    pub fn new() -> Self {
        Self {
            patterns: Arc::new(DashMap::new()),
        }
    }

    /// Subscribe a client to a topic pattern
    pub fn subscribe(&self, pattern: &str, client_id: &str) {
        self.patterns
            .entry(pattern.to_string())
            .or_default()
            .insert(client_id.to_string());
    }

    /// Unsubscribe a client from a topic pattern
    pub fn unsubscribe(&self, pattern: &str, client_id: &str) -> bool {
        if let Some(mut entry) = self.patterns.get_mut(pattern) {
            let removed = entry.remove(client_id);
            if entry.is_empty() {
                drop(entry);
                self.patterns.remove(pattern);
            }
            removed
        } else {
            false
        }
    }

    /// Unsubscribe a client from all patterns
    pub fn unsubscribe_all(&self, client_id: &str) -> usize {
        let mut count = 0;
        let mut empty_patterns = Vec::new();

        for mut entry in self.patterns.iter_mut() {
            if entry.value_mut().remove(client_id) {
                count += 1;
            }
            if entry.value().is_empty() {
                empty_patterns.push(entry.key().clone());
            }
        }

        for pattern in empty_patterns {
            self.patterns.remove(&pattern);
        }

        count
    }

    /// Find all client IDs whose patterns match the given topic
    pub fn match_topic(&self, topic: &str) -> Vec<String> {
        let mut matched = HashSet::new();

        for entry in self.patterns.iter() {
            let pattern = entry.key();
            let clients = entry.value();

            if Self::pattern_matches(pattern, topic) {
                for client_id in clients.iter() {
                    matched.insert(client_id.clone());
                }
            }
        }

        matched.into_iter().collect()
    }

    /// Check if a specific pattern matches a topic
    #[staticmethod]
    pub fn pattern_matches(pattern: &str, topic: &str) -> bool {
        if pattern == topic {
            return true;
        }

        let pattern_parts: Vec<&str> = pattern.split(':').collect();
        let topic_parts: Vec<&str> = topic.split(':').collect();

        let mut pi = 0;
        let mut ti = 0;

        while pi < pattern_parts.len() && ti < topic_parts.len() {
            match pattern_parts[pi] {
                "#" => return true, // Multi-level wildcard matches everything after
                "*" => {
                    // Single-level wildcard matches exactly one segment
                    pi += 1;
                    ti += 1;
                }
                part => {
                    if part != topic_parts[ti] {
                        return false;
                    }
                    pi += 1;
                    ti += 1;
                }
            }
        }

        // Both must be fully consumed (unless pattern ended with #)
        pi == pattern_parts.len() && ti == topic_parts.len()
    }

    /// Get all registered patterns
    pub fn patterns(&self) -> Vec<String> {
        self.patterns.iter().map(|e| e.key().clone()).collect()
    }

    /// Get subscriber count for a pattern
    pub fn subscriber_count(&self, pattern: &str) -> usize {
        self.patterns
            .get(pattern)
            .map(|e| e.value().len())
            .unwrap_or(0)
    }

    fn __repr__(&self) -> String {
        format!("TopicMatcher(patterns={})", self.patterns.len())
    }
}

impl Default for TopicMatcher {
    fn default() -> Self {
        Self::new()
    }
}

/// High-performance channel manager for pub/sub messaging
///
/// Manages named channels with configurable buffer sizes.
/// Uses tokio broadcast channels internally for efficient fan-out.
///
/// Example (Python):
///     manager = ChannelManager(default_buffer_size=256)
///     manager.create_channel("chat:general")
///     sub = manager.subscribe("chat:general", "user-1")
///     manager.publish("chat:general", "Hello!")
///     msg = sub.try_recv()  # "Hello!"
#[pyclass]
pub struct ChannelManager {
    channels: Arc<DashMap<String, ChannelInner>>,
    default_buffer_size: usize,
    topic_matcher: TopicMatcher,
}

#[pymethods]
impl ChannelManager {
    #[new]
    #[pyo3(signature = (default_buffer_size=256))]
    pub fn new(default_buffer_size: usize) -> Self {
        Self {
            channels: Arc::new(DashMap::new()),
            default_buffer_size,
            topic_matcher: TopicMatcher::new(),
        }
    }

    /// Create a new channel with optional custom buffer size
    #[pyo3(signature = (name, buffer_size=None, metadata=None))]
    pub fn create_channel(
        &self,
        name: &str,
        buffer_size: Option<usize>,
        metadata: Option<HashMap<String, String>>,
    ) -> bool {
        if self.channels.contains_key(name) {
            return false;
        }

        let buf_size = buffer_size.unwrap_or(self.default_buffer_size);
        let (sender, _) = broadcast::channel(buf_size);

        self.channels.insert(
            name.to_string(),
            ChannelInner {
                sender,
                subscribers: HashSet::new(),
                total_messages: AtomicU64::new(0),
                dropped_messages: AtomicU64::new(0),
                metadata: metadata.unwrap_or_default(),
            },
        );

        true
    }

    /// Remove a channel
    pub fn remove_channel(&self, name: &str) -> bool {
        self.channels.remove(name).is_some()
    }

    /// Check if a channel exists
    pub fn has_channel(&self, name: &str) -> bool {
        self.channels.contains_key(name)
    }

    /// Subscribe a client to a channel, returns a Subscriber handle
    pub fn subscribe(&self, channel_name: &str, client_id: &str) -> PyResult<Subscriber> {
        let receiver = {
            let mut channel = self.channels.get_mut(channel_name).ok_or_else(|| {
                pyo3::exceptions::PyKeyError::new_err(format!(
                    "Channel '{}' does not exist",
                    channel_name
                ))
            })?;
            channel.subscribers.insert(client_id.to_string());
            channel.sender.subscribe()
        };

        // Also register with topic matcher for pattern-based routing
        self.topic_matcher.subscribe(channel_name, client_id);

        Ok(Subscriber {
            channel_name: channel_name.to_string(),
            client_id: client_id.to_string(),
            receiver: Arc::new(RwLock::new(receiver)),
            received_count: AtomicU64::new(0),
            missed_count: AtomicU64::new(0),
        })
    }

    /// Unsubscribe a client from a channel
    pub fn unsubscribe(&self, channel_name: &str, client_id: &str) -> bool {
        self.topic_matcher.unsubscribe(channel_name, client_id);

        if let Some(mut channel) = self.channels.get_mut(channel_name) {
            channel.subscribers.remove(client_id)
        } else {
            false
        }
    }

    /// Publish a message to a channel
    /// Returns the number of receivers that got the message
    pub fn publish(&self, channel_name: &str, message: &str) -> PyResult<usize> {
        let channel = self.channels.get(channel_name).ok_or_else(|| {
            pyo3::exceptions::PyKeyError::new_err(format!(
                "Channel '{}' does not exist",
                channel_name
            ))
        })?;

        channel.total_messages.fetch_add(1, Ordering::Relaxed);

        match channel.sender.send(message.to_string()) {
            Ok(n) => Ok(n),
            Err(_) => {
                // No active receivers
                Ok(0)
            }
        }
    }

    /// Publish a message to all channels matching a topic pattern
    /// Returns total number of receivers across all matched channels
    pub fn publish_to_topic(&self, topic: &str, message: &str) -> usize {
        let mut total = 0;
        for entry in self.channels.iter() {
            if TopicMatcher::pattern_matches(topic, entry.key())
                || TopicMatcher::pattern_matches(entry.key(), topic)
            {
                entry.total_messages.fetch_add(1, Ordering::Relaxed);
                if let Ok(n) = entry.sender.send(message.to_string()) {
                    total += n;
                }
            }
        }
        total
    }

    /// Get stats for a channel
    pub fn get_stats(&self, channel_name: &str) -> PyResult<ChannelStats> {
        let channel = self.channels.get(channel_name).ok_or_else(|| {
            pyo3::exceptions::PyKeyError::new_err(format!(
                "Channel '{}' does not exist",
                channel_name
            ))
        })?;

        Ok(ChannelStats {
            name: channel_name.to_string(),
            subscriber_count: channel.subscribers.len(),
            total_messages: channel.total_messages.load(Ordering::Relaxed),
            dropped_messages: channel.dropped_messages.load(Ordering::Relaxed),
            metadata: channel.metadata.clone(),
        })
    }

    /// List all channel names
    pub fn list_channels(&self) -> Vec<String> {
        self.channels.iter().map(|e| e.key().clone()).collect()
    }

    /// Get subscriber IDs for a channel
    pub fn get_subscribers(&self, channel_name: &str) -> PyResult<Vec<String>> {
        let channel = self.channels.get(channel_name).ok_or_else(|| {
            pyo3::exceptions::PyKeyError::new_err(format!(
                "Channel '{}' does not exist",
                channel_name
            ))
        })?;

        Ok(channel.subscribers.iter().cloned().collect())
    }

    /// Get the topic matcher for pattern-based routing
    #[getter]
    pub fn topic_matcher(&self) -> TopicMatcher {
        self.topic_matcher.clone()
    }

    /// Get total channel count
    pub fn channel_count(&self) -> usize {
        self.channels.len()
    }

    /// Remove all channels
    pub fn clear(&self) {
        self.channels.clear();
    }

    fn __repr__(&self) -> String {
        format!(
            "ChannelManager(channels={}, buffer_size={})",
            self.channels.len(),
            self.default_buffer_size,
        )
    }
}
