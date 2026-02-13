# Server-Sent Events (SSE) & Streaming

Hypern provides efficient SSE and streaming support powered by Rust's Tokio async runtime.

## Basic SSE

### Sending Events from a List

```python
from hypern import Hypern, SSEEvent

app = Hypern()

@app.get("/events")
def sse_events(req, res, ctx):
    # Create multiple SSE events
    events = [
        SSEEvent("Connected!", event="connect"),
        SSEEvent("Hello World", event="message", id="1"),
        SSEEvent("Goodbye", event="close", id="2"),
    ]
    
    # Send all events as SSE response
    res.sse(events)
```

### Single Event Response

```python
@app.get("/notification")
def single_notification(req, res, ctx):
    res.sse_event(
        data="New notification!",
        event="notification",
        id="notif-1"
    )
```

## Generator-Based Streaming (Recommended)

For large or continuous event streams, use generator-based streaming for memory efficiency:

```python
from hypern import SSEEvent

@app.get("/stream")
def stream_events(req, res, ctx):
    # Generator produces events on-demand
    def event_generator():
        for i in range(1000):
            yield SSEEvent(f"Event {i}", event="counter", id=str(i))
    
    # Stream events without loading all into memory
    res.sse_stream(event_generator())
```

### Generator Types

The `sse_stream` method accepts various generator outputs:

```python
@app.get("/flexible-stream")
def flexible_stream(req, res, ctx):
    def generator():
        # Yield SSEEvent objects
        yield SSEEvent("Event 1", event="type1")
        
        # Yield dictionaries
        yield {"data": "Event 2", "event": "type2", "id": "2"}
        
        # Yield plain strings (becomes data-only event)
        yield "Simple message"
        
        # Any object with a 'data' attribute
        class CustomEvent:
            data = "Custom event"
            event = "custom"
        yield CustomEvent()
    
    res.sse_stream(generator())
```

### Real-Time Data Streaming

```python
@app.get("/live-data")
def live_data(req, res, ctx):
    def data_generator():
        import time
        
        for i in range(100):
            # Simulate real-time data
            data = {
                "timestamp": time.time(),
                "value": i * 1.5,
                "sensor": "temp-1"
            }
            yield SSEEvent(
                json.dumps(data),
                event="sensor_reading",
                id=str(i)
            )
            time.sleep(0.1)  # 10 events per second
    
    res.sse_stream(data_generator())
```

## SSE Event Properties

```python
from hypern import SSEEvent

# Basic event (data only)
event = SSEEvent("Hello World")

# Named event
event = SSEEvent("User logged in", event="user_login")

# Event with ID (for client reconnection)
event = SSEEvent("Data update", id="12345", event="update")

# Event with retry (reconnection time in ms)
event = SSEEvent("Data", retry=5000)

# Full event
event = SSEEvent(
    "Full event data",
    id="evt-1",
    event="custom_event",
    retry=3000
)

# Get formatted SSE string
formatted = event.format()
# Output: "id: evt-1\nevent: custom_event\nretry: 3000\ndata: Full event data\n\n"

# Get as bytes
event_bytes = event.to_bytes()
```

## SSE Headers

Set SSE headers manually for custom streaming:

```python
@app.get("/custom-stream")
def custom_stream(req, res, ctx):
    # Set SSE headers
    res.sse_headers()
    
    # Build response body manually
    body = ""
    body += SSEEvent.comment("keepalive")  # SSE comment
    body += SSEEvent("Starting...", event="start").format()
    body += SSEEvent("Done!", event="end").format()
    
    res.send(body)
```

## Client-Side Usage

```javascript
// JavaScript client
const eventSource = new EventSource('/events');

// Listen to named events
eventSource.addEventListener('message', (e) => {
    console.log('Message:', e.data);
});

eventSource.addEventListener('notification', (e) => {
    console.log('Notification:', e.data);
});

// Handle errors
eventSource.onerror = (e) => {
    console.error('SSE Error:', e);
    eventSource.close();
};

// Handle connection open
eventSource.onopen = () => {
    console.log('Connected to SSE');
};
```

### Handling Reconnection

```javascript
const eventSource = new EventSource('/events');
let lastEventId = null;

eventSource.onmessage = (e) => {
    lastEventId = e.lastEventId;
    console.log('Event:', e.data);
};

eventSource.onerror = () => {
    // Reconnect with last event ID
    eventSource.close();
    
    setTimeout(() => {
        const newSource = new EventSource(`/events?lastEventId=${lastEventId}`);
        // ... setup handlers
    }, 1000);
};
```

## Streaming Response

For non-SSE streaming (binary data, large files):

```python
from hypern import StreamingResponse

@app.get("/download")
def download_large_file(req, res, ctx):
    def file_chunks():
        with open("large_file.bin", "rb") as f:
            while chunk := f.read(8192):
                yield chunk
    
    res.stream(file_chunks(), content_type="application/octet-stream")
```

## Performance Considerations

1. **Use Generators** - Generators stream data without loading everything into memory
2. **Batch Events** - For high-frequency data, consider batching multiple updates into single events
3. **Compression** - Enable compression middleware for text-based streams
4. **Keep-Alive** - Send periodic comments to keep connections alive through proxies

```python
@app.get("/efficient-stream")
def efficient_stream(req, res, ctx):
    def generator():
        import time
        last_keepalive = time.time()
        
        while True:
            # Send keepalive every 30 seconds
            if time.time() - last_keepalive > 30:
                yield SSEEvent.comment("keepalive")
                last_keepalive = time.time()
            
            # Check for new data
            data = get_new_data()  # Your data source
            if data:
                yield SSEEvent(json.dumps(data), event="update")
            
            time.sleep(0.1)
    
    res.sse_stream(generator())
```
