"""
WebSocket handler API for Hypern.

Provides a high-level interface for WebSocket connections with accept, send,
and receive semantics.

Since the Rust server core (Axum) handles the actual WebSocket upgrade at the
transport layer, this module provides a Python-level abstraction that:

1. Lets you define WebSocket handlers with ``@app.ws()`` or ``@router.ws()``.
2. Gives each handler a :class:`WebSocket` object with ``accept``, ``send``,
   ``receive``, and ``close`` methods.
3. Manages connection lifecycle and broadcasts through :class:`WebSocketRoom`.

Example:
    from hypern.websocket import WebSocket, WebSocketRoom

    room = WebSocketRoom()

    @app.ws("/chat")
    async def chat(ws: WebSocket):
        await ws.accept()
        room.join(ws)
        try:
            while True:
                msg = await ws.receive_text()
                room.broadcast(f"User: {msg}")
        except WebSocketDisconnect:
            room.leave(ws)
"""

from __future__ import annotations

import asyncio
import enum
import json
import uuid
from typing import Any, Callable, Dict, List, Optional, Set, Union


# ============================================================================
# WebSocket state
# ============================================================================


class WebSocketState(enum.Enum):
    """Connection state machine."""
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"
    DISCONNECTED = "disconnected"


class WebSocketDisconnect(Exception):
    """Raised when the remote end closes the connection."""

    def __init__(self, code: int = 1000, reason: str = ""):
        self.code = code
        self.reason = reason
        super().__init__(f"WebSocket disconnected: code={code} reason={reason}")


class WebSocketError(Exception):
    """General WebSocket error."""
    pass


# ============================================================================
# WebSocket message types
# ============================================================================


class WebSocketMessage:
    """
    Represents a single WebSocket message.

    Attributes:
        type: ``"text"`` or ``"bytes"``.
        data: The payload (``str`` or ``bytes``).
    """

    __slots__ = ("type", "data")

    def __init__(self, msg_type: str, data: Union[str, bytes]):
        self.type = msg_type
        self.data = data

    def json(self) -> Any:
        """Parse the payload as JSON (only for text messages)."""
        if self.type != "text":
            raise WebSocketError("Cannot parse binary message as JSON")
        return json.loads(self.data)

    def __repr__(self) -> str:
        preview = str(self.data)[:60]
        return f"WebSocketMessage(type={self.type!r}, data={preview!r})"


# ============================================================================
# WebSocket connection
# ============================================================================


class WebSocket:
    """
    High-level WebSocket connection object.

    Wraps an asyncio queue pair to communicate between the transport layer
    (Rust/Axum) and the Python handler.

    Lifecycle::

        CONNECTING  ─▶  accept()  ─▶  CONNECTED  ─▶  close()  ─▶  DISCONNECTED

    Args:
        id: Unique connection identifier (auto-generated if omitted).

    Example:
        @app.ws("/echo")
        async def echo(ws: WebSocket):
            await ws.accept()
            while True:
                msg = await ws.receive_text()
                await ws.send_text(f"echo: {msg}")
    """

    def __init__(self, id: Optional[str] = None):
        self.id: str = id or uuid.uuid4().hex
        self.state: WebSocketState = WebSocketState.CONNECTING
        self.path: str = ""
        self.headers: Dict[str, str] = {}
        self.query_params: Dict[str, str] = {}
        self.client_host: Optional[str] = None
        self.client_port: Optional[int] = None
        self.extra: Dict[str, Any] = {}

        # Internal queues
        self._recv_queue: asyncio.Queue[WebSocketMessage] = asyncio.Queue()
        self._send_queue: asyncio.Queue[Union[WebSocketMessage, None]] = asyncio.Queue()
        self._close_code: int = 1000
        self._close_reason: str = ""

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def accept(
        self,
        subprotocol: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        Accept the WebSocket handshake.

        Must be called before sending or receiving messages.

        Args:
            subprotocol: Optional subprotocol to negotiate.
            headers: Optional extra headers to include in the upgrade response.
        """
        if self.state != WebSocketState.CONNECTING:
            raise WebSocketError(f"Cannot accept: state is {self.state.value}")
        self.state = WebSocketState.CONNECTED
        self.extra["subprotocol"] = subprotocol
        if headers:
            self.extra["accept_headers"] = headers

    async def close(self, code: int = 1000, reason: str = "") -> None:
        """
        Initiate a graceful close.

        Args:
            code: WebSocket close code (default 1000 = normal).
            reason: Human-readable close reason.
        """
        if self.state in (WebSocketState.DISCONNECTING, WebSocketState.DISCONNECTED):
            return
        self.state = WebSocketState.DISCONNECTING
        self._close_code = code
        self._close_reason = reason
        # Signal the send-side that we're done
        await self._send_queue.put(None)
        self.state = WebSocketState.DISCONNECTED

    @property
    def is_connected(self) -> bool:
        return self.state == WebSocketState.CONNECTED

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def send(self, message: WebSocketMessage) -> None:
        """Send a :class:`WebSocketMessage`."""
        self._assert_connected("send")
        await self._send_queue.put(message)

    async def send_text(self, data: str) -> None:
        """Send a text message."""
        await self.send(WebSocketMessage("text", data))

    async def send_bytes(self, data: bytes) -> None:
        """Send a binary message."""
        await self.send(WebSocketMessage("bytes", data))

    async def send_json(self, data: Any) -> None:
        """Send a JSON-serialised text message."""
        await self.send_text(json.dumps(data, separators=(",", ":")))

    # ------------------------------------------------------------------
    # Receiving
    # ------------------------------------------------------------------

    async def receive(self, timeout: Optional[float] = None) -> WebSocketMessage:
        """
        Receive the next message.

        Args:
            timeout: Optional timeout in seconds.

        Raises:
            WebSocketDisconnect: When the connection is closed.
            asyncio.TimeoutError: If a timeout is specified and exceeded.
        """
        self._assert_connected("receive")
        try:
            if timeout is not None:
                msg = await asyncio.wait_for(self._recv_queue.get(), timeout)
            else:
                msg = await self._recv_queue.get()
        except asyncio.TimeoutError:
            raise

        if msg is None:
            self.state = WebSocketState.DISCONNECTED
            raise WebSocketDisconnect(self._close_code, self._close_reason)
        return msg

    async def receive_text(self, timeout: Optional[float] = None) -> str:
        """Receive a text message."""
        msg = await self.receive(timeout)
        if msg.type != "text":
            raise WebSocketError(f"Expected text message, got {msg.type}")
        return msg.data

    async def receive_bytes(self, timeout: Optional[float] = None) -> bytes:
        """Receive a binary message."""
        msg = await self.receive(timeout)
        if msg.type != "bytes":
            raise WebSocketError(f"Expected binary message, got {msg.type}")
        return msg.data

    async def receive_json(self, timeout: Optional[float] = None) -> Any:
        """Receive and parse a JSON text message."""
        text = await self.receive_text(timeout)
        return json.loads(text)

    # ------------------------------------------------------------------
    # Transport helpers (called by the Rust bridge)
    # ------------------------------------------------------------------

    def feed_message(self, msg_type: str, data: Union[str, bytes]) -> None:
        """
        Push a message from the transport layer into the receive queue.

        This is called by the Rust/Axum integration, not by user code.
        """
        self._recv_queue.put_nowait(WebSocketMessage(msg_type, data))

    def feed_disconnect(self, code: int = 1000, reason: str = "") -> None:
        """Signal a disconnect from the transport side."""
        self._close_code = code
        self._close_reason = reason
        self._recv_queue.put_nowait(None)

    async def drain_send_queue(self) -> Optional[WebSocketMessage]:
        """
        Pop the next outgoing message (used by the transport layer).

        Returns ``None`` when the connection is closing.
        """
        return await self._send_queue.get()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _assert_connected(self, action: str) -> None:
        if self.state != WebSocketState.CONNECTED:
            raise WebSocketError(
                f"Cannot {action}: WebSocket is {self.state.value}"
            )

    def __repr__(self) -> str:
        return f"<WebSocket id={self.id!r} state={self.state.value!r}>"


# ============================================================================
# WebSocket Room (pub/sub)
# ============================================================================


class WebSocketRoom:
    """
    A simple pub/sub room for broadcasting messages to connected WebSocket
    clients.

    Example:
        room = WebSocketRoom()

        @app.ws("/chat")
        async def chat(ws: WebSocket):
            await ws.accept()
            room.join(ws)
            try:
                while True:
                    msg = await ws.receive_text()
                    room.broadcast(f"User said: {msg}")
            except WebSocketDisconnect:
                room.leave(ws)
    """

    def __init__(self, name: str = "default"):
        self.name = name
        self._connections: Dict[str, WebSocket] = {}

    @property
    def size(self) -> int:
        """Number of active connections."""
        return len(self._connections)

    def join(self, ws: WebSocket) -> None:
        """Add a WebSocket to the room."""
        self._connections[ws.id] = ws

    def leave(self, ws: WebSocket) -> None:
        """Remove a WebSocket from the room."""
        self._connections.pop(ws.id, None)

    def broadcast(self, data: str, exclude: Optional[Set[str]] = None) -> None:
        """
        Broadcast a text message to all connections.

        Args:
            data: The text payload.
            exclude: Optional set of connection IDs to skip.
        """
        exclude = exclude or set()
        msg = WebSocketMessage("text", data)
        for cid, ws in list(self._connections.items()):
            if cid in exclude:
                continue
            if ws.is_connected:
                ws._send_queue.put_nowait(msg)

    def broadcast_json(self, data: Any, exclude: Optional[Set[str]] = None) -> None:
        """Broadcast a JSON payload."""
        self.broadcast(json.dumps(data, separators=(",", ":")), exclude)

    def broadcast_bytes(self, data: bytes, exclude: Optional[Set[str]] = None) -> None:
        """Broadcast binary data."""
        exclude = exclude or set()
        msg = WebSocketMessage("bytes", data)
        for cid, ws in list(self._connections.items()):
            if cid in exclude:
                continue
            if ws.is_connected:
                ws._send_queue.put_nowait(msg)

    async def close_all(self, code: int = 1000, reason: str = "") -> None:
        """Close all connections in the room."""
        for ws in list(self._connections.values()):
            try:
                await ws.close(code, reason)
            except Exception:
                pass
        self._connections.clear()

    def get_connections(self) -> List[WebSocket]:
        """Get all active connections."""
        return [ws for ws in self._connections.values() if ws.is_connected]


# ============================================================================
# WebSocket Route Registry
# ============================================================================


class WebSocketRoute:
    """Represents a registered WebSocket route."""

    def __init__(self, path: str, handler: Callable, **options):
        self.path = path
        self.handler = handler
        self.options = options

    def __repr__(self) -> str:
        return f"<WebSocketRoute path={self.path!r}>"


class WebSocketRouter:
    """
    Registry for WebSocket routes.

    This is used internally by :class:`Hypern` and :class:`Router` to
    collect WebSocket handlers.

    Example:
        ws_router = WebSocketRouter()

        @ws_router.route("/chat")
        async def chat(ws):
            await ws.accept()
            ...
    """

    def __init__(self):
        self._routes: List[WebSocketRoute] = []

    def route(self, path: str, **options) -> Callable:
        """Decorator to register a WebSocket handler."""
        def decorator(handler: Callable) -> Callable:
            self._routes.append(WebSocketRoute(path, handler, **options))
            return handler
        return decorator

    def add_route(self, path: str, handler: Callable, **options) -> None:
        """Register a WebSocket handler programmatically."""
        self._routes.append(WebSocketRoute(path, handler, **options))

    def get_routes(self) -> List[WebSocketRoute]:
        """Return all registered routes."""
        return list(self._routes)

    def get_handler(self, path: str) -> Optional[Callable]:
        """Look up the handler for a given path."""
        for route in self._routes:
            if route.path == path:
                return route.handler
        return None


__all__ = [
    "WebSocket",
    "WebSocketState",
    "WebSocketMessage",
    "WebSocketDisconnect",
    "WebSocketError",
    "WebSocketRoom",
    "WebSocketRoute",
    "WebSocketRouter",
]
