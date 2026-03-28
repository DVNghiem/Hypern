//! Rust-backed WebSocket support for Hypern.
//!
//! Provides `RustWebSocket` pyclass that wraps Axum's WebSocket with
//! send/receive methods exposed to Python.

use pyo3::prelude::*;
use pyo3::exceptions::{PyConnectionError, PyValueError};

use std::sync::Arc;
use parking_lot::Mutex;
use tokio::sync::mpsc;

/// Message types for WebSocket communication.
#[pyclass(eq, eq_int, skip_from_py_object)]
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum WsMessageType {
    Text,
    Binary,
    Ping,
    Pong,
    Close,
}

/// A WebSocket message with type and payload.
#[pyclass(skip_from_py_object)]
#[derive(Clone, Debug)]
pub struct WsMessage {
    #[pyo3(get)]
    pub msg_type: WsMessageType,
    #[pyo3(get)]
    pub data: Vec<u8>,
}

#[pymethods]
impl WsMessage {
    /// Get message data as UTF-8 text. Returns None for non-text messages.
    pub fn text(&self) -> Option<String> {
        String::from_utf8(self.data.clone()).ok()
    }

    /// Get message data as JSON (parsed from text).
    pub fn json(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let text = String::from_utf8(self.data.clone())
            .map_err(|_| PyValueError::new_err("Message is not valid UTF-8"))?;
        let json_mod = py.import("json")?;
        json_mod.call_method1("loads", (text,)).map(|o| o.unbind())
    }

    fn __repr__(&self) -> String {
        let preview = String::from_utf8_lossy(&self.data);
        let preview = if preview.len() > 50 {
            format!("{}...", &preview[..50])
        } else {
            preview.to_string()
        };
        format!("WsMessage({:?}, {:?})", self.msg_type, preview)
    }
}

/// Internal state for a single WebSocket connection.
struct WsInner {
    /// Sender half — write messages to the WebSocket.
    tx: Option<mpsc::UnboundedSender<WsOutgoing>>,
    /// Receiver half — read messages from the WebSocket.
    rx: Option<mpsc::UnboundedReceiver<WsMessage>>,
    /// Whether the connection has been closed.
    closed: bool,
}

#[allow(dead_code)]
pub enum WsOutgoing {
    Text(String),
    Binary(Vec<u8>),
    Ping(Vec<u8>),
    Close,
}

/// A Rust-backed WebSocket connection exposed to Python.
///
/// Created by the server when a WebSocket upgrade is accepted.
/// The Python handler receives this object and uses it to send/receive messages.
#[pyclass]
pub struct RustWebSocket {
    inner: Arc<Mutex<WsInner>>,
}

impl RustWebSocket {
    /// Create a new RustWebSocket from channel halves.
    pub fn new(
        tx: mpsc::UnboundedSender<WsOutgoing>,
        rx: mpsc::UnboundedReceiver<WsMessage>,
    ) -> Self {
        Self {
            inner: Arc::new(Mutex::new(WsInner {
                tx: Some(tx),
                rx: Some(rx),
                closed: false,
            })),
        }
    }
}

#[pymethods]
impl RustWebSocket {
    /// Send a text message.
    pub fn send_text(&self, text: &str) -> PyResult<()> {
        let inner = self.inner.lock();
        if inner.closed {
            return Err(PyConnectionError::new_err("WebSocket is closed"));
        }
        if let Some(tx) = &inner.tx {
            tx.send(WsOutgoing::Text(text.to_string()))
                .map_err(|_| PyConnectionError::new_err("WebSocket send channel closed"))?;
        }
        Ok(())
    }

    /// Send binary data.
    pub fn send_bytes(&self, data: &[u8]) -> PyResult<()> {
        let inner = self.inner.lock();
        if inner.closed {
            return Err(PyConnectionError::new_err("WebSocket is closed"));
        }
        if let Some(tx) = &inner.tx {
            tx.send(WsOutgoing::Binary(data.to_vec()))
                .map_err(|_| PyConnectionError::new_err("WebSocket send channel closed"))?;
        }
        Ok(())
    }

    /// Send a JSON-serializable value.
    pub fn send_json(&self, py: Python<'_>, value: Py<PyAny>) -> PyResult<()> {
        let json_mod = py.import("json")?;
        let text: String = json_mod.call_method1("dumps", (value,))?.extract()?;
        self.send_text(&text)
    }

    /// Send a ping frame.
    pub fn send_ping(&self, data: Option<&[u8]>) -> PyResult<()> {
        let inner = self.inner.lock();
        if inner.closed {
            return Err(PyConnectionError::new_err("WebSocket is closed"));
        }
        if let Some(tx) = &inner.tx {
            tx.send(WsOutgoing::Ping(data.unwrap_or_default().to_vec()))
                .map_err(|_| PyConnectionError::new_err("WebSocket send channel closed"))?;
        }
        Ok(())
    }

    /// Receive the next message (blocking). Returns None when the connection is closed.
    pub fn receive(&self) -> PyResult<Option<WsMessage>> {
        let mut inner = self.inner.lock();
        if inner.closed {
            return Ok(None);
        }
        if let Some(rx) = &mut inner.rx {
            match rx.try_recv() {
                Ok(msg) => Ok(Some(msg)),
                Err(mpsc::error::TryRecvError::Empty) => Ok(None),
                Err(mpsc::error::TryRecvError::Disconnected) => {
                    inner.closed = true;
                    Ok(None)
                }
            }
        } else {
            Ok(None)
        }
    }

    /// Receive a text message. Returns None on close.
    pub fn receive_text(&self) -> PyResult<Option<String>> {
        match self.receive()? {
            Some(msg) => Ok(msg.text()),
            None => Ok(None),
        }
    }

    /// Receive and parse JSON. Returns None on close.
    pub fn receive_json(&self, py: Python<'_>) -> PyResult<Option<Py<PyAny>>> {
        match self.receive()? {
            Some(msg) => msg.json(py).map(Some),
            None => Ok(None),
        }
    }

    /// Close the WebSocket connection.
    pub fn close(&self) -> PyResult<()> {
        let mut inner = self.inner.lock();
        if !inner.closed {
            if let Some(tx) = &inner.tx {
                let _ = tx.send(WsOutgoing::Close);
            }
            inner.closed = true;
            inner.tx = None;
            inner.rx = None;
        }
        Ok(())
    }

    /// Check if the WebSocket is closed.
    #[getter]
    pub fn is_closed(&self) -> bool {
        self.inner.lock().closed
    }

    fn __repr__(&self) -> String {
        let closed = self.inner.lock().closed;
        format!("RustWebSocket(closed={})", closed)
    }
}
