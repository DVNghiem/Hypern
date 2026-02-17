//! Live SSE/WebSocket Realtime Infrastructure
//!
//! Provides channel/topic abstractions, presence tracking,
//! backpressure-aware broadcast, and heartbeat/auto-reconnect helpers.
//!
//! All types are exposed to Python via PyO3.

pub mod broadcast;
pub mod channel;
pub mod heartbeat;
pub mod presence;

// Re-export main types for convenience
pub use broadcast::{BackpressurePolicy, BroadcastConfig, BroadcastStats, RealtimeBroadcast};
pub use channel::{ChannelManager, ChannelStats, Subscriber, TopicMatcher};
pub use heartbeat::{HeartbeatConfig, HeartbeatMonitor, HeartbeatStats};
pub use presence::{PresenceDiff, PresenceInfo, PresenceTracker};
