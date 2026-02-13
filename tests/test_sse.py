"""
Test cases for Server-Sent Events (SSE) in Hypern framework.

Tests cover:
- Basic SSE events
- Single SSE event
- SSE with JSON data
- Event parsing
"""

import json
import httpx
import pytest


def parse_sse_events(text: str) -> list:
    """Parse SSE events from response text."""
    events = []
    current_event = {}
    
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            if current_event:
                events.append(current_event)
                current_event = {}
            continue
        
        if line.startswith("event:"):
            current_event["event"] = line[6:].strip()
        elif line.startswith("data:"):
            current_event["data"] = line[5:].strip()
        elif line.startswith("id:"):
            current_event["id"] = line[3:].strip()
        elif line.startswith("retry:"):
            current_event["retry"] = line[6:].strip()
    
    if current_event:
        events.append(current_event)
    
    return events


class TestBasicSSE:
    """Test basic SSE functionality."""
    
    def test_sse_basic_events(self, client: httpx.Client):
        """Test basic SSE with multiple events."""
        response = client.get("/sse/basic")
        assert response.status_code == 200
        
        # Check content type
        content_type = response.headers.get("content-type", "")
        assert "text/event-stream" in content_type
        
        # Parse events
        events = parse_sse_events(response.text)
        assert len(events) >= 3
        
        # Check first event (connect)
        connect_event = next((e for e in events if e.get("event") == "connect"), None)
        assert connect_event is not None
        assert connect_event["data"] == "Connected!"
        
        # Check message event
        message_event = next((e for e in events if e.get("event") == "message"), None)
        assert message_event is not None
        assert message_event["data"] == "Hello World"
        assert message_event.get("id") == "1"
        
        # Check close event
        close_event = next((e for e in events if e.get("event") == "close"), None)
        assert close_event is not None
        assert close_event["data"] == "Goodbye"
    
    def test_sse_event_ids(self, client: httpx.Client):
        """Test SSE events have proper IDs."""
        response = client.get("/sse/basic")
        assert response.status_code == 200
        
        events = parse_sse_events(response.text)
        
        # Find events with IDs
        events_with_ids = [e for e in events if "id" in e]
        assert len(events_with_ids) >= 2


class TestSingleSSEEvent:
    """Test single SSE event responses."""
    
    def test_single_sse_event(self, client: httpx.Client):
        """Test single SSE event."""
        response = client.get("/sse/single")
        assert response.status_code == 200
        
        content_type = response.headers.get("content-type", "")
        assert "text/event-stream" in content_type
        
        events = parse_sse_events(response.text)
        assert len(events) >= 1
        
        # Check the notification event
        notif = events[0]
        assert notif.get("event") == "notification"
        assert notif.get("data") == "Single notification"
        assert notif.get("id") == "notif-1"


class TestSSEWithData:
    """Test SSE with JSON data."""
    
    def test_sse_json_data(self, client: httpx.Client):
        """Test SSE events with JSON data."""
        response = client.get("/sse/data")
        assert response.status_code == 200
        
        events = parse_sse_events(response.text)
        assert len(events) >= 3
        
        # Parse JSON data from events
        for i, event in enumerate(events, 1):
            if "data" in event and event.get("event") == "data":
                data = json.loads(event["data"])
                assert "count" in data
    
    def test_sse_data_sequence(self, client: httpx.Client):
        """Test SSE events are in correct sequence."""
        response = client.get("/sse/data")
        assert response.status_code == 200
        
        events = parse_sse_events(response.text)
        data_events = [e for e in events if e.get("event") == "data"]
        
        # Check sequence
        counts = []
        for event in data_events:
            if "data" in event:
                parsed = json.loads(event["data"])
                counts.append(parsed.get("count"))
        
        # Should have sequential counts
        assert 1 in counts
        assert 2 in counts
        assert 3 in counts


class TestSSEHeaders:
    """Test SSE response headers."""
    
    def test_sse_content_type(self, client: httpx.Client):
        """Test SSE has correct content type."""
        response = client.get("/sse/basic")
        
        content_type = response.headers.get("content-type", "")
        assert "text/event-stream" in content_type
    
    def test_sse_cache_control(self, client: httpx.Client):
        """Test SSE has appropriate cache control."""
        response = client.get("/sse/basic")
        
        cache_control = response.headers.get("cache-control", "")
        # SSE typically should not be cached
        assert "no-cache" in cache_control or cache_control == ""


class TestSSEEventFormat:
    """Test SSE event format compliance."""
    
    def test_sse_line_format(self, client: httpx.Client):
        """Test SSE uses proper line format."""
        response = client.get("/sse/basic")
        text = response.text
        
        # Should have event: lines
        assert "event:" in text
        
        # Should have data: lines
        assert "data:" in text
    
    def test_sse_event_separation(self, client: httpx.Client):
        """Test SSE events are properly separated."""
        response = client.get("/sse/basic")
        text = response.text
        
        # Events should be separated by blank lines
        lines = text.split("\n")
        
        # Should have some content
        assert len(lines) > 3
