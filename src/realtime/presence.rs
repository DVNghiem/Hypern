use std::collections::HashMap;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use dashmap::DashMap;
use pyo3::prelude::*;

/// Information about a connected client's presence
#[pyclass]
#[derive(Clone, Debug)]
pub struct PresenceInfo {
    /// Client identifier
    #[pyo3(get)]
    pub client_id: String,
    /// Channel name
    #[pyo3(get)]
    pub channel: String,
    /// Arbitrary metadata (e.g., username, avatar, status)
    #[pyo3(get)]
    pub metadata: HashMap<String, String>,
    /// Unix timestamp when the client joined
    #[pyo3(get)]
    pub joined_at: f64,
    /// Unix timestamp of last activity
    #[pyo3(get)]
    pub last_seen: f64,
}

#[pymethods]
impl PresenceInfo {
    #[new]
    #[pyo3(signature = (client_id, channel, metadata=None))]
    pub fn new(
        client_id: String,
        channel: String,
        metadata: Option<HashMap<String, String>>,
    ) -> Self {
        let now = now_secs();
        Self {
            client_id,
            channel,
            metadata: metadata.unwrap_or_default(),
            joined_at: now,
            last_seen: now,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "PresenceInfo(client={:?}, channel={:?}, meta={:?})",
            self.client_id, self.channel, self.metadata
        )
    }
}

/// Diff of presence changes (joins and leaves) for incremental updates
#[pyclass]
#[derive(Clone, Debug, Default)]
pub struct PresenceDiff {
    /// Clients who joined since last diff
    #[pyo3(get)]
    pub joins: Vec<PresenceInfo>,
    /// Client IDs who left since last diff
    #[pyo3(get)]
    pub leaves: Vec<String>,
}

#[pymethods]
impl PresenceDiff {
    #[new]
    pub fn new() -> Self {
        Self::default()
    }

    /// Check if the diff has any changes
    pub fn has_changes(&self) -> bool {
        !self.joins.is_empty() || !self.leaves.is_empty()
    }

    /// Total number of changes
    pub fn change_count(&self) -> usize {
        self.joins.len() + self.leaves.len()
    }

    fn __repr__(&self) -> String {
        format!(
            "PresenceDiff(joins={}, leaves={})",
            self.joins.len(),
            self.leaves.len()
        )
    }
}

/// Per-channel presence data
struct ChannelPresence {
    members: HashMap<String, PresenceInfo>,
    // Accumulate changes for diff-based updates
    pending_joins: Vec<PresenceInfo>,
    pending_leaves: Vec<String>,
}

impl ChannelPresence {
    fn new() -> Self {
        Self {
            members: HashMap::new(),
            pending_joins: Vec::new(),
            pending_leaves: Vec::new(),
        }
    }
}

/// Track connected clients' presence across channels
///
/// Example (Python):
///     tracker = PresenceTracker()
///     tracker.track("chat:general", "user-1", {"name": "Alice", "status": "online"})
///     tracker.track("chat:general", "user-2", {"name": "Bob", "status": "away"})
///     members = tracker.list("chat:general")  # [PresenceInfo(...), PresenceInfo(...)]
///     diff = tracker.flush_diff("chat:general")  # PresenceDiff(joins=2, leaves=0)
#[pyclass]
pub struct PresenceTracker {
    channels: Arc<DashMap<String, ChannelPresence>>,
    /// Global client → channels mapping for fast cleanup
    client_channels: Arc<DashMap<String, Vec<String>>>,
}

#[pymethods]
impl PresenceTracker {
    #[new]
    pub fn new() -> Self {
        Self {
            channels: Arc::new(DashMap::new()),
            client_channels: Arc::new(DashMap::new()),
        }
    }

    /// Track a client's presence in a channel
    #[pyo3(signature = (channel, client_id, metadata=None))]
    pub fn track(
        &self,
        channel: &str,
        client_id: &str,
        metadata: Option<HashMap<String, String>>,
    ) -> PresenceInfo {
        let info = PresenceInfo::new(
            client_id.to_string(),
            channel.to_string(),
            metadata,
        );

        // Add to channel
        self.channels
            .entry(channel.to_string())
            .or_insert_with(ChannelPresence::new)
            .members
            .insert(client_id.to_string(), info.clone());

        // Record as pending join for diff
        if let Some(mut cp) = self.channels.get_mut(channel) {
            cp.pending_joins.push(info.clone());
        }

        // Track client → channels mapping
        self.client_channels
            .entry(client_id.to_string())
            .or_default()
            .push(channel.to_string());

        info
    }

    /// Remove a client's presence from a channel
    pub fn untrack(&self, channel: &str, client_id: &str) -> bool {
        let removed = if let Some(mut cp) = self.channels.get_mut(channel) {
            let existed = cp.members.remove(client_id).is_some();
            if existed {
                cp.pending_leaves.push(client_id.to_string());
            }
            existed
        } else {
            false
        };

        // Clean up empty channels
        if let Some(cp) = self.channels.get(channel) {
            if cp.members.is_empty() && cp.pending_joins.is_empty() && cp.pending_leaves.is_empty()
            {
                drop(cp);
                self.channels.remove(channel);
            }
        }

        // Update client → channels mapping
        if let Some(mut channels) = self.client_channels.get_mut(client_id) {
            channels.retain(|c| c != channel);
            if channels.is_empty() {
                drop(channels);
                self.client_channels.remove(client_id);
            }
        }

        removed
    }

    /// Remove a client from ALL channels (e.g., on disconnect)
    pub fn untrack_all(&self, client_id: &str) -> Vec<String> {
        let channels_left = if let Some((_, channels)) = self.client_channels.remove(client_id) {
            channels
        } else {
            return Vec::new();
        };

        for channel in &channels_left {
            if let Some(mut cp) = self.channels.get_mut(channel) {
                if cp.members.remove(client_id).is_some() {
                    cp.pending_leaves.push(client_id.to_string());
                }
            }
        }

        channels_left
    }

    /// Update a client's metadata (e.g., status change)
    #[pyo3(signature = (channel, client_id, metadata))]
    pub fn update(
        &self,
        channel: &str,
        client_id: &str,
        metadata: HashMap<String, String>,
    ) -> bool {
        if let Some(mut cp) = self.channels.get_mut(channel) {
            if let Some(info) = cp.members.get_mut(client_id) {
                info.metadata = metadata;
                info.last_seen = now_secs();
                return true;
            }
        }
        false
    }

    /// Touch a client's last_seen timestamp (heartbeat)
    pub fn touch(&self, channel: &str, client_id: &str) -> bool {
        if let Some(mut cp) = self.channels.get_mut(channel) {
            if let Some(info) = cp.members.get_mut(client_id) {
                info.last_seen = now_secs();
                return true;
            }
        }
        false
    }

    /// List all present clients in a channel
    pub fn list(&self, channel: &str) -> Vec<PresenceInfo> {
        self.channels
            .get(channel)
            .map(|cp| cp.members.values().cloned().collect())
            .unwrap_or_default()
    }

    /// Get presence info for a specific client in a channel
    pub fn get(&self, channel: &str, client_id: &str) -> Option<PresenceInfo> {
        self.channels
            .get(channel)
            .and_then(|cp| cp.members.get(client_id).cloned())
    }

    /// Count members in a channel
    pub fn count(&self, channel: &str) -> usize {
        self.channels
            .get(channel)
            .map(|cp| cp.members.len())
            .unwrap_or(0)
    }

    /// Flush and return the accumulated diff for a channel
    /// This is useful for sending incremental presence updates
    pub fn flush_diff(&self, channel: &str) -> PresenceDiff {
        if let Some(mut cp) = self.channels.get_mut(channel) {
            let joins = std::mem::take(&mut cp.pending_joins);
            let leaves = std::mem::take(&mut cp.pending_leaves);
            PresenceDiff { joins, leaves }
        } else {
            PresenceDiff::default()
        }
    }

    /// Get all channels a client is present in
    pub fn client_channels(&self, client_id: &str) -> Vec<String> {
        self.client_channels
            .get(client_id)
            .map(|v| v.value().clone())
            .unwrap_or_default()
    }

    /// List all channels that have at least one member
    pub fn active_channels(&self) -> Vec<String> {
        self.channels
            .iter()
            .filter(|e| !e.members.is_empty())
            .map(|e| e.key().clone())
            .collect()
    }

    /// Get total number of tracked clients across all channels
    pub fn total_clients(&self) -> usize {
        self.client_channels.len()
    }

    /// Remove stale presences (last_seen older than timeout_secs)
    pub fn evict_stale(&self, timeout_secs: f64) -> Vec<(String, String)> {
        let cutoff = now_secs() - timeout_secs;
        let mut evicted = Vec::new();

        for mut entry in self.channels.iter_mut() {
            let channel = entry.key().clone();
            let cp = entry.value_mut();
            let stale: Vec<String> = cp
                .members
                .iter()
                .filter(|(_, info)| info.last_seen < cutoff)
                .map(|(id, _)| id.clone())
                .collect();

            for client_id in &stale {
                cp.members.remove(client_id);
                cp.pending_leaves.push(client_id.clone());
                evicted.push((channel.clone(), client_id.clone()));
            }
        }

        // Clean up client_channels mapping
        for (channel, client_id) in &evicted {
            if let Some(mut channels) = self.client_channels.get_mut(client_id) {
                channels.retain(|c| c != channel);
                if channels.is_empty() {
                    drop(channels);
                    self.client_channels.remove(client_id);
                }
            }
        }

        evicted
    }

    /// Clear all presence data
    pub fn clear(&self) {
        self.channels.clear();
        self.client_channels.clear();
    }

    fn __repr__(&self) -> String {
        format!(
            "PresenceTracker(channels={}, clients={})",
            self.channels.len(),
            self.client_channels.len(),
        )
    }
}

impl Default for PresenceTracker {
    fn default() -> Self {
        Self::new()
    }
}

fn now_secs() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}
