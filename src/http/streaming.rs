use std::pin::Pin;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::task::{Context, Poll};

use bytes::Bytes;
use futures_core::Stream;
use pyo3::prelude::*;
use tokio::sync::mpsc::{self, Receiver, Sender};

use crate::memory::arena::with_arena;

/// SSE Event structure
#[pyclass(from_py_object)]
#[derive(Clone, Debug)]
pub struct SSEEvent {
    /// Event ID (optional)
    #[pyo3(get, set)]
    pub id: Option<String>,
    /// Event type/name (optional)
    #[pyo3(get, set)]
    pub event: Option<String>,
    /// Event data (required)
    #[pyo3(get, set)]
    pub data: String,
    /// Retry timeout in milliseconds (optional)
    #[pyo3(get, set)]
    pub retry: Option<u64>,
}

#[pymethods]
impl SSEEvent {
    #[new]
    #[pyo3(signature = (data, id=None, event=None, retry=None))]
    pub fn new(
        data: String,
        id: Option<String>,
        event: Option<String>,
        retry: Option<u64>,
    ) -> Self {
        Self {
            id,
            event,
            data,
            retry,
        }
    }

    /// Format as SSE wire format
    pub fn format(&self) -> String {
        let mut output = String::with_capacity(self.data.len() + 50);

        if let Some(ref id) = self.id {
            output.push_str("id: ");
            output.push_str(id);
            output.push('\n');
        }

        if let Some(ref event) = self.event {
            output.push_str("event: ");
            output.push_str(event);
            output.push('\n');
        }

        if let Some(retry) = self.retry {
            output.push_str("retry: ");
            output.push_str(&retry.to_string());
            output.push('\n');
        }

        // Data can be multiline - each line needs "data: " prefix
        for line in self.data.lines() {
            output.push_str("data: ");
            output.push_str(line);
            output.push('\n');
        }

        output.push('\n'); // End of event
        output
    }

    pub fn to_bytes(&self) -> Vec<u8> {
        self.format().into_bytes()
    }
}

impl SSEEvent {
    /// Create a comment event (for keepalive)
    pub fn comment(text: &str) -> String {
        format!(": {}\n\n", text)
    }

    /// Create a simple data event
    pub fn data(data: impl Into<String>) -> Self {
        Self {
            id: None,
            event: None,
            data: data.into(),
            retry: None,
        }
    }

    /// Create a named event
    pub fn named(event: impl Into<String>, data: impl Into<String>) -> Self {
        Self {
            id: None,
            event: Some(event.into()),
            data: data.into(),
            retry: None,
        }
    }
}

/// SSE Stream for sending events
#[pyclass(from_py_object)]
pub struct SSEStream {
    sender: Sender<Bytes>,
    closed: Arc<AtomicBool>,
    event_count: AtomicU64,
    /// The SSE body for this stream (kept for proper ownership)
    #[pyo3(get)]
    body_handle: Option<usize>,
}

impl Clone for SSEStream {
    fn clone(&self) -> Self {
        Self {
            sender: self.sender.clone(),
            closed: self.closed.clone(),
            event_count: AtomicU64::new(self.event_count.load(Ordering::SeqCst)),
            body_handle: self.body_handle,
        }
    }
}

#[pymethods]
impl SSEStream {
    /// Create a new SSE stream
    #[new]
    #[pyo3(signature = (buffer_size=100))]
    pub fn py_new(buffer_size: usize) -> Self {
        let (sender, _receiver) = mpsc::channel(buffer_size);
        let closed = Arc::new(AtomicBool::new(false));

        Self {
            sender,
            closed,
            event_count: AtomicU64::new(0),
            body_handle: None,
        }
    }

    /// Send an SSE event
    pub fn send(&self, event: &SSEEvent) -> PyResult<bool> {
        if self.closed.load(Ordering::SeqCst) {
            return Ok(false);
        }

        let bytes = Bytes::from(event.to_bytes());
        match self.sender.try_send(bytes) {
            Ok(_) => {
                self.event_count.fetch_add(1, Ordering::SeqCst);
                Ok(true)
            }
            Err(_) => Ok(false),
        }
    }

    /// Send raw data as an event
    pub fn send_data(&self, data: &str) -> PyResult<bool> {
        let event = SSEEvent::data(data);
        self.send(&event)
    }

    /// Send a named event
    pub fn send_event(&self, event_name: &str, data: &str) -> PyResult<bool> {
        let event = SSEEvent::named(event_name, data);
        self.send(&event)
    }

    /// Send a keepalive comment
    pub fn keepalive(&self) -> PyResult<bool> {
        if self.closed.load(Ordering::SeqCst) {
            return Ok(false);
        }

        let comment = SSEEvent::comment("keepalive");
        let bytes = Bytes::from(comment);
        match self.sender.try_send(bytes) {
            Ok(_) => Ok(true),
            Err(_) => Ok(false),
        }
    }

    /// Close the stream
    pub fn close(&self) {
        self.closed.store(true, Ordering::SeqCst);
    }

    /// Check if stream is closed
    pub fn is_closed(&self) -> bool {
        self.closed.load(Ordering::SeqCst)
    }

    /// Get event count
    pub fn event_count(&self) -> u64 {
        self.event_count.load(Ordering::SeqCst)
    }
}

/// SSE Response body that implements Stream
pub struct SSEBody {
    receiver: Receiver<Bytes>,
    closed: Arc<AtomicBool>,
}

impl SSEBody {
    pub fn new(buffer_size: usize) -> (SSEStream, Self) {
        let (sender, receiver) = mpsc::channel(buffer_size);
        let closed = Arc::new(AtomicBool::new(false));

        let stream = SSEStream {
            sender,
            closed: closed.clone(),
            event_count: AtomicU64::new(0),
            body_handle: None,
        };

        let body = Self { receiver, closed };

        (stream, body)
    }
}

impl Stream for SSEBody {
    type Item = Result<Bytes, std::io::Error>;

    fn poll_next(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Option<Self::Item>> {
        if self.closed.load(Ordering::SeqCst) {
            return Poll::Ready(None);
        }

        match Pin::new(&mut self.receiver).poll_recv(cx) {
            Poll::Ready(Some(bytes)) => Poll::Ready(Some(Ok(bytes))),
            Poll::Ready(None) => Poll::Ready(None),
            Poll::Pending => Poll::Pending,
        }
    }
}

/// Streaming response builder
#[pyclass(from_py_object)]
pub struct StreamingResponse {
    sender: Sender<Bytes>,
    closed: Arc<AtomicBool>,
    content_type: String,
}

impl Clone for StreamingResponse {
    fn clone(&self) -> Self {
        Self {
            sender: self.sender.clone(),
            closed: self.closed.clone(),
            content_type: self.content_type.clone(),
        }
    }
}

#[pymethods]
impl StreamingResponse {
    /// Create a new streaming response
    #[new]
    #[pyo3(signature = (content_type="application/octet-stream", buffer_size=100))]
    pub fn py_new(content_type: &str, buffer_size: usize) -> Self {
        let (sender, _receiver) = mpsc::channel(buffer_size);
        let closed = Arc::new(AtomicBool::new(false));

        Self {
            sender,
            closed,
            content_type: content_type.to_string(),
        }
    }

    /// Write bytes to the stream
    pub fn write(&self, data: Vec<u8>) -> PyResult<bool> {
        if self.closed.load(Ordering::SeqCst) {
            return Ok(false);
        }

        let bytes = Bytes::from(data);
        match self.sender.try_send(bytes) {
            Ok(_) => Ok(true),
            Err(_) => Ok(false),
        }
    }

    /// Write string to the stream
    pub fn write_str(&self, data: &str) -> PyResult<bool> {
        self.write(data.as_bytes().to_vec())
    }

    /// Write a line (with newline)
    pub fn write_line(&self, data: &str) -> PyResult<bool> {
        let mut line = data.to_string();
        line.push('\n');
        self.write(line.into_bytes())
    }

    /// Flush (no-op for now, but kept for API compatibility)
    pub fn flush(&self) -> PyResult<()> {
        Ok(())
    }

    /// Close the stream
    pub fn close(&self) {
        self.closed.store(true, Ordering::SeqCst);
    }

    /// Check if closed
    pub fn is_closed(&self) -> bool {
        self.closed.load(Ordering::SeqCst)
    }

    /// Get content type
    #[getter]
    pub fn content_type(&self) -> &str {
        &self.content_type
    }
}

/// Streaming body that implements Stream
pub struct StreamingBody {
    receiver: Receiver<Bytes>,
    closed: Arc<AtomicBool>,
}

impl StreamingBody {
    pub fn new(buffer_size: usize, content_type: impl Into<String>) -> (StreamingResponse, Self) {
        let (sender, receiver) = mpsc::channel(buffer_size);
        let closed = Arc::new(AtomicBool::new(false));

        let response = StreamingResponse {
            sender,
            closed: closed.clone(),
            content_type: content_type.into(),
        };

        let body = Self { receiver, closed };

        (response, body)
    }
}

impl Stream for StreamingBody {
    type Item = Result<Bytes, std::io::Error>;

    fn poll_next(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Option<Self::Item>> {
        if self.closed.load(Ordering::SeqCst) {
            return Poll::Ready(None);
        }

        match Pin::new(&mut self.receiver).poll_recv(cx) {
            Poll::Ready(Some(bytes)) => Poll::Ready(Some(Ok(bytes))),
            Poll::Ready(None) => Poll::Ready(None),
            Poll::Pending => Poll::Pending,
        }
    }
}

/// Create SSE response headers
pub fn sse_headers() -> Vec<(String, String)> {
    vec![
        ("Content-Type".to_string(), "text/event-stream".to_string()),
        ("Cache-Control".to_string(), "no-cache".to_string()),
        ("Connection".to_string(), "keep-alive".to_string()),
        ("X-Accel-Buffering".to_string(), "no".to_string()),
    ]
}

/// Generator-based SSE stream that consumes Python iterators/generators
/// for memory-efficient event streaming.
///
/// This approach allows streaming millions of events without loading them
/// all into memory at once.
#[pyclass]
pub struct SSEGenerator {
    /// Indicates if the generator is exhausted
    exhausted: Arc<AtomicBool>,
    /// Event count for statistics
    event_count: AtomicU64,
}

#[pymethods]
impl SSEGenerator {
    #[new]
    pub fn new() -> Self {
        Self {
            exhausted: Arc::new(AtomicBool::new(false)),
            event_count: AtomicU64::new(0),
        }
    }

    /// Check if generator is exhausted
    pub fn is_exhausted(&self) -> bool {
        self.exhausted.load(Ordering::SeqCst)
    }

    /// Get total events processed
    pub fn event_count(&self) -> u64 {
        self.event_count.load(Ordering::SeqCst)
    }
}

impl Default for SSEGenerator {
    fn default() -> Self {
        Self::new()
    }
}

/// Converts a Python iterator/generator into SSE-formatted bytes.
/// Uses arena allocation for efficient string building.
///
/// # Arguments
/// * `py` - Python GIL token
/// * `iterator` - Python iterator yielding SSEEvent objects
///
/// # Returns
/// A Vec of formatted SSE bytes for each event in the iterator
pub fn collect_sse_from_generator(
    py: Python<'_>,
    iterator: &Bound<'_, PyAny>,
) -> PyResult<Vec<Bytes>> {
    let py_iter = iterator.try_iter()?;
    let mut events: Vec<Bytes> = Vec::new();

    for item in py_iter {
        let item = item?;

        // Try to extract as SSEEvent first
        if let Ok(event) = item.extract::<SSEEvent>() {
            // Use arena for efficient string formatting
            let formatted = with_arena(|arena| {
                let formatted_str = event.format();
                arena.alloc_str(&formatted_str).to_string()
            });
            events.push(Bytes::from(formatted));
        }
        // Try as dict with data/event/id/retry keys
        else if let Ok(dict) = item.cast::<pyo3::types::PyDict>() {
            let data = dict
                .get_item("data")?
                .map(|v| v.extract::<String>())
                .transpose()?
                .unwrap_or_default();
            let event_type = dict
                .get_item("event")?
                .map(|v| v.extract::<String>())
                .transpose()?;
            let id = dict
                .get_item("id")?
                .map(|v| v.extract::<String>())
                .transpose()?;
            let retry = dict
                .get_item("retry")?
                .map(|v| v.extract::<u64>())
                .transpose()?;

            let event = SSEEvent {
                id,
                event: event_type,
                data,
                retry,
            };
            events.push(Bytes::from(event.format()));
        }
        // Try as string (simple data event)
        else if let Ok(s) = item.extract::<String>() {
            let event = SSEEvent::data(s);
            events.push(Bytes::from(event.format()));
        }
        // Try extracting data attribute (duck typing)
        else if let Ok(data) = item.getattr("data") {
            let data_str = data.extract::<String>()?;
            let event_type = item
                .getattr("event")
                .ok()
                .and_then(|v| v.extract::<Option<String>>().ok())
                .flatten();
            let id = item
                .getattr("id")
                .ok()
                .and_then(|v| v.extract::<Option<String>>().ok())
                .flatten();
            let retry = item
                .getattr("retry")
                .ok()
                .and_then(|v| v.extract::<Option<u64>>().ok())
                .flatten();

            let event = SSEEvent {
                id,
                event: event_type,
                data: data_str,
                retry,
            };
            events.push(Bytes::from(event.format()));
        } else {
            // Last resort: convert to string
            let s = item.str()?.to_string();
            let event = SSEEvent::data(s);
            events.push(Bytes::from(event.format()));
        }

        // Allow Python to handle signals/cancellation periodically
        py.check_signals()?;
    }

    Ok(events)
}
