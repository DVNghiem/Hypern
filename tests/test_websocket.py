"""
Tests for Hypern WebSocket module.

These are unit tests that exercise the Python-side WebSocket abstraction
(queues, rooms, router) without requiring a live server.
"""

import asyncio
import json
import pytest

from hypern.websocket import (
    WebSocket,
    WebSocketState,
    WebSocketMessage,
    WebSocketDisconnect,
    WebSocketError,
    WebSocketRoom,
    WebSocketRoute,
    WebSocketRouter,
)


# Override autouse fixtures from conftest that require the test server
@pytest.fixture(autouse=True)
def reset_database():
    yield


# ============================================================================
# WebSocketMessage Tests
# ============================================================================


class TestWebSocketMessage:
    """Test the WebSocketMessage data class."""

    def test_text_message(self):
        msg = WebSocketMessage("text", "hello world")
        assert msg.type == "text"
        assert msg.data == "hello world"

    def test_bytes_message(self):
        msg = WebSocketMessage("bytes", b"\x00\x01")
        assert msg.type == "bytes"
        assert msg.data == b"\x00\x01"

    def test_json_parse(self):
        msg = WebSocketMessage("text", '{"key": "value", "num": 42}')
        parsed = msg.json()
        assert parsed == {"key": "value", "num": 42}

    def test_json_parse_invalid(self):
        msg = WebSocketMessage("text", "not json")
        with pytest.raises(Exception):
            msg.json()

    def test_json_on_binary_raises(self):
        msg = WebSocketMessage("bytes", b"\x00\x01")
        with pytest.raises(WebSocketError, match="binary"):
            msg.json()

    def test_repr(self):
        msg = WebSocketMessage("text", "hello")
        r = repr(msg)
        assert "text" in r
        assert "hello" in r


# ============================================================================
# WebSocket Lifecycle Tests
# ============================================================================


class TestWebSocket:
    """Test the core WebSocket accept/send/receive/close cycle."""

    @pytest.mark.asyncio
    async def test_initial_state(self):
        ws = WebSocket()
        assert ws.state == WebSocketState.CONNECTING

    @pytest.mark.asyncio
    async def test_has_id(self):
        ws = WebSocket()
        assert ws.id is not None and len(ws.id) > 0

    @pytest.mark.asyncio
    async def test_custom_id(self):
        ws = WebSocket(id="my-id")
        assert ws.id == "my-id"

    @pytest.mark.asyncio
    async def test_accept(self):
        ws = WebSocket()
        await ws.accept()
        assert ws.state == WebSocketState.CONNECTED
        assert ws.is_connected is True

    @pytest.mark.asyncio
    async def test_accept_twice_raises(self):
        ws = WebSocket()
        await ws.accept()
        with pytest.raises(WebSocketError):
            await ws.accept()

    @pytest.mark.asyncio
    async def test_send_before_accept_raises(self):
        ws = WebSocket()
        with pytest.raises(WebSocketError):
            await ws.send_text("hello")

    @pytest.mark.asyncio
    async def test_send_text(self):
        ws = WebSocket()
        await ws.accept()
        await ws.send_text("hello")
        item = ws._send_queue.get_nowait()
        assert isinstance(item, WebSocketMessage)
        assert item.type == "text"
        assert item.data == "hello"

    @pytest.mark.asyncio
    async def test_send_bytes(self):
        ws = WebSocket()
        await ws.accept()
        await ws.send_bytes(b"\x00\x01")
        item = ws._send_queue.get_nowait()
        assert isinstance(item, WebSocketMessage)
        assert item.type == "bytes"
        assert item.data == b"\x00\x01"

    @pytest.mark.asyncio
    async def test_send_json(self):
        ws = WebSocket()
        await ws.accept()
        await ws.send_json({"key": "val"})
        item = ws._send_queue.get_nowait()
        assert item.type == "text"
        assert json.loads(item.data) == {"key": "val"}

    @pytest.mark.asyncio
    async def test_receive_text(self):
        ws = WebSocket()
        await ws.accept()
        # Simulate inbound text message from the transport layer
        ws.feed_message("text", "hello from client")
        text = await asyncio.wait_for(ws.receive_text(), timeout=1.0)
        assert text == "hello from client"

    @pytest.mark.asyncio
    async def test_receive_bytes(self):
        ws = WebSocket()
        await ws.accept()
        ws.feed_message("bytes", b"\x00\x01\x02")
        data = await asyncio.wait_for(ws.receive_bytes(), timeout=1.0)
        assert data == b"\x00\x01\x02"

    @pytest.mark.asyncio
    async def test_receive_json(self):
        ws = WebSocket()
        await ws.accept()
        ws.feed_message("text", '{"a": 1}')
        obj = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
        assert obj == {"a": 1}

    @pytest.mark.asyncio
    async def test_close(self):
        ws = WebSocket()
        await ws.accept()
        await ws.close(code=1000, reason="normal")
        assert ws.state == WebSocketState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        """Closing twice should not raise."""
        ws = WebSocket()
        await ws.accept()
        await ws.close()
        await ws.close()  # should be no-op
        assert ws.state == WebSocketState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_send_after_close_raises(self):
        ws = WebSocket()
        await ws.accept()
        await ws.close()
        with pytest.raises(WebSocketError):
            await ws.send_text("data")

    @pytest.mark.asyncio
    async def test_feed_disconnect_causes_receive_error(self):
        """feed_disconnect enqueues a None sentinel; next receive raises."""
        ws = WebSocket()
        await ws.accept()
        ws.feed_disconnect(1001, "going away")
        with pytest.raises(WebSocketDisconnect) as exc_info:
            await asyncio.wait_for(ws.receive_text(), timeout=1.0)
        assert exc_info.value.code == 1001

    @pytest.mark.asyncio
    async def test_multiple_messages_ordered(self):
        """Messages should be received in order."""
        ws = WebSocket()
        await ws.accept()
        for i in range(5):
            ws.feed_message("text", f"msg-{i}")

        for i in range(5):
            text = await asyncio.wait_for(ws.receive_text(), timeout=1.0)
            assert text == f"msg-{i}"

    @pytest.mark.asyncio
    async def test_drain_send_queue(self):
        """drain_send_queue should return sent messages."""
        ws = WebSocket()
        await ws.accept()
        await ws.send_text("hello")
        msg = await asyncio.wait_for(ws.drain_send_queue(), timeout=1.0)
        assert msg.type == "text"
        assert msg.data == "hello"


# ============================================================================
# WebSocketRoom Tests
# ============================================================================


class TestWebSocketRoom:
    """Test room-based pub/sub management."""

    @pytest.mark.asyncio
    async def test_join_and_leave(self):
        room = WebSocketRoom("test-room")
        ws = WebSocket()
        await ws.accept()

        room.join(ws)
        assert room.size == 1

        room.leave(ws)
        assert room.size == 0

    @pytest.mark.asyncio
    async def test_leave_nonmember(self):
        """Leaving a room you're not in should not error."""
        room = WebSocketRoom("test")
        ws = WebSocket()
        room.leave(ws)  # should not raise

    @pytest.mark.asyncio
    async def test_broadcast(self):
        """Broadcast should enqueue a message for every member."""
        room = WebSocketRoom("chat")
        clients = []
        for _ in range(3):
            ws = WebSocket()
            await ws.accept()
            room.join(ws)
            clients.append(ws)

        # broadcast is synchronous
        room.broadcast("hello everyone")

        for ws in clients:
            item = ws._send_queue.get_nowait()
            assert isinstance(item, WebSocketMessage)
            assert item.type == "text"
            assert item.data == "hello everyone"

    @pytest.mark.asyncio
    async def test_broadcast_json(self):
        room = WebSocketRoom("room")
        ws = WebSocket()
        await ws.accept()
        room.join(ws)

        room.broadcast_json({"event": "ping"})
        item = ws._send_queue.get_nowait()
        assert item.type == "text"
        assert json.loads(item.data) == {"event": "ping"}

    @pytest.mark.asyncio
    async def test_broadcast_bytes(self):
        room = WebSocketRoom("room")
        ws = WebSocket()
        await ws.accept()
        room.join(ws)

        room.broadcast_bytes(b"\xff")
        item = ws._send_queue.get_nowait()
        assert item.type == "bytes"
        assert item.data == b"\xff"

    @pytest.mark.asyncio
    async def test_close_all(self):
        room = WebSocketRoom("room")
        clients = []
        for _ in range(3):
            ws = WebSocket()
            await ws.accept()
            room.join(ws)
            clients.append(ws)

        await room.close_all()
        for ws in clients:
            assert ws.state == WebSocketState.DISCONNECTED
        assert room.size == 0

    @pytest.mark.asyncio
    async def test_broadcast_skips_disconnected(self):
        room = WebSocketRoom("room")
        ws1 = WebSocket()
        await ws1.accept()
        ws2 = WebSocket()
        await ws2.accept()
        room.join(ws1)
        room.join(ws2)

        # Disconnect ws1
        await ws1.close()

        room.broadcast("msg")
        # ws2 should still get the message
        item = ws2._send_queue.get_nowait()
        assert item.type == "text"
        assert item.data == "msg"

    @pytest.mark.asyncio
    async def test_broadcast_with_exclude(self):
        room = WebSocketRoom("room")
        ws1 = WebSocket()
        await ws1.accept()
        ws2 = WebSocket()
        await ws2.accept()
        room.join(ws1)
        room.join(ws2)

        room.broadcast("msg", exclude={ws1.id})
        # ws1 should NOT get the message
        assert ws1._send_queue.empty()
        # ws2 should get it
        item = ws2._send_queue.get_nowait()
        assert item.data == "msg"

    @pytest.mark.asyncio
    async def test_get_connections(self):
        room = WebSocketRoom("room")
        ws1 = WebSocket()
        await ws1.accept()
        ws2 = WebSocket()
        await ws2.accept()
        room.join(ws1)
        room.join(ws2)

        conns = room.get_connections()
        assert len(conns) == 2


# ============================================================================
# WebSocketRouter Tests
# ============================================================================


class TestWebSocketRouter:
    """Test WebSocket route registration."""

    def test_add_route(self):
        router = WebSocketRouter()

        async def handler(ws):
            pass

        router.add_route("/ws/chat", handler)
        routes = router.get_routes()
        assert len(routes) == 1
        assert routes[0].path == "/ws/chat"
        assert routes[0].handler is handler

    def test_route_decorator(self):
        router = WebSocketRouter()

        @router.route("/ws/echo")
        async def echo(ws):
            pass

        routes = router.get_routes()
        assert len(routes) == 1
        assert routes[0].path == "/ws/echo"

    def test_get_handler(self):
        router = WebSocketRouter()

        async def handler(ws):
            pass

        router.add_route("/ws/chat", handler)
        h = router.get_handler("/ws/chat")
        assert h is handler

    def test_get_handler_nonexistent(self):
        router = WebSocketRouter()
        h = router.get_handler("/ws/nope")
        assert h is None

    def test_multiple_routes(self):
        router = WebSocketRouter()

        @router.route("/ws/a")
        async def a(ws):
            pass

        @router.route("/ws/b")
        async def b(ws):
            pass

        @router.route("/ws/c")
        async def c(ws):
            pass

        routes = router.get_routes()
        assert len(routes) == 3
        paths = {r.path for r in routes}
        assert paths == {"/ws/a", "/ws/b", "/ws/c"}
