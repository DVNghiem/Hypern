"""
Realtime infrastructure for SSE/WebSocket communication.

Provides high-performance Rust-backed channel/topic abstractions,
presence tracking, backpressure-aware broadcasting, and heartbeat/
auto-reconnect helpers.

All heavy lifting is done in Rust; this module provides Pythonic wrappers
and async helpers.

Example — Channel-based pub/sub::

    from hypern.realtime import ChannelManager

    manager = ChannelManager(default_buffer_size=256)
    manager.create_channel("chat:general")

    sub = manager.subscribe("chat:general", "user-1")
    manager.publish("chat:general", '{"msg": "hello"}')
    message = sub.try_recv()  # '{"msg": "hello"}'

Example — Presence tracking::

    from hypern.realtime import PresenceTracker

    tracker = PresenceTracker()
    tracker.track("room:lobby", "alice", {"name": "Alice", "status": "online"})
    members = tracker.list("room:lobby")  # [PresenceInfo(...)]

Example — Backpressure broadcast::

    from hypern.realtime import RealtimeBroadcast, BroadcastConfig, BackpressurePolicy

    broadcast = RealtimeBroadcast()
    broadcast.create("alerts", BroadcastConfig(
        buffer_size=128,
        policy=BackpressurePolicy.DropOldest,
    ))
    rx = broadcast.subscribe("alerts")
    broadcast.send("alerts", '{"type": "warning", "msg": "CPU high"}')

Example — Heartbeat monitoring::

    from hypern.realtime import HeartbeatMonitor, HeartbeatConfig

    monitor = HeartbeatMonitor(HeartbeatConfig(interval_secs=15, timeout_secs=45))
    monitor.register("client-1")
    monitor.pong("client-1")  # record client response
    dead = monitor.check_timeouts()  # [] (still alive)
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Dict, List, Optional

from ._hypern import (
    # Channel / Topic
    ChannelManager as _ChannelManager,
    ChannelStats,
    Subscriber,
    TopicMatcher,
    # Presence
    PresenceTracker as _PresenceTracker,
    PresenceInfo,
    PresenceDiff,
    # Broadcast
    RealtimeBroadcast as _RealtimeBroadcast,
    BroadcastConfig,
    BroadcastStats,
    BroadcastSubscriber,
    BackpressurePolicy,
    # Heartbeat
    HeartbeatMonitor as _HeartbeatMonitor,
    HeartbeatConfig,
    HeartbeatStats,
    # SSE types (for integration)
    SSEEvent,
)


# ============================================================================
# Channel Manager wrapper with async helpers
# ============================================================================


class ChannelManager:
    """
    High-performance channel/topic manager for pub/sub messaging.

    Wraps Rust's ``tokio::broadcast`` channels for efficient fan-out.
    Supports pattern-based topic matching (wildcards).

    Args:
        default_buffer_size: Default broadcast buffer per channel (default: 256).

    Topic patterns:
        - ``"chat:general"`` — exact match
        - ``"chat:*"`` — single-level wildcard (matches ``chat:general``, ``chat:random``)
        - ``"events:#"`` — multi-level wildcard (matches ``events:user:login``)

    Example::

        manager = ChannelManager()
        manager.create_channel("chat:general")
        sub = manager.subscribe("chat:general", "user-1")
        manager.publish("chat:general", "Hello!")
        msg = sub.try_recv()  # "Hello!"
    """

    def __init__(self, default_buffer_size: int = 256):
        self._inner = _ChannelManager(default_buffer_size)

    def create_channel(
        self,
        name: str,
        buffer_size: Optional[int] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Create a new channel. Returns False if it already exists."""
        return self._inner.create_channel(name, buffer_size, metadata)

    def remove_channel(self, name: str) -> bool:
        return self._inner.remove_channel(name)

    def has_channel(self, name: str) -> bool:
        return self._inner.has_channel(name)

    def subscribe(self, channel_name: str, client_id: str) -> "Subscriber":
        return self._inner.subscribe(channel_name, client_id)

    def unsubscribe(self, channel_name: str, client_id: str) -> bool:
        return self._inner.unsubscribe(channel_name, client_id)

    def publish(self, channel_name: str, message: str) -> int:
        """Publish a message. Returns the number of receivers."""
        return self._inner.publish(channel_name, message)

    def publish_json(self, channel_name: str, data: Any) -> int:
        """Publish a JSON-serialized message to a channel."""
        return self._inner.publish(channel_name, json.dumps(data, separators=(",", ":")))

    def publish_to_topic(self, topic: str, message: str) -> int:
        """Publish to all channels matching a topic pattern."""
        return self._inner.publish_to_topic(topic, message)

    def get_stats(self, channel_name: str) -> "ChannelStats":
        return self._inner.get_stats(channel_name)

    def list_channels(self) -> List[str]:
        return self._inner.list_channels()

    def get_subscribers(self, channel_name: str) -> List[str]:
        return self._inner.get_subscribers(channel_name)

    @property
    def topic_matcher(self) -> "TopicMatcher":
        return self._inner.topic_matcher

    def channel_count(self) -> int:
        return self._inner.channel_count()

    def clear(self) -> None:
        self._inner.clear()

    async def subscribe_async(
        self,
        channel_name: str,
        client_id: str,
        callback: Callable[[str], Any],
        poll_interval: float = 0.01,
    ) -> None:
        """
        Subscribe and continuously poll for messages asynchronously.

        Args:
            channel_name: Channel to subscribe to.
            client_id: Unique client identifier.
            callback: Called with each message string.
            poll_interval: Seconds between polls (default: 0.01).
        """
        sub = self._inner.subscribe(channel_name, client_id)
        try:
            while True:
                msg = sub.try_recv()
                if msg is not None:
                    result = callback(msg)
                    if asyncio.iscoroutine(result):
                        await result
                else:
                    await asyncio.sleep(poll_interval)
        finally:
            self._inner.unsubscribe(channel_name, client_id)

    def __repr__(self) -> str:
        return repr(self._inner)


# ============================================================================
# Presence Tracker wrapper
# ============================================================================


class PresenceTracker:
    """
    Track connected clients' presence across channels.

    Provides join/leave tracking, metadata updates, diff-based incremental
    updates, and stale connection eviction.

    Example::

        tracker = PresenceTracker()
        tracker.track("room:lobby", "alice", {"name": "Alice"})
        tracker.track("room:lobby", "bob", {"name": "Bob"})
        members = tracker.list("room:lobby")  # [PresenceInfo, PresenceInfo]
        diff = tracker.flush_diff("room:lobby")  # PresenceDiff(joins=2, leaves=0)
    """

    def __init__(self):
        self._inner = _PresenceTracker()

    def track(
        self, channel: str, client_id: str, metadata: Optional[Dict[str, str]] = None
    ) -> "PresenceInfo":
        return self._inner.track(channel, client_id, metadata)

    def untrack(self, channel: str, client_id: str) -> bool:
        return self._inner.untrack(channel, client_id)

    def untrack_all(self, client_id: str) -> List[str]:
        return self._inner.untrack_all(client_id)

    def update(self, channel: str, client_id: str, metadata: Dict[str, str]) -> bool:
        return self._inner.update(channel, client_id, metadata)

    def touch(self, channel: str, client_id: str) -> bool:
        return self._inner.touch(channel, client_id)

    def list(self, channel: str) -> List["PresenceInfo"]:
        return self._inner.list(channel)

    def get(self, channel: str, client_id: str) -> Optional["PresenceInfo"]:
        return self._inner.get(channel, client_id)

    def count(self, channel: str) -> int:
        return self._inner.count(channel)

    def flush_diff(self, channel: str) -> "PresenceDiff":
        return self._inner.flush_diff(channel)

    def client_channels(self, client_id: str) -> List[str]:
        return self._inner.client_channels(client_id)

    def active_channels(self) -> List[str]:
        return self._inner.active_channels()

    def total_clients(self) -> int:
        return self._inner.total_clients()

    def evict_stale(self, timeout_secs: float) -> List[tuple]:
        return self._inner.evict_stale(timeout_secs)

    def clear(self) -> None:
        self._inner.clear()

    def track_json(
        self, channel: str, client_id: str, metadata: Any
    ) -> "PresenceInfo":
        """Track with JSON-serializable metadata (converted to str dict)."""
        str_meta = {str(k): str(v) for k, v in metadata.items()} if metadata else None
        return self._inner.track(channel, client_id, str_meta)

    def list_as_dicts(self, channel: str) -> List[Dict[str, Any]]:
        """List presence info as plain dicts (useful for JSON serialization)."""
        return [
            {
                "client_id": info.client_id,
                "channel": info.channel,
                "metadata": info.metadata,
                "joined_at": info.joined_at,
                "last_seen": info.last_seen,
            }
            for info in self._inner.list(channel)
        ]

    def diff_as_dict(self, channel: str) -> Dict[str, Any]:
        """Flush and return diff as a plain dict (useful for broadcasting)."""
        diff = self._inner.flush_diff(channel)
        return {
            "joins": [
                {
                    "client_id": info.client_id,
                    "metadata": info.metadata,
                }
                for info in diff.joins
            ],
            "leaves": diff.leaves,
        }

    def __repr__(self) -> str:
        return repr(self._inner)


# ============================================================================
# Broadcast wrapper
# ============================================================================


class RealtimeBroadcast:
    """
    Backpressure-aware broadcast system.

    Supports multiple named channels with configurable buffer sizes,
    overflow policies, and optional message deduplication.

    Example::

        broadcast = RealtimeBroadcast()
        broadcast.create("alerts", BroadcastConfig(buffer_size=128))
        rx = broadcast.subscribe("alerts")
        broadcast.send("alerts", '{"alert": "CPU high"}')
        msg = rx.try_recv()  # '{"alert": "CPU high"}'
    """

    def __init__(self):
        self._inner = _RealtimeBroadcast()

    def create(self, name: str, config: Optional["BroadcastConfig"] = None) -> bool:
        return self._inner.create(name, config)

    def remove(self, name: str) -> bool:
        return self._inner.remove(name)

    def subscribe(self, name: str) -> "BroadcastSubscriber":
        return self._inner.subscribe(name)

    def send(
        self, name: str, message: str, message_id: Optional[str] = None
    ) -> int:
        return self._inner.send(name, message, message_id)

    def send_json(
        self,
        name: str,
        data: Any,
        message_id: Optional[str] = None,
    ) -> int:
        """Send a JSON-serialized message to a broadcast channel."""
        return self._inner.send(
            name,
            json.dumps(data, separators=(",", ":")),
            message_id,
        )

    def send_many(self, names: List[str], message: str) -> Dict[str, int]:
        return self._inner.send_many(names, message)

    def stats(self, name: str) -> "BroadcastStats":
        return self._inner.stats(name)

    def global_stats(self) -> "BroadcastStats":
        return self._inner.global_stats()

    def list_channels(self) -> List[str]:
        return self._inner.list_channels()

    def has_channel(self, name: str) -> bool:
        return self._inner.has_channel(name)

    def clear(self) -> None:
        self._inner.clear()

    async def subscribe_async(
        self,
        name: str,
        callback: Callable[[str], Any],
        poll_interval: float = 0.01,
    ) -> None:
        """
        Subscribe and poll for messages asynchronously.

        Args:
            name: Broadcast channel name.
            callback: Called with each message.
            poll_interval: Seconds between polls (default: 0.01).
        """
        rx = self._inner.subscribe(name)
        while True:
            msg = rx.try_recv()
            if msg is not None:
                result = callback(msg)
                if asyncio.iscoroutine(result):
                    await result
            else:
                await asyncio.sleep(poll_interval)

    def __repr__(self) -> str:
        return repr(self._inner)


# ============================================================================
# Heartbeat Monitor wrapper with async loop
# ============================================================================


class HeartbeatMonitor:
    """
    Server-side heartbeat monitor for SSE and WebSocket connections.

    Tracks client liveness, supports SSE Last-Event-ID for stream resumption,
    and generates SSE keepalive/retry events.

    Example::

        monitor = HeartbeatMonitor(HeartbeatConfig(
            interval_secs=15,
            timeout_secs=45,
            sse_retry_ms=3000,
        ))
        monitor.register("client-1")
        # ... later, when client responds:
        monitor.pong("client-1")
        # Check for dead connections:
        dead = monitor.check_timeouts()
    """

    def __init__(self, config: Optional["HeartbeatConfig"] = None):
        self._inner = _HeartbeatMonitor(config)

    def __getattr__(self, name: str) -> Any:
        """Delegate all other attributes to _inner."""
        return getattr(self._inner, name)

    async def run_heartbeat_loop(
        self,
        on_ping: Optional[Callable[[str], Any]] = None,
        on_timeout: Optional[Callable[[str], Any]] = None,
        on_dead: Optional[Callable[[str], Any]] = None,
    ) -> None:
        """
        Run an async heartbeat loop that periodically:
        1. Pings clients that need pings
        2. Checks for timeouts
        3. Evicts dead clients

        Args:
            on_ping: Called with client_id when a ping should be sent.
            on_timeout: Called with client_id on timeout detection.
            on_dead: Called with client_id when a client is evicted.
        """
        interval = self.config.interval_secs
        while True:
            # Ping clients
            for client_id in self.clients_needing_ping():
                self.ping(client_id)
                if on_ping:
                    result = on_ping(client_id)
                    if asyncio.iscoroutine(result):
                        await result

            # Check timeouts
            for client_id in self.check_timeouts():
                if on_timeout:
                    result = on_timeout(client_id)
                    if asyncio.iscoroutine(result):
                        await result

            # Evict dead clients
            for client_id in self.evict_dead():
                if on_dead:
                    result = on_dead(client_id)
                    if asyncio.iscoroutine(result):
                        await result

            await asyncio.sleep(interval)

    def make_sse_event(
        self,
        data: str,
        event: Optional[str] = None,
        id: Optional[str] = None,
    ) -> "SSEEvent":
        """
        Create an SSE event with the heartbeat config's retry value.

        Args:
            data: Event data.
            event: Optional event type.
            id: Optional event ID.

        Returns:
            SSEEvent with retry set from heartbeat config.
        """
        return SSEEvent(
            data=data,
            event=event,
            id=id,
            retry=self.config.sse_retry_ms,
        )


# ============================================================================
# Convenience: RealtimeHub combines all components
# ============================================================================


class RealtimeHub:
    """
    Convenience wrapper that bundles all realtime components together.

    Provides a single entry point for channel management, presence
    tracking, broadcasting, and heartbeat monitoring.

    Example::

        hub = RealtimeHub()

        # Create a channel with presence and broadcast
        hub.channels.create_channel("chat:general")
        hub.broadcast.create("chat:general")

        # Track user presence
        hub.presence.track("chat:general", "alice", {"name": "Alice"})

        # Start heartbeat monitoring
        hub.heartbeat.register("alice")

        # Publish & broadcast
        hub.channels.publish("chat:general", "Hello everyone!")
    """

    def __init__(
        self,
        channel_buffer_size: int = 256,
        heartbeat_config: Optional[HeartbeatConfig] = None,
    ):
        self.channels = ChannelManager(default_buffer_size=channel_buffer_size)
        self.presence = PresenceTracker()
        self.broadcast = RealtimeBroadcast()
        self.heartbeat = HeartbeatMonitor(heartbeat_config)

    def create_channel(
        self,
        name: str,
        buffer_size: Optional[int] = None,
        broadcast_config: Optional[BroadcastConfig] = None,
    ) -> None:
        """
        Create a channel with optional broadcast support.

        Args:
            name: Channel name.
            buffer_size: Optional buffer size override.
            broadcast_config: If provided, also creates a broadcast channel.
        """
        self.channels.create_channel(name, buffer_size)
        if broadcast_config is not None:
            self.broadcast.create(name, broadcast_config)

    def join(
        self,
        channel: str,
        client_id: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> "Subscriber":
        """
        Join a channel: subscribe + track presence + register heartbeat.

        Args:
            channel: Channel name.
            client_id: Unique client ID.
            metadata: Optional presence metadata.

        Returns:
            A Subscriber handle for receiving messages.
        """
        sub = self.channels.subscribe(channel, client_id)
        self.presence.track(channel, client_id, metadata)
        self.heartbeat.register(client_id)
        return sub

    def leave(self, channel: str, client_id: str) -> None:
        """
        Leave a channel: unsubscribe + untrack presence + unregister heartbeat.
        """
        self.channels.unsubscribe(channel, client_id)
        self.presence.untrack(channel, client_id)
        self.heartbeat.unregister(client_id)

    def disconnect(self, client_id: str) -> List[str]:
        """
        Fully disconnect a client from all channels.

        Returns:
            List of channels the client was removed from.
        """
        channels = self.presence.untrack_all(client_id)
        for ch in channels:
            self.channels.unsubscribe(ch, client_id)
        self.heartbeat.unregister(client_id)
        return channels

    def publish(self, channel: str, message: str) -> int:
        """Publish a message to a channel."""
        return self.channels.publish(channel, message)

    def publish_json(self, channel: str, data: Any) -> int:
        """Publish a JSON-serialized message to a channel."""
        return self.channels.publish_json(channel, data)

    def get_presence(self, channel: str) -> List["PresenceInfo"]:
        """Get presence info for a channel."""
        return self.presence.list(channel)

    def get_presence_diff(self, channel: str) -> Dict[str, Any]:
        """Get and flush presence diff for a channel."""
        return self.presence.diff_as_dict(channel)

    def __repr__(self) -> str:
        return (
            f"RealtimeHub("
            f"channels={self.channels.channel_count()}, "
            f"clients={self.presence.total_clients()}, "
            f"heartbeat={self.heartbeat.client_count()}"
            f")"
        )


__all__ = [
    # Channel / Topic
    "ChannelManager",
    "ChannelStats",
    "Subscriber",
    "TopicMatcher",
    # Presence
    "PresenceTracker",
    "PresenceInfo",
    "PresenceDiff",
    # Broadcast
    "RealtimeBroadcast",
    "BroadcastConfig",
    "BroadcastStats",
    "BroadcastSubscriber",
    "BackpressurePolicy",
    # Heartbeat
    "HeartbeatMonitor",
    "HeartbeatConfig",
    "HeartbeatStats",
    # Hub
    "RealtimeHub",
]
