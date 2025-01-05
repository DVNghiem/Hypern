use bytes::Bytes;
use futures::{SinkExt, StreamExt};
use http_body_util::{BodyExt, Full};
use hyper::{body::Incoming, header, upgrade::Upgraded, Request, Response};
use hyper_util::rt::TokioIo;
use pyo3::{
    prelude::*,
    types::{PyDict, PyTuple},
};
use std::sync::{Arc, Mutex as StdMutex};
use tokio::sync::{mpsc, Mutex};
use tokio_tungstenite::WebSocketStream;
use tracing::{info, warn};
use tungstenite::Message;

use crate::types::body::{full, BoxBody};

#[derive(Debug, Clone)]
pub enum WebSocketMessage {
    Text(String),
    Binary(Vec<u8>),
    Close,
}

#[pyclass]
pub struct WebSocketSession {
    tx_send: StdMutex<mpsc::Sender<WebSocketMessage>>,
    is_closed: StdMutex<bool>,
}

impl WebSocketSession {
    pub fn from_sender(sender: mpsc::Sender<WebSocketMessage>) -> Self {
        WebSocketSession {
            tx_send: StdMutex::new(sender),
            is_closed: StdMutex::new(false),
        }
    }
}

fn convert_to_boxbody(res: Response<Full<Bytes>>) -> Response<BoxBody> {
    let (parts, body) = res.into_parts();
    let boxed_body = body.map_err(|never| match never {}).boxed();

    Response::from_parts(parts, boxed_body)
}

#[pymethods]
impl WebSocketSession {
    #[new]
    fn new() -> Self {
        let (tx_send, _) = mpsc::channel(100);
        WebSocketSession {
            tx_send: StdMutex::new(tx_send),
            is_closed: StdMutex::new(false),
        }
    }

    fn send(&self, message: &PyAny) -> PyResult<()> {
        if *self.is_closed.lock().unwrap() {
            return Err(PyErr::new::<pyo3::exceptions::PyConnectionError, _>(
                "WebSocket closed",
            ));
        }

        let msg = if let Ok(text) = message.extract::<String>() {
            WebSocketMessage::Text(text)
        } else if let Ok(bytes) = message.extract::<Vec<u8>>() {
            WebSocketMessage::Binary(bytes)
        } else {
            return Err(PyErr::new::<pyo3::exceptions::PyTypeError, _>(
                "Unsupported message type",
            ));
        };

        let tx = self.tx_send.lock().unwrap().clone();
        tokio::task::spawn_blocking(move || {
            let _ = tokio::runtime::Runtime::new().unwrap().block_on(async {
                tx.send(msg).await.map_err(|_| {
                    PyErr::new::<pyo3::exceptions::PyConnectionError, _>("Failed to send message")
                })
            });
        });
        Ok(())
    }

    fn close(&self) -> PyResult<()> {
        let mut is_closed = self.is_closed.lock().unwrap();
        *is_closed = true;
        let tx = self.tx_send.lock().unwrap().clone();

        tokio::runtime::Runtime::new().unwrap().block_on(async {
            tx.send(WebSocketMessage::Close).await.map_err(|_| {
                PyErr::new::<pyo3::exceptions::PyConnectionError, _>("Failed to close")
            })
        })
    }
}

pub async fn websocket_handler(
    handler: PyObject,
    mut req: Request<Incoming>,
) -> Result<Response<BoxBody>, Box<dyn std::error::Error>> {
    info!("Received request with headers: {:?}", req.headers());

    // Ensure all required headers are present and correct
    let upgrade_header = req
        .headers()
        .get(header::UPGRADE)
        .and_then(|h| h.to_str().ok())
        .map(|h| h.to_lowercase());

    let connection_header = req
        .headers()
        .get(header::CONNECTION)
        .and_then(|h| h.to_str().ok())
        .map(|h| h.to_lowercase());

    let websocket_key = req.headers().get(header::SEC_WEBSOCKET_KEY);

    let websocket_version = req.headers().get(header::SEC_WEBSOCKET_VERSION);

    // Validate all required headers
    if upgrade_header != Some("websocket".to_string())
        || !connection_header
            .clone()
            .map(|h| h.contains("upgrade"))
            .unwrap_or(false)
        || websocket_key.is_none()
        || websocket_version != Some(&header::HeaderValue::from_static("13"))
    {
        warn!(
            "Invalid WebSocket headers: upgrade={:?}, connection={:?}, key={:?}, version={:?}",
            upgrade_header, connection_header, websocket_key, websocket_version
        );
        return Ok(Response::new(full("Invalid WebSocket headers")));
    }

    // Add required response headers if missing
    if !req.headers().contains_key(header::SEC_WEBSOCKET_PROTOCOL) {
        req.headers_mut().insert(
            header::SEC_WEBSOCKET_PROTOCOL,
            header::HeaderValue::from_static("websocket"),
        );
    }

    if hyper_tungstenite::is_upgrade_request(&req) {
        let (response, websocket) = hyper_tungstenite::upgrade(&mut req, None)?;

        tokio::spawn(async move {
            match websocket.await {
                Ok(ws) => {
                    handle_socket(handler, ws).await;
                }
                Err(e) => {
                    eprintln!("Failed to establish WebSocket connection: {:?}", e);
                }
            }
        });

        Ok(convert_to_boxbody(response))
    } else {
        Ok(Response::new(full("Not a websocket request")))
    }
}

async fn handle_socket(python_handler: PyObject, ws: WebSocketStream<TokioIo<Upgraded>>) {
    let (tx_send, mut rx_send) = mpsc::channel(100);
    let (tx_recv, _) = mpsc::channel(100);

    let is_closed = Arc::new(Mutex::new(false));
    let is_closed_clone = is_closed.clone();

    let (mut write, mut read) = ws.split();

    tokio::spawn(async move {
        while let Some(msg) = rx_send.recv().await {
            let send_result = match msg {
                WebSocketMessage::Text(text) => write.send(Message::Text(text.into())).await,
                WebSocketMessage::Binary(bytes) => write.send(Message::Binary(bytes.into())).await,
                WebSocketMessage::Close => {
                    info!("Closing connection");
                    break;
                }
            };

            if send_result.is_err() {
                break;
            }
        }
    });

    tokio::spawn(async move {
        while let Some(msg) = read.next().await {
            match msg {
                Ok(Message::Text(text)) => {
                    let _ = Python::with_gil(|py| -> PyResult<PyObject> {
                        let session = WebSocketSession::from_sender(tx_send.clone());

                        let inspect = py.import("inspect")?;
                        let is_coroutine = inspect
                            .call_method1("iscoroutinefunction", (python_handler.as_ref(py),))?
                            .is_true()?;

                        let kwargs = PyDict::new(py);
                        kwargs.set_item("message", text.to_object(py))?;

                        let args = PyTuple::new(py, &[PyCell::new(py, session)?]);

                        if is_coroutine {
                            let asyncio = py.import("asyncio")?;
                            let coro = python_handler.call(py, args, Some(kwargs))?;
                            let loop_obj = asyncio.call_method0("new_event_loop")?;
                            let result = loop_obj.call_method1("run_until_complete", (coro,))?;
                            loop_obj.call_method0("close")?;
                            Ok(result.into())
                        } else {
                            Ok(python_handler.call(py, args, Some(kwargs))?)
                        }
                    });
                }
                Ok(Message::Binary(bytes)) => {
                    if tx_recv
                        .send(WebSocketMessage::Binary(bytes.to_vec()))
                        .await
                        .is_err()
                    {
                        break;
                    }
                }
                Ok(Message::Ping(ping)) => {
                    if tx_recv
                        .send(WebSocketMessage::Binary(ping.to_vec()))
                        .await
                        .is_err()
                    {
                        break;
                    }
                }
                Ok(Message::Close(_)) | Err(_) => {
                    let mut closed = is_closed_clone.lock().await;
                    *closed = true;
                    break;
                }
                _ => {}
            }
        }
    });
}
