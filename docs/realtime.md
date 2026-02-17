# Realtime: Channels, Presence, Broadcast & Heartbeat

Hypern provides a high-performance **realtime infrastructure** built in Rust, designed for
SSE and WebSocket patterns. It includes:

| Component | Purpose |
|-----------|---------|
| **ChannelManager** | Named pub/sub channels with topic-based routing |
| **PresenceTracker** | Track who is online in each channel |
| **RealtimeBroadcast** | Backpressure-aware fan-out with dedup |
| **HeartbeatMonitor** | Liveness detection + SSE auto-reconnect helpers |
| **RealtimeHub** | Convenience wrapper bundling all components |

All heavy lifting runs in Rust (lock-free data structures, tokio broadcast channels);
Python gets a clean, ergonomic API.

---

## Quick Start

```python
from hypern.realtime import RealtimeHub, BroadcastConfig

hub = RealtimeHub()

# Create a channel
hub.create_channel("chat:general")

# A user joins — subscribes + tracks presence + registers heartbeat
sub = hub.join("chat:general", "alice", {"name": "Alice", "status": "online"})

# Publish a message
hub.publish("chat:general", "Hello everyone!")

# Receive (non-blocking)
msg = sub.try_recv()  # "Hello everyone!"

# Get who's online
members = hub.get_presence("chat:general")

# When user disconnects
hub.disconnect("alice")
```

---

## Channel / Topic System

### ChannelManager

Manages named channels backed by Rust's `tokio::broadcast` for zero-copy fan-out.

```python
from hypern.realtime import ChannelManager

manager = ChannelManager(default_buffer_size=256)

# Create channels
manager.create_channel("chat:general")
manager.create_channel("chat:random")
manager.create_channel("events:system", buffer_size=1024)

# Subscribe
sub = manager.subscribe("chat:general", "user-1")

# Publish
receivers = manager.publish("chat:general", "Hello!")

# Receive messages
msg = sub.try_recv()       # Non-blocking, returns None if empty
messages = sub.drain()      # Drain all pending messages

# JSON helpers
manager.publish_json("chat:general", {"type": "message", "text": "Hi"})

# Stats
stats = manager.get_stats("chat:general")
print(f"Subscribers: {stats.subscriber_count}, Messages: {stats.total_messages}")

# Cleanup
manager.unsubscribe("chat:general", "user-1")
manager.remove_channel("chat:general")
```

### Topic Pattern Matching

Channels support pattern-based routing with wildcards:

| Pattern | Matches | Example |
|---------|---------|---------|
| `chat:general` | Exact match only | `chat:general` |
| `chat:*` | Any single segment | `chat:general`, `chat:random` |
| `events:#` | Any number of segments | `events:user:login`, `events:system:alert:critical` |

```python
from hypern.realtime import TopicMatcher

matcher = TopicMatcher()

# Subscribe to patterns
matcher.subscribe("chat:*", "user-1")      # All chat rooms
matcher.subscribe("events:#", "admin-1")    # All events (recursive)
matcher.subscribe("chat:general", "user-2") # Exact channel only

# Find who should receive a message
recipients = matcher.match_topic("chat:general")
# → ["user-1", "user-2"]

recipients = matcher.match_topic("events:user:login")
# → ["admin-1"]

# Static check
TopicMatcher.pattern_matches("chat:*", "chat:general")  # True
TopicMatcher.pattern_matches("chat:*", "events:foo")     # False
```

### Publishing to Topic Patterns

```python
manager = ChannelManager()
manager.create_channel("chat:general")
manager.create_channel("chat:random")

sub1 = manager.subscribe("chat:general", "u1")
sub2 = manager.subscribe("chat:random", "u2")

# Publish to all channels matching pattern
total = manager.publish_to_topic("chat:*", "Announcement!")
# Both sub1 and sub2 receive the message
```

### Async Subscribe

```python
import asyncio
from hypern.realtime import ChannelManager

manager = ChannelManager()
manager.create_channel("events")

async def handle_events():
    await manager.subscribe_async(
        "events", "worker-1",
        callback=lambda msg: print(f"Got: {msg}"),
        poll_interval=0.01,
    )

asyncio.create_task(handle_events())
```

---

## Presence Tracking

Track which clients are connected to each channel, with metadata and diff-based updates.

```python
from hypern.realtime import PresenceTracker

tracker = PresenceTracker()

# Track presence with metadata
tracker.track("room:lobby", "alice", {"name": "Alice", "status": "online"})
tracker.track("room:lobby", "bob", {"name": "Bob", "status": "away"})

# List members
members = tracker.list("room:lobby")
for m in members:
    print(f"{m.client_id}: {m.metadata}")

# Count
print(f"Members: {tracker.count('room:lobby')}")

# Get specific client
info = tracker.get("room:lobby", "alice")
print(f"Alice joined at: {info.joined_at}")
```

### Metadata Updates

```python
# Update a user's status
tracker.update("room:lobby", "alice", {"name": "Alice", "status": "away"})

# Touch last_seen (for heartbeat)
tracker.touch("room:lobby", "alice")
```

### Diff-Based Updates

Instead of sending the full member list on every change, use diffs for efficient updates:

```python
# After some joins/leaves have occurred:
diff = tracker.flush_diff("room:lobby")
if diff.has_changes():
    print(f"Joins: {[j.client_id for j in diff.joins]}")
    print(f"Leaves: {diff.leaves}")

# As a plain dict (ready for JSON broadcasting)
diff_dict = tracker.diff_as_dict("room:lobby")
# {"joins": [{"client_id": "alice", "metadata": {...}}], "leaves": ["bob"]}
```

### Disconnect & Cleanup

```python
# Remove from one channel
tracker.untrack("room:lobby", "alice")

# Remove from ALL channels (full disconnect)
channels_left = tracker.untrack_all("alice")
print(f"Alice left: {channels_left}")

# Evict stale presences (e.g., no heartbeat for 60s)
evicted = tracker.evict_stale(timeout_secs=60.0)
for channel, client_id in evicted:
    print(f"Evicted {client_id} from {channel}")
```

---

## Backpressure-Aware Broadcast

The broadcast system wraps `tokio::broadcast` with configurable backpressure policies
and optional message deduplication.

### Basic Usage

```python
from hypern.realtime import RealtimeBroadcast, BroadcastConfig, BackpressurePolicy

broadcast = RealtimeBroadcast()

# Create with default config
broadcast.create("notifications")

# Create with custom config
broadcast.create("alerts", BroadcastConfig(
    buffer_size=128,
    policy=BackpressurePolicy.DropOldest,  # or BackpressurePolicy.Error
    dedup_enabled=True,
    dedup_window=1000,
))

# Subscribe
rx = broadcast.subscribe("alerts")

# Send
count = broadcast.send("alerts", '{"type": "warning", "msg": "CPU high"}')
print(f"Delivered to {count} subscribers")

# Receive
msg = rx.try_recv()    # Non-blocking
msgs = rx.drain()       # Get all pending

# JSON helper
broadcast.send_json("alerts", {"type": "info", "msg": "Deployed v2.1"})
```

### Backpressure Policies

| Policy | Behavior |
|--------|----------|
| `BackpressurePolicy.DropOldest` | When no subscribers, silently drops. Lagging subscribers skip old messages. |
| `BackpressurePolicy.Error` | Raises `RuntimeError` when no subscribers are active. |

```python
# Error policy — fail loudly when nobody listens
broadcast.create("critical", BroadcastConfig(policy=BackpressurePolicy.Error))
rx = broadcast.subscribe("critical")
broadcast.send("critical", "important")  # OK, 1 subscriber

# If no subscribers, this will raise RuntimeError
```

### Message Deduplication

Prevent duplicate messages (useful for at-least-once delivery systems):

```python
broadcast.create("events", BroadcastConfig(
    dedup_enabled=True,
    dedup_window=1000,  # Track last 1000 message IDs
))

rx = broadcast.subscribe("events")

broadcast.send("events", "event A", message_id="evt-1")
broadcast.send("events", "event A (dup)", message_id="evt-1")  # Skipped!
broadcast.send("events", "event B", message_id="evt-2")

msgs = rx.drain()  # ["event A", "event B"]
```

### Multi-Channel Broadcast

```python
broadcast.create("channel-a")
broadcast.create("channel-b")

rx_a = broadcast.subscribe("channel-a")
rx_b = broadcast.subscribe("channel-b")

# Send to multiple channels at once
results = broadcast.send_many(["channel-a", "channel-b"], "Hello all!")
# {"channel-a": 1, "channel-b": 1}
```

### Statistics

```python
stats = broadcast.stats("alerts")
print(f"Sent: {stats.total_sent}, Dropped: {stats.total_dropped}, Deduped: {stats.total_deduped}")

global_stats = broadcast.global_stats()
print(f"Total channels: {global_stats.channel_count}, Total sent: {global_stats.total_sent}")
```

---

## Heartbeat / Auto-Reconnect

Server-side heartbeat monitoring for detecting dead connections, with SSE-specific helpers
for keepalive and client-side auto-reconnect.

### Basic Heartbeat

```python
from hypern.realtime import HeartbeatMonitor, HeartbeatConfig

monitor = HeartbeatMonitor(HeartbeatConfig(
    interval_secs=15.0,   # Ping every 15 seconds
    timeout_secs=45.0,    # Dead after 45 seconds without pong
    max_retries=3,        # Evict after 3 timeouts
    sse_retry_ms=3000,    # SSE client retries after 3s
    send_keepalive=True,  # Enable keepalive for SSE
))

# Register clients
monitor.register("client-1")
monitor.register("client-2", last_event_id="evt-42")  # Resume SSE stream

# Record heartbeat activity
monitor.ping("client-1")  # We sent a ping
monitor.pong("client-1")  # Client responded

# Check for timeouts
timed_out = monitor.check_timeouts()
for client_id in timed_out:
    print(f"Client {client_id} timed out!")

# Get dead clients (exceeded max_retries)
dead = monitor.get_dead_clients()

# Evict dead clients
evicted = monitor.evict_dead()

# Cleanup
monitor.unregister("client-1")
```

### SSE Auto-Reconnect Helpers

The heartbeat monitor generates SSE-compatible events for client-side reconnection:

```python
# Generate SSE keepalive comment (prevents proxy timeouts)
comment = monitor.sse_keepalive_comment()
# ": keepalive\n\n"

# Generate SSE retry field (tells client to reconnect after N ms)
retry = monitor.sse_retry_field()
# "retry: 3000\n\n"

# Generate full heartbeat event (retry + comment)
heartbeat = monitor.sse_heartbeat_event()
# "retry: 3000\n: heartbeat\n\n"

# Create SSE events with auto-retry configured
event = monitor.make_sse_event(
    data="Hello",
    event="message",
    id="evt-43",
)
# SSEEvent with retry=3000 automatically set
```

### Last-Event-ID Tracking (Resumable SSE)

```python
# When client connects with Last-Event-ID header:
monitor.register("client-1", last_event_id="evt-100")

# Get the resume point
last_id = monitor.get_last_event_id("client-1")
if last_id:
    # Send events since last_id
    send_events_since(last_id)

# Update as events are sent
monitor.set_last_event_id("client-1", "evt-105")
```

### Async Heartbeat Loop

Run a background heartbeat loop that automatically pings, detects timeouts, and evicts dead clients:

```python
import asyncio
from hypern.realtime import HeartbeatMonitor, HeartbeatConfig

monitor = HeartbeatMonitor(HeartbeatConfig(interval_secs=10, timeout_secs=30))

async def on_ping(client_id):
    # Send SSE keepalive or WebSocket ping
    print(f"Pinging {client_id}")

async def on_timeout(client_id):
    print(f"Timeout: {client_id}")

async def on_dead(client_id):
    print(f"Evicted: {client_id}")

# Run as background task
asyncio.create_task(
    monitor.run_heartbeat_loop(
        on_ping=on_ping,
        on_timeout=on_timeout,
        on_dead=on_dead,
    )
)
```

### Monitor Statistics

```python
stats = monitor.stats()
print(f"Monitoring {stats.monitored_clients} clients")
print(f"Pings: {stats.total_pings}, Pongs: {stats.total_pongs}")
print(f"Timeouts: {stats.total_timeouts}, Currently dead: {stats.timed_out_clients}")

# Detailed per-client info
info = monitor.client_info()
# {"client-1": {"alive": "true", "retries": "0", "last_pong_ago_secs": "2.5"}}
```

---

## RealtimeHub

A convenience wrapper that bundles all four components and provides coordinated
join/leave/disconnect operations.

```python
from hypern.realtime import RealtimeHub, HeartbeatConfig, BroadcastConfig

hub = RealtimeHub(
    channel_buffer_size=256,
    heartbeat_config=HeartbeatConfig(interval_secs=15, timeout_secs=45),
)

# Create a channel with broadcast support
hub.create_channel(
    "chat:general",
    broadcast_config=BroadcastConfig(buffer_size=128),
)

# Join = subscribe + track presence + register heartbeat
sub = hub.join("chat:general", "alice", {"name": "Alice"})

# Publish
hub.publish("chat:general", "Hello!")
hub.publish_json("chat:general", {"msg": "typed message"})

# Get presence
members = hub.get_presence("chat:general")
diff = hub.get_presence_diff("chat:general")

# Leave one channel
hub.leave("chat:general", "alice")

# Full disconnect (all channels)
channels_left = hub.disconnect("alice")
```

---

## Complete Chat Room Example

```python
from hypern import Hypern, Request, Response
from hypern.realtime import RealtimeHub, HeartbeatConfig, BroadcastConfig
import json, asyncio

app = Hypern()
hub = RealtimeHub(heartbeat_config=HeartbeatConfig(interval_secs=15))

# Create the chat room on startup
hub.create_channel("chat:main", broadcast_config=BroadcastConfig(buffer_size=256))


@app.get("/chat/join")
async def join_chat(request: Request, response: Response):
    user_id = request.query.get("user_id", "anonymous")
    sub = hub.join("chat:main", user_id, {"name": user_id})
    response.json({"status": "joined", "user_id": user_id})
    response.finish()


@app.post("/chat/send")
async def send_message(request: Request, response: Response):
    body = json.loads(request.body)
    user_id = body["user_id"]
    message = body["message"]
    hub.publish_json("chat:main", {
        "type": "message",
        "from": user_id,
        "text": message,
    })
    response.json({"status": "sent"})
    response.finish()


@app.get("/chat/members")
async def get_members(request: Request, response: Response):
    members = hub.presence.list_as_dicts("chat:main")
    response.json({"members": members})
    response.finish()


@app.get("/chat/leave")
async def leave_chat(request: Request, response: Response):
    user_id = request.query.get("user_id", "")
    hub.disconnect(user_id)
    response.json({"status": "left"})
    response.finish()
```

---

## SSE Stream with Heartbeat Example

```python
from hypern import Hypern, Request, Response, SSEEvent
from hypern.realtime import HeartbeatMonitor, HeartbeatConfig

app = Hypern()
monitor = HeartbeatMonitor(HeartbeatConfig(
    interval_secs=15,
    timeout_secs=45,
    sse_retry_ms=3000,
))


@app.get("/events")
async def sse_endpoint(request: Request, response: Response):
    client_id = request.query.get("client_id", "anon")
    last_event_id = request.headers.get("Last-Event-ID")

    # Register for heartbeat
    monitor.register(client_id, last_event_id=last_event_id)

    # Build SSE events
    events = []

    # If resuming, add events since last_event_id
    if last_event_id:
        # ... fetch missed events from your data store ...
        pass

    # Add the retry field so client auto-reconnects
    events.append(monitor.make_sse_event(
        data="connected",
        event="connect",
        id=f"evt-{client_id}-0",
    ))

    response.sse(events)
    response.finish()
```

---

## API Reference

### ChannelManager

| Method | Description |
|--------|-------------|
| `create_channel(name, buffer_size?, metadata?)` | Create a named channel |
| `remove_channel(name)` | Remove a channel |
| `has_channel(name)` | Check existence |
| `subscribe(channel, client_id)` → `Subscriber` | Subscribe to a channel |
| `unsubscribe(channel, client_id)` | Unsubscribe |
| `publish(channel, message)` → `int` | Publish, returns receiver count |
| `publish_json(channel, data)` → `int` | Publish JSON |
| `publish_to_topic(pattern, message)` → `int` | Publish to matching channels |
| `get_stats(channel)` → `ChannelStats` | Get channel stats |
| `list_channels()` → `list[str]` | List all channels |
| `get_subscribers(channel)` → `list[str]` | Get subscriber IDs |
| `subscribe_async(channel, client_id, callback)` | Async polling loop |

### Subscriber

| Method/Property | Description |
|-----------------|-------------|
| `try_recv()` → `str \| None` | Non-blocking receive |
| `drain()` → `list[str]` | Drain all pending messages |
| `channel_name` | Channel name |
| `client_id` | Client identifier |
| `received_count` | Messages received |
| `missed_count` | Messages missed (lag) |

### TopicMatcher

| Method | Description |
|--------|-------------|
| `subscribe(pattern, client_id)` | Register pattern subscription |
| `unsubscribe(pattern, client_id)` | Remove subscription |
| `unsubscribe_all(client_id)` | Remove all subscriptions |
| `match_topic(topic)` → `list[str]` | Find matching client IDs |
| `pattern_matches(pattern, topic)` | Static pattern check |

### PresenceTracker

| Method | Description |
|--------|-------------|
| `track(channel, client_id, metadata?)` → `PresenceInfo` | Track presence |
| `untrack(channel, client_id)` | Remove from channel |
| `untrack_all(client_id)` → `list[str]` | Remove from all channels |
| `update(channel, client_id, metadata)` | Update metadata |
| `touch(channel, client_id)` | Update last_seen |
| `list(channel)` → `list[PresenceInfo]` | List members |
| `get(channel, client_id)` → `PresenceInfo` | Get specific |
| `count(channel)` → `int` | Member count |
| `flush_diff(channel)` → `PresenceDiff` | Get incremental diff |
| `evict_stale(timeout_secs)` | Remove inactive |
| `list_as_dicts(channel)` | JSON-ready member list |
| `diff_as_dict(channel)` | JSON-ready diff |

### RealtimeBroadcast

| Method | Description |
|--------|-------------|
| `create(name, config?)` | Create broadcast channel |
| `remove(name)` | Remove channel |
| `subscribe(name)` → `BroadcastSubscriber` | Subscribe |
| `send(name, message, message_id?)` → `int` | Send message |
| `send_json(name, data, message_id?)` → `int` | Send JSON |
| `send_many(names, message)` → `dict` | Multi-channel send |
| `stats(name)` → `BroadcastStats` | Channel stats |
| `global_stats()` → `BroadcastStats` | All channels stats |

### HeartbeatMonitor

| Method | Description |
|--------|-------------|
| `register(client_id, last_event_id?)` | Start monitoring |
| `unregister(client_id)` | Stop monitoring |
| `ping(client_id)` | Record ping sent |
| `pong(client_id)` | Record pong received |
| `check_timeouts()` → `list[str]` | Get timed-out clients |
| `is_alive(client_id)` → `bool` | Check liveness |
| `evict_dead()` → `list[str]` | Remove dead clients |
| `set_last_event_id(client_id, id)` | Set SSE resume point |
| `get_last_event_id(client_id)` → `str` | Get SSE resume point |
| `sse_keepalive_comment()` → `str` | SSE keepalive string |
| `sse_retry_field()` → `str` | SSE retry field string |
| `sse_heartbeat_event()` → `str` | Full SSE heartbeat |
| `make_sse_event(data, event?, id?)` → `SSEEvent` | Create event with retry |
| `run_heartbeat_loop(on_ping?, on_timeout?, on_dead?)` | Async loop |
| `stats()` → `HeartbeatStats` | Monitor statistics |
