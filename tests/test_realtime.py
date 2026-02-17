"""
Comprehensive tests for Hypern Realtime module.

Tests cover:
- Channel/Topic abstractions (ChannelManager, TopicMatcher)
- Presence tracking (PresenceTracker)
- Backpressure-aware broadcast (RealtimeBroadcast)
- Heartbeat/auto-reconnect helpers (HeartbeatMonitor)
- RealtimeHub convenience wrapper
"""

import asyncio
import json
import time

import pytest

from hypern.realtime import (
    # Channel / Topic
    ChannelManager,
    ChannelStats,
    Subscriber,
    TopicMatcher,
    # Presence
    PresenceTracker,
    PresenceInfo,
    PresenceDiff,
    # Broadcast
    RealtimeBroadcast,
    BroadcastConfig,
    BroadcastStats,
    BroadcastSubscriber,
    BackpressurePolicy,
    # Heartbeat
    HeartbeatMonitor,
    HeartbeatConfig,
    HeartbeatStats,
    # Hub
    RealtimeHub,
)


# Override autouse conftest fixtures that need a test server
@pytest.fixture(autouse=True)
def reset_database():
    yield


# ============================================================================
# TopicMatcher Tests
# ============================================================================


class TestTopicMatcher:
    """Test pattern-based topic matching."""

    def test_exact_match(self):
        assert TopicMatcher.pattern_matches("chat:general", "chat:general") is True
        assert TopicMatcher.pattern_matches("chat:general", "chat:random") is False

    def test_single_wildcard(self):
        assert TopicMatcher.pattern_matches("chat:*", "chat:general") is True
        assert TopicMatcher.pattern_matches("chat:*", "chat:random") is True
        assert TopicMatcher.pattern_matches("chat:*", "users:online") is False

    def test_multi_level_wildcard(self):
        assert TopicMatcher.pattern_matches("events:#", "events:user:login") is True
        assert TopicMatcher.pattern_matches("events:#", "events:system:alert:critical") is True
        assert TopicMatcher.pattern_matches("events:#", "events:simple") is True
        assert TopicMatcher.pattern_matches("events:#", "other:thing") is False

    def test_no_match_different_prefix(self):
        assert TopicMatcher.pattern_matches("chat:*", "users:online") is False

    def test_subscribe_and_match(self):
        tm = TopicMatcher()
        tm.subscribe("chat:*", "user-1")
        tm.subscribe("chat:general", "user-2")

        matched = tm.match_topic("chat:general")
        assert "user-1" in matched
        assert "user-2" in matched

    def test_subscribe_and_match_no_overlap(self):
        tm = TopicMatcher()
        tm.subscribe("chat:*", "user-1")
        tm.subscribe("events:*", "user-2")

        matched = tm.match_topic("chat:general")
        assert "user-1" in matched
        assert "user-2" not in matched

    def test_unsubscribe(self):
        tm = TopicMatcher()
        tm.subscribe("chat:*", "user-1")
        assert tm.subscriber_count("chat:*") == 1

        removed = tm.unsubscribe("chat:*", "user-1")
        assert removed is True
        assert tm.subscriber_count("chat:*") == 0

    def test_unsubscribe_nonexistent(self):
        tm = TopicMatcher()
        assert tm.unsubscribe("chat:*", "nobody") is False

    def test_unsubscribe_all(self):
        tm = TopicMatcher()
        tm.subscribe("chat:*", "user-1")
        tm.subscribe("events:*", "user-1")
        tm.subscribe("chat:*", "user-2")

        count = tm.unsubscribe_all("user-1")
        assert count == 2
        assert tm.subscriber_count("chat:*") == 1  # user-2 remains

    def test_patterns_list(self):
        tm = TopicMatcher()
        tm.subscribe("a:*", "u1")
        tm.subscribe("b:*", "u1")
        patterns = tm.patterns()
        assert set(patterns) == {"a:*", "b:*"}

    def test_repr(self):
        tm = TopicMatcher()
        assert "TopicMatcher" in repr(tm)


# ============================================================================
# ChannelManager Tests
# ============================================================================


class TestChannelManager:
    """Test channel creation, pub/sub, and lifecycle."""

    def test_create_channel(self):
        mgr = ChannelManager()
        assert mgr.create_channel("test") is True
        assert mgr.has_channel("test") is True
        assert mgr.channel_count() == 1

    def test_create_duplicate_channel(self):
        mgr = ChannelManager()
        mgr.create_channel("test")
        assert mgr.create_channel("test") is False

    def test_remove_channel(self):
        mgr = ChannelManager()
        mgr.create_channel("test")
        assert mgr.remove_channel("test") is True
        assert mgr.has_channel("test") is False

    def test_remove_nonexistent(self):
        mgr = ChannelManager()
        assert mgr.remove_channel("nope") is False

    def test_subscribe_and_receive(self):
        mgr = ChannelManager()
        mgr.create_channel("ch")
        sub = mgr.subscribe("ch", "client-1")
        mgr.publish("ch", "hello")

        msg = sub.try_recv()
        assert msg == "hello"

    def test_subscribe_nonexistent_channel(self):
        mgr = ChannelManager()
        with pytest.raises(KeyError):
            mgr.subscribe("nonexistent", "c1")

    def test_publish_nonexistent_channel(self):
        mgr = ChannelManager()
        with pytest.raises(KeyError):
            mgr.publish("nonexistent", "test")

    def test_multiple_subscribers(self):
        mgr = ChannelManager()
        mgr.create_channel("ch")
        sub1 = mgr.subscribe("ch", "c1")
        sub2 = mgr.subscribe("ch", "c2")

        mgr.publish("ch", "broadcast")
        assert sub1.try_recv() == "broadcast"
        assert sub2.try_recv() == "broadcast"

    def test_subscriber_drain(self):
        mgr = ChannelManager()
        mgr.create_channel("ch")
        sub = mgr.subscribe("ch", "c1")

        for i in range(5):
            mgr.publish("ch", f"msg-{i}")

        messages = sub.drain()
        assert len(messages) == 5
        assert messages[0] == "msg-0"
        assert messages[4] == "msg-4"

    def test_unsubscribe(self):
        mgr = ChannelManager()
        mgr.create_channel("ch")
        mgr.subscribe("ch", "c1")
        assert mgr.unsubscribe("ch", "c1") is True

    def test_get_stats(self):
        mgr = ChannelManager()
        mgr.create_channel("ch")
        sub = mgr.subscribe("ch", "c1")
        mgr.publish("ch", "m1")
        mgr.publish("ch", "m2")

        stats = mgr.get_stats("ch")
        assert stats.name == "ch"
        assert stats.subscriber_count == 1
        assert stats.total_messages == 2

    def test_list_channels(self):
        mgr = ChannelManager()
        mgr.create_channel("a")
        mgr.create_channel("b")
        mgr.create_channel("c")
        assert set(mgr.list_channels()) == {"a", "b", "c"}

    def test_get_subscribers(self):
        mgr = ChannelManager()
        mgr.create_channel("ch")
        mgr.subscribe("ch", "c1")
        mgr.subscribe("ch", "c2")
        subs = mgr.get_subscribers("ch")
        assert set(subs) == {"c1", "c2"}

    def test_publish_json(self):
        mgr = ChannelManager()
        mgr.create_channel("ch")
        sub = mgr.subscribe("ch", "c1")
        mgr.publish_json("ch", {"key": "value", "num": 42})

        msg = sub.try_recv()
        parsed = json.loads(msg)
        assert parsed["key"] == "value"
        assert parsed["num"] == 42

    def test_publish_to_topic(self):
        mgr = ChannelManager()
        mgr.create_channel("chat:general")
        mgr.create_channel("chat:random")
        mgr.create_channel("events:system")

        sub1 = mgr.subscribe("chat:general", "c1")
        sub2 = mgr.subscribe("chat:random", "c2")
        sub3 = mgr.subscribe("events:system", "c3")

        # Publish to topic pattern that matches chat:*
        mgr.publish_to_topic("chat:*", "hello chats")

        assert sub1.try_recv() == "hello chats"
        assert sub2.try_recv() == "hello chats"
        assert sub3.try_recv() is None  # events:system should not match

    def test_clear(self):
        mgr = ChannelManager()
        mgr.create_channel("a")
        mgr.create_channel("b")
        mgr.clear()
        assert mgr.channel_count() == 0

    def test_custom_buffer_size(self):
        mgr = ChannelManager()
        mgr.create_channel("small", buffer_size=2)
        sub = mgr.subscribe("small", "c1")
        # Should work fine
        mgr.publish("small", "m1")
        assert sub.try_recv() == "m1"

    def test_channel_with_metadata(self):
        mgr = ChannelManager()
        result = mgr.create_channel("ch", metadata={"desc": "test channel"})
        assert result is True

    def test_subscriber_properties(self):
        mgr = ChannelManager()
        mgr.create_channel("ch")
        sub = mgr.subscribe("ch", "c1")
        assert sub.channel_name == "ch"
        assert sub.client_id == "c1"
        assert sub.received_count == 0
        assert sub.missed_count == 0

    def test_subscriber_received_count(self):
        mgr = ChannelManager()
        mgr.create_channel("ch")
        sub = mgr.subscribe("ch", "c1")
        mgr.publish("ch", "m1")
        mgr.publish("ch", "m2")
        sub.try_recv()
        sub.try_recv()
        assert sub.received_count == 2

    def test_no_message_returns_none(self):
        mgr = ChannelManager()
        mgr.create_channel("ch")
        sub = mgr.subscribe("ch", "c1")
        assert sub.try_recv() is None

    def test_topic_matcher_property(self):
        mgr = ChannelManager()
        tm = mgr.topic_matcher
        assert tm is not None


# ============================================================================
# PresenceTracker Tests
# ============================================================================


class TestPresenceTracker:
    """Test presence tracking across channels."""

    def test_track_and_list(self):
        tracker = PresenceTracker()
        tracker.track("room", "alice", {"name": "Alice"})
        tracker.track("room", "bob", {"name": "Bob"})

        members = tracker.list("room")
        assert len(members) == 2
        ids = {m.client_id for m in members}
        assert ids == {"alice", "bob"}

    def test_track_returns_presence_info(self):
        tracker = PresenceTracker()
        info = tracker.track("room", "alice", {"name": "Alice"})
        assert info.client_id == "alice"
        assert info.channel == "room"
        assert info.metadata["name"] == "Alice"
        assert info.joined_at > 0
        assert info.last_seen > 0

    def test_untrack(self):
        tracker = PresenceTracker()
        tracker.track("room", "alice")
        assert tracker.untrack("room", "alice") is True
        assert tracker.count("room") == 0

    def test_untrack_nonexistent(self):
        tracker = PresenceTracker()
        assert tracker.untrack("room", "nobody") is False

    def test_untrack_all(self):
        tracker = PresenceTracker()
        tracker.track("room1", "alice")
        tracker.track("room2", "alice")
        tracker.track("room1", "bob")

        channels = tracker.untrack_all("alice")
        assert set(channels) == {"room1", "room2"}
        assert tracker.count("room1") == 1  # bob remains
        assert tracker.count("room2") == 0

    def test_update_metadata(self):
        tracker = PresenceTracker()
        tracker.track("room", "alice", {"status": "online"})
        updated = tracker.update("room", "alice", {"status": "away"})
        assert updated is True

        info = tracker.get("room", "alice")
        assert info.metadata["status"] == "away"

    def test_touch(self):
        tracker = PresenceTracker()
        tracker.track("room", "alice")
        time.sleep(0.01)
        old_info = tracker.get("room", "alice")
        tracker.touch("room", "alice")
        new_info = tracker.get("room", "alice")
        assert new_info.last_seen >= old_info.last_seen

    def test_get_specific_client(self):
        tracker = PresenceTracker()
        tracker.track("room", "alice", {"name": "Alice"})
        info = tracker.get("room", "alice")
        assert info is not None
        assert info.client_id == "alice"

    def test_get_nonexistent(self):
        tracker = PresenceTracker()
        assert tracker.get("room", "nobody") is None

    def test_count(self):
        tracker = PresenceTracker()
        tracker.track("room", "a")
        tracker.track("room", "b")
        tracker.track("room", "c")
        assert tracker.count("room") == 3

    def test_count_empty(self):
        tracker = PresenceTracker()
        assert tracker.count("nonexistent") == 0

    def test_flush_diff(self):
        tracker = PresenceTracker()
        tracker.track("room", "alice")
        tracker.track("room", "bob")

        diff = tracker.flush_diff("room")
        assert len(diff.joins) == 2
        assert len(diff.leaves) == 0
        assert diff.has_changes() is True

        # Second flush should be empty
        diff2 = tracker.flush_diff("room")
        assert len(diff2.joins) == 0
        assert diff2.has_changes() is False

    def test_flush_diff_with_leaves(self):
        tracker = PresenceTracker()
        tracker.track("room", "alice")
        tracker.flush_diff("room")  # clear pending

        tracker.untrack("room", "alice")
        diff = tracker.flush_diff("room")
        assert len(diff.leaves) == 1
        assert "alice" in diff.leaves

    def test_client_channels(self):
        tracker = PresenceTracker()
        tracker.track("room1", "alice")
        tracker.track("room2", "alice")
        channels = tracker.client_channels("alice")
        assert set(channels) == {"room1", "room2"}

    def test_active_channels(self):
        tracker = PresenceTracker()
        tracker.track("room1", "alice")
        tracker.track("room2", "bob")
        channels = tracker.active_channels()
        assert set(channels) == {"room1", "room2"}

    def test_total_clients(self):
        tracker = PresenceTracker()
        tracker.track("room1", "alice")
        tracker.track("room2", "bob")
        tracker.track("room1", "bob")
        assert tracker.total_clients() == 2

    def test_evict_stale(self):
        tracker = PresenceTracker()
        tracker.track("room", "alice")
        # evict anything older than 0 seconds (i.e., everything)
        time.sleep(0.01)
        evicted = tracker.evict_stale(0.001)
        assert len(evicted) >= 1

    def test_clear(self):
        tracker = PresenceTracker()
        tracker.track("room", "alice")
        tracker.clear()
        assert tracker.total_clients() == 0

    def test_list_as_dicts(self):
        tracker = PresenceTracker()
        tracker.track("room", "alice", {"name": "Alice"})
        dicts = tracker.list_as_dicts("room")
        assert len(dicts) == 1
        assert dicts[0]["client_id"] == "alice"
        assert dicts[0]["metadata"]["name"] == "Alice"
        assert "joined_at" in dicts[0]

    def test_diff_as_dict(self):
        tracker = PresenceTracker()
        tracker.track("room", "alice", {"name": "Alice"})
        d = tracker.diff_as_dict("room")
        assert len(d["joins"]) == 1
        assert d["joins"][0]["client_id"] == "alice"
        assert d["leaves"] == []


# ============================================================================
# RealtimeBroadcast Tests
# ============================================================================


class TestRealtimeBroadcast:
    """Test backpressure-aware broadcast."""

    def test_create_and_send(self):
        bc = RealtimeBroadcast()
        bc.create("ch")
        rx = bc.subscribe("ch")
        count = bc.send("ch", "hello")
        assert count == 1
        assert rx.try_recv() == "hello"

    def test_create_duplicate(self):
        bc = RealtimeBroadcast()
        bc.create("ch")
        assert bc.create("ch") is False

    def test_subscribe_nonexistent(self):
        bc = RealtimeBroadcast()
        with pytest.raises(KeyError):
            bc.subscribe("nonexistent")

    def test_send_nonexistent(self):
        bc = RealtimeBroadcast()
        with pytest.raises(KeyError):
            bc.send("nonexistent", "msg")

    def test_multiple_subscribers(self):
        bc = RealtimeBroadcast()
        bc.create("ch")
        rx1 = bc.subscribe("ch")
        rx2 = bc.subscribe("ch")
        count = bc.send("ch", "test")
        assert count == 2
        assert rx1.try_recv() == "test"
        assert rx2.try_recv() == "test"

    def test_subscriber_drain(self):
        bc = RealtimeBroadcast()
        bc.create("ch")
        rx = bc.subscribe("ch")
        for i in range(3):
            bc.send("ch", f"m{i}")
        msgs = rx.drain()
        assert msgs == ["m0", "m1", "m2"]

    def test_dedup_enabled(self):
        bc = RealtimeBroadcast()
        config = BroadcastConfig(
            buffer_size=64, dedup_enabled=True, dedup_window=100
        )
        bc.create("ch", config)
        rx = bc.subscribe("ch")

        bc.send("ch", "msg1", message_id="id-1")
        bc.send("ch", "msg1-dup", message_id="id-1")  # duplicate
        bc.send("ch", "msg2", message_id="id-2")

        msgs = rx.drain()
        assert len(msgs) == 2
        assert msgs[0] == "msg1"
        assert msgs[1] == "msg2"

    def test_dedup_stats(self):
        bc = RealtimeBroadcast()
        config = BroadcastConfig(buffer_size=64, dedup_enabled=True)
        bc.create("ch", config)
        rx = bc.subscribe("ch")

        bc.send("ch", "m1", message_id="a")
        bc.send("ch", "m2", message_id="a")  # dup
        bc.send("ch", "m3", message_id="b")

        stats = bc.stats("ch")
        assert stats.total_sent == 2
        assert stats.total_deduped == 1

    def test_send_json(self):
        bc = RealtimeBroadcast()
        bc.create("ch")
        rx = bc.subscribe("ch")
        bc.send_json("ch", {"key": "val"})
        msg = rx.try_recv()
        assert json.loads(msg) == {"key": "val"}

    def test_send_many(self):
        bc = RealtimeBroadcast()
        bc.create("a")
        bc.create("b")
        rx_a = bc.subscribe("a")
        rx_b = bc.subscribe("b")

        results = bc.send_many(["a", "b"], "broadcast")
        assert results["a"] == 1
        assert results["b"] == 1
        assert rx_a.try_recv() == "broadcast"
        assert rx_b.try_recv() == "broadcast"

    def test_global_stats(self):
        bc = RealtimeBroadcast()
        bc.create("a")
        bc.create("b")
        rx = bc.subscribe("a")
        bc.send("a", "m1")

        stats = bc.global_stats()
        assert stats.channel_count == 2
        assert stats.total_sent >= 1

    def test_list_channels(self):
        bc = RealtimeBroadcast()
        bc.create("a")
        bc.create("b")
        assert set(bc.list_channels()) == {"a", "b"}

    def test_has_channel(self):
        bc = RealtimeBroadcast()
        bc.create("test")
        assert bc.has_channel("test") is True
        assert bc.has_channel("nope") is False

    def test_remove(self):
        bc = RealtimeBroadcast()
        bc.create("test")
        assert bc.remove("test") is True
        assert bc.has_channel("test") is False

    def test_clear(self):
        bc = RealtimeBroadcast()
        bc.create("a")
        bc.create("b")
        bc.clear()
        assert bc.list_channels() == []

    def test_subscriber_properties(self):
        bc = RealtimeBroadcast()
        bc.create("ch")
        rx = bc.subscribe("ch")
        assert rx.channel_name == "ch"
        assert rx.received_count == 0
        assert rx.lagged_count == 0

    def test_error_policy_no_subscribers(self):
        bc = RealtimeBroadcast()
        config = BroadcastConfig(policy=BackpressurePolicy.Error)
        bc.create("ch", config)
        # No subscribers → should raise
        with pytest.raises(RuntimeError):
            bc.send("ch", "test")

    def test_drop_oldest_policy_no_subscribers(self):
        bc = RealtimeBroadcast()
        config = BroadcastConfig(policy=BackpressurePolicy.DropOldest)
        bc.create("ch", config)
        # No subscribers → should return 0, no error
        count = bc.send("ch", "test")
        assert count == 0

    def test_broadcast_config_defaults(self):
        config = BroadcastConfig()
        assert config.buffer_size == 256
        assert config.policy == BackpressurePolicy.DropOldest
        assert config.dedup_enabled is False
        assert config.dedup_window == 1000


# ============================================================================
# HeartbeatMonitor Tests
# ============================================================================


class TestHeartbeatMonitor:
    """Test heartbeat monitoring and SSE helpers."""

    def test_register_and_alive(self):
        hb = HeartbeatMonitor()
        hb.register("c1")
        assert hb.is_alive("c1") is True
        assert hb.client_count() == 1

    def test_unregister(self):
        hb = HeartbeatMonitor()
        hb.register("c1")
        assert hb.unregister("c1") is True
        assert hb.client_count() == 0

    def test_unregister_nonexistent(self):
        hb = HeartbeatMonitor()
        assert hb.unregister("nobody") is False

    def test_ping_pong(self):
        hb = HeartbeatMonitor()
        hb.register("c1")
        assert hb.ping("c1") is True
        assert hb.pong("c1") is True

    def test_ping_nonexistent(self):
        hb = HeartbeatMonitor()
        assert hb.ping("nobody") is False

    def test_pong_resets_retry_count(self):
        hb = HeartbeatMonitor(HeartbeatConfig(timeout_secs=0.001))
        hb.register("c1")
        time.sleep(0.01)
        hb.check_timeouts()
        assert hb.retry_count("c1") >= 1

        hb.pong("c1")
        assert hb.retry_count("c1") == 0

    def test_check_timeouts(self):
        hb = HeartbeatMonitor(HeartbeatConfig(timeout_secs=0.001))
        hb.register("c1")
        time.sleep(0.01)

        timed_out = hb.check_timeouts()
        assert "c1" in timed_out
        assert hb.is_timed_out("c1") is True

    def test_no_timeout_when_alive(self):
        hb = HeartbeatMonitor(HeartbeatConfig(timeout_secs=60))
        hb.register("c1")
        hb.pong("c1")
        timed_out = hb.check_timeouts()
        assert timed_out == []

    def test_nonexistent_is_timed_out(self):
        hb = HeartbeatMonitor()
        assert hb.is_timed_out("nobody") is True

    def test_nonexistent_is_not_alive(self):
        hb = HeartbeatMonitor()
        assert hb.is_alive("nobody") is False

    def test_get_dead_clients(self):
        hb = HeartbeatMonitor(HeartbeatConfig(timeout_secs=0.001, max_retries=0))
        hb.register("c1")
        time.sleep(0.01)
        hb.check_timeouts()  # triggers timeout, retry_count=1
        dead = hb.get_dead_clients()
        assert "c1" in dead

    def test_evict_dead(self):
        hb = HeartbeatMonitor(HeartbeatConfig(timeout_secs=0.001, max_retries=0))
        hb.register("c1")
        time.sleep(0.01)
        hb.check_timeouts()
        evicted = hb.evict_dead()
        assert "c1" in evicted
        assert hb.client_count() == 0

    def test_last_event_id(self):
        hb = HeartbeatMonitor()
        hb.register("c1", last_event_id="evt-42")
        assert hb.get_last_event_id("c1") == "evt-42"

        hb.set_last_event_id("c1", "evt-43")
        assert hb.get_last_event_id("c1") == "evt-43"

    def test_last_event_id_none(self):
        hb = HeartbeatMonitor()
        hb.register("c1")
        assert hb.get_last_event_id("c1") is None

    def test_clients_needing_ping(self):
        hb = HeartbeatMonitor(HeartbeatConfig(interval_secs=0.001))
        hb.register("c1")
        time.sleep(0.01)
        needs_ping = hb.clients_needing_ping()
        assert "c1" in needs_ping

    def test_sse_keepalive_comment(self):
        hb = HeartbeatMonitor()
        comment = hb.sse_keepalive_comment()
        assert comment == ": keepalive\n\n"

    def test_sse_retry_field(self):
        hb = HeartbeatMonitor(HeartbeatConfig(sse_retry_ms=5000))
        field = hb.sse_retry_field()
        assert field == "retry: 5000\n\n"

    def test_sse_heartbeat_event(self):
        hb = HeartbeatMonitor(HeartbeatConfig(sse_retry_ms=3000))
        event = hb.sse_heartbeat_event()
        assert "retry: 3000" in event
        assert ": heartbeat" in event

    def test_stats(self):
        hb = HeartbeatMonitor()
        hb.register("c1")
        hb.register("c2")
        hb.ping("c1")
        hb.pong("c1")

        stats = hb.stats()
        assert stats.monitored_clients == 2
        assert stats.total_pings == 1
        assert stats.total_pongs == 1

    def test_client_ids(self):
        hb = HeartbeatMonitor()
        hb.register("c1")
        hb.register("c2")
        assert set(hb.client_ids()) == {"c1", "c2"}

    def test_client_info(self):
        hb = HeartbeatMonitor()
        hb.register("c1")
        hb.set_last_event_id("c1", "evt-1")
        info = hb.client_info()
        assert "c1" in info
        assert info["c1"]["alive"] == "true"
        assert info["c1"]["last_event_id"] == "evt-1"

    def test_clear(self):
        hb = HeartbeatMonitor()
        hb.register("c1")
        hb.clear()
        assert hb.client_count() == 0

    def test_config_property(self):
        config = HeartbeatConfig(interval_secs=5, timeout_secs=15)
        hb = HeartbeatMonitor(config)
        assert hb.config.interval_secs == 5.0
        assert hb.config.timeout_secs == 15.0

    def test_make_sse_event(self):
        hb = HeartbeatMonitor(HeartbeatConfig(sse_retry_ms=2000))
        event = hb.make_sse_event("test data", event="ping", id="1")
        assert event.data == "test data"
        assert event.event == "ping"
        assert event.id == "1"
        assert event.retry == 2000

    def test_default_config(self):
        config = HeartbeatConfig()
        assert config.interval_secs == 30.0
        assert config.timeout_secs == 90.0
        assert config.max_retries == 5
        assert config.sse_retry_ms == 3000
        assert config.send_keepalive is True


# ============================================================================
# RealtimeHub Tests
# ============================================================================


class TestRealtimeHub:
    """Test the convenience hub wrapper."""

    def test_create_hub(self):
        hub = RealtimeHub()
        assert hub.channels.channel_count() == 0

    def test_create_channel_via_hub(self):
        hub = RealtimeHub()
        hub.create_channel("chat:general")
        assert hub.channels.has_channel("chat:general") is True

    def test_create_channel_with_broadcast(self):
        hub = RealtimeHub()
        hub.create_channel(
            "chat:general",
            broadcast_config=BroadcastConfig(buffer_size=64),
        )
        assert hub.channels.has_channel("chat:general") is True
        assert hub.broadcast.has_channel("chat:general") is True

    def test_join_and_publish(self):
        hub = RealtimeHub()
        hub.create_channel("room")

        sub = hub.join("room", "alice", {"name": "Alice"})
        assert hub.presence.count("room") == 1
        assert hub.heartbeat.is_alive("alice") is True

        hub.publish("room", "hello")
        assert sub.try_recv() == "hello"

    def test_leave(self):
        hub = RealtimeHub()
        hub.create_channel("room")
        hub.join("room", "alice")

        hub.leave("room", "alice")
        assert hub.presence.count("room") == 0

    def test_disconnect(self):
        hub = RealtimeHub()
        hub.create_channel("room1")
        hub.create_channel("room2")
        hub.join("room1", "alice")
        hub.join("room2", "alice")

        channels = hub.disconnect("alice")
        assert set(channels) == {"room1", "room2"}
        assert hub.presence.count("room1") == 0
        assert hub.presence.count("room2") == 0

    def test_publish_json(self):
        hub = RealtimeHub()
        hub.create_channel("ch")
        sub = hub.join("ch", "c1")
        hub.publish_json("ch", {"msg": "hello"})
        msg = sub.try_recv()
        assert json.loads(msg) == {"msg": "hello"}

    def test_get_presence(self):
        hub = RealtimeHub()
        hub.create_channel("room")
        hub.join("room", "alice", {"name": "Alice"})
        members = hub.get_presence("room")
        assert len(members) == 1
        assert members[0].client_id == "alice"

    def test_get_presence_diff(self):
        hub = RealtimeHub()
        hub.create_channel("room")
        hub.join("room", "alice", {"name": "Alice"})
        diff = hub.get_presence_diff("room")
        assert len(diff["joins"]) == 1
        assert diff["joins"][0]["client_id"] == "alice"

    def test_repr(self):
        hub = RealtimeHub()
        r = repr(hub)
        assert "RealtimeHub" in r
        assert "channels=0" in r

    def test_custom_heartbeat_config(self):
        config = HeartbeatConfig(interval_secs=5, timeout_secs=10)
        hub = RealtimeHub(heartbeat_config=config)
        assert hub.heartbeat.config.interval_secs == 5.0


# ============================================================================
# Async Tests
# ============================================================================


class TestAsyncFeatures:
    """Test async subscribe and heartbeat loops."""

    @pytest.mark.asyncio
    async def test_channel_subscribe_async(self):
        mgr = ChannelManager()
        mgr.create_channel("ch")
        received = []

        async def listener():
            sub = mgr.subscribe("ch", "c1")
            for _ in range(3):
                while True:
                    msg = sub.try_recv()
                    if msg is not None:
                        received.append(msg)
                        break
                    await asyncio.sleep(0.001)

        async def publisher():
            await asyncio.sleep(0.01)
            for i in range(3):
                mgr.publish("ch", f"msg-{i}")
                await asyncio.sleep(0.01)

        await asyncio.wait_for(
            asyncio.gather(listener(), publisher()),
            timeout=5.0,
        )
        assert received == ["msg-0", "msg-1", "msg-2"]

    @pytest.mark.asyncio
    async def test_broadcast_subscribe_async(self):
        bc = RealtimeBroadcast()
        bc.create("ch")
        received = []

        async def listener():
            rx = bc.subscribe("ch")
            for _ in range(2):
                while True:
                    msg = rx.try_recv()
                    if msg is not None:
                        received.append(msg)
                        break
                    await asyncio.sleep(0.001)

        async def publisher():
            await asyncio.sleep(0.01)
            bc.send("ch", "a")
            await asyncio.sleep(0.01)
            bc.send("ch", "b")

        await asyncio.wait_for(
            asyncio.gather(listener(), publisher()),
            timeout=5.0,
        )
        assert received == ["a", "b"]
