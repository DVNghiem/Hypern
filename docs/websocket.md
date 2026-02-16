# WebSocket

Hypern provides a high-level WebSocket API with accept, send, receive, and close semantics. The API is modelled after familiar async patterns and integrates with the Rust (Axum) transport layer.

## Quick Start

```python
from hypern import Hypern
from hypern.websocket import WebSocket, WebSocketDisconnect

app = Hypern()

@app.ws("/echo")
async def echo(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            msg = await ws.receive_text()
            await ws.send_text(f"echo: {msg}")
    except WebSocketDisconnect:
        pass
```

## Connection Lifecycle

```
CONNECTING  ─▶  accept()  ─▶  CONNECTED  ─▶  close()  ─▶  DISCONNECTED
```

Every WebSocket handler receives a `WebSocket` object. You **must** call `await ws.accept()` before sending or receiving messages.

## Sending Messages

```python
# Text
await ws.send_text("Hello!")

# Binary
await ws.send_bytes(b"\x00\x01\x02")

# JSON (auto-serialized)
await ws.send_json({"event": "update", "data": [1, 2, 3]})
```

## Receiving Messages

```python
# Text
text = await ws.receive_text()

# Binary
data = await ws.receive_bytes()

# JSON (auto-parsed)
obj = await ws.receive_json()

# With timeout (raises asyncio.TimeoutError)
msg = await ws.receive_text(timeout=30.0)
```

## Closing Connections

```python
# Normal close
await ws.close()

# With close code and reason
await ws.close(code=1001, reason="Going away")
```

## Handling Disconnects

When the remote end closes the connection, `receive_*()` raises `WebSocketDisconnect`:

```python
from hypern.websocket import WebSocketDisconnect

@app.ws("/chat")
async def chat(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            msg = await ws.receive_text()
            await ws.send_text(msg)
    except WebSocketDisconnect as e:
        print(f"Client disconnected: code={e.code} reason={e.reason}")
```

## Connection Properties

| Property       | Type            | Description                         |
|----------------|-----------------|-------------------------------------|
| `ws.id`        | `str`           | Unique connection identifier        |
| `ws.state`     | `WebSocketState`| Current state (CONNECTING, etc.)    |
| `ws.is_connected`| `bool`        | Whether currently connected         |
| `ws.path`      | `str`           | Request path                        |
| `ws.headers`   | `dict`          | Upgrade request headers             |
| `ws.query_params`| `dict`        | Query string parameters             |
| `ws.client_host`| `str`          | Client IP address                   |

---

## Rooms (Pub/Sub)

The `WebSocketRoom` class provides simple pub/sub broadcasting:

```python
from hypern.websocket import WebSocket, WebSocketRoom, WebSocketDisconnect

chat_room = WebSocketRoom("chat")

@app.ws("/chat")
async def chat(ws: WebSocket):
    await ws.accept()
    chat_room.join(ws)
    try:
        while True:
            msg = await ws.receive_text()
            # Broadcast to everyone except the sender
            chat_room.broadcast(f"User {ws.id}: {msg}", exclude={ws.id})
    except WebSocketDisconnect:
        chat_room.leave(ws)
```

### Room API

| Method                     | Description                              |
|----------------------------|------------------------------------------|
| `room.join(ws)`            | Add a connection to the room             |
| `room.leave(ws)`           | Remove a connection from the room        |
| `room.broadcast(text)`     | Send text to all connected members       |
| `room.broadcast_json(obj)` | Send JSON to all members                 |
| `room.broadcast_bytes(b)`  | Send binary data to all members          |
| `room.close_all()`         | Close all connections and clear the room |
| `room.get_connections()`   | Get list of active connections           |
| `room.size`                | Number of connections in the room        |

### Excluding Connections

Pass an `exclude` set to skip specific connections during broadcast:

```python
room.broadcast("hello", exclude={sender_ws.id})
```

---

## WebSocket Router

For modular applications, use `WebSocketRouter` to organize handlers:

```python
from hypern.websocket import WebSocketRouter

ws_router = WebSocketRouter()

@ws_router.route("/ws/chat")
async def chat(ws):
    await ws.accept()
    ...

@ws_router.route("/ws/notifications")
async def notifications(ws):
    await ws.accept()
    ...

# Programmatic registration
async def echo(ws):
    await ws.accept()
    ...

ws_router.add_route("/ws/echo", echo)
```

### Looking Up Handlers

```python
handler = ws_router.get_handler("/ws/chat")
routes = ws_router.get_routes()  # List[WebSocketRoute]
```

---

## States

| State           | Description                                     |
|-----------------|-------------------------------------------------|
| `CONNECTING`    | Initial state, before `accept()`                |
| `CONNECTED`     | After `accept()`, ready for send/receive        |
| `DISCONNECTING` | Close initiated, draining queues                |
| `DISCONNECTED`  | Connection fully closed                         |

---

## Complete Chat Example

```python
from hypern import Hypern
from hypern.websocket import WebSocket, WebSocketRoom, WebSocketDisconnect

app = Hypern()
rooms = {}

def get_room(name: str) -> WebSocketRoom:
    if name not in rooms:
        rooms[name] = WebSocketRoom(name)
    return rooms[name]

@app.ws("/chat/:room_name")
async def chat(ws: WebSocket):
    room_name = ws.query_params.get("room", "general")
    room = get_room(room_name)

    await ws.accept()
    room.join(ws)
    room.broadcast(f"User {ws.id[:8]} joined", exclude={ws.id})

    try:
        while True:
            text = await ws.receive_text()
            room.broadcast(f"{ws.id[:8]}: {text}", exclude={ws.id})
    except WebSocketDisconnect:
        room.leave(ws)
        room.broadcast(f"User {ws.id[:8]} left")

if __name__ == "__main__":
    app.start(host="0.0.0.0", port=8000)
```
