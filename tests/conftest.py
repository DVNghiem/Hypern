"""
Pytest configuration and fixtures for Hypern framework tests.

This module provides:
- Test server management via subprocess
- HTTP client fixtures
- Helper functions for assertions
"""

import os
import sys
import time
import subprocess
import socket
import httpx
import pytest
from typing import Optional, Dict, Any


# ============================================================================
# Test Configuration
# ============================================================================

TEST_HOST = "127.0.0.1"
TEST_PORT = 8765
TEST_BASE_URL = f"http://{TEST_HOST}:{TEST_PORT}"
SERVER_STARTUP_TIMEOUT = 15.0  # seconds
SERVER_SHUTDOWN_TIMEOUT = 5.0  # seconds


# ============================================================================
# Server Process Management
# ============================================================================

class TestServerProcess:
    """Manages the test server as a separate process."""
    
    def __init__(self, host: str = TEST_HOST, port: int = TEST_PORT):
        self.host = host
        self.port = port
        self.process: Optional[subprocess.Popen] = None
        self.base_url = f"http://{host}:{port}"
    
    def is_port_in_use(self) -> bool:
        """Check if the port is already in use."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex((self.host, self.port)) == 0
    
    def wait_for_server(self, timeout: float = SERVER_STARTUP_TIMEOUT) -> bool:
        """Wait for the server to start accepting connections."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.is_port_in_use():
                # Verify server is responding
                try:
                    response = httpx.get(f"{self.base_url}/health", timeout=2.0)
                    if response.status_code == 200:
                        return True
                except (httpx.RequestError, httpx.TimeoutException):
                    pass
            time.sleep(0.1)
        return False
    
    def start(self) -> None:
        """Start the test server in a subprocess."""
        if self.is_port_in_use():
            raise RuntimeError(f"Port {self.port} is already in use")
        
        # Get the path to the test server script
        server_script = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "test_server.py"
        )
        
        # Get the Python executable from the virtual environment
        python_exe = sys.executable
        
        # Start the server process
        self.process = subprocess.Popen(
            [python_exe, server_script, "--host", self.host, "--port", str(self.port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        
        # Wait for the server to start
        if not self.wait_for_server():
            # Get error output if server failed to start
            stdout, stderr = "", ""
            if self.process:
                try:
                    stdout, stderr = self.process.communicate(timeout=1.0)
                    stdout = stdout.decode("utf-8", errors="replace") if stdout else ""
                    stderr = stderr.decode("utf-8", errors="replace") if stderr else ""
                except subprocess.TimeoutExpired:
                    self.process.kill()
            
            error_msg = f"Server failed to start within {SERVER_STARTUP_TIMEOUT} seconds"
            if stderr:
                error_msg += f"\nServer stderr: {stderr}"
            if stdout:
                error_msg += f"\nServer stdout: {stdout}"
            raise RuntimeError(error_msg)
    
    def stop(self) -> None:
        """Stop the test server process."""
        if self.process:
            # Send SIGTERM first
            self.process.terminate()
            try:
                self.process.wait(timeout=SERVER_SHUTDOWN_TIMEOUT)
            except subprocess.TimeoutExpired:
                # Force kill if doesn't respond
                self.process.kill()
                self.process.wait(timeout=1.0)
            finally:
                self.process = None
    
    def is_running(self) -> bool:
        """Check if the server process is running."""
        return self.process is not None and self.process.poll() is None


# Global server instance
_server: Optional[TestServerProcess] = None


def get_server() -> TestServerProcess:
    """Get or create the global test server instance."""
    global _server
    if _server is None:
        _server = TestServerProcess()
    return _server


# ============================================================================
# Pytest Fixtures
# ============================================================================

@pytest.fixture(scope="session")
def test_server():
    """Session-scoped fixture that starts the test server."""
    server = get_server()
    try:
        server.start()
        yield server
    finally:
        server.stop()


@pytest.fixture(scope="session")
def base_url(test_server):
    """Get the base URL for the test server."""
    return test_server.base_url


@pytest.fixture(scope="function")
def client(base_url):
    """Function-scoped HTTP client for making requests."""
    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        yield client


@pytest.fixture(scope="session")
def session_client(base_url):
    """Session-scoped HTTP client for making requests."""
    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        yield client


@pytest.fixture(autouse=True)
def reset_database(client):
    """Reset the test database before each test."""
    yield
    # Reset database after each test
    try:
        client.post("/test/reset-db")
    except httpx.RequestError:
        pass  # Ignore errors during cleanup


# ============================================================================
# Helper Functions for Assertions
# ============================================================================

def assert_status(response: httpx.Response, expected_status: int, msg: str = "") -> None:
    """Assert that the response has the expected status code."""
    assert response.status_code == expected_status, (
        f"{msg}Expected status {expected_status}, got {response.status_code}. "
        f"Response: {response.text[:500]}"
    )


def assert_json_response(
    response: httpx.Response,
    expected_keys: list = None,
    expected_values: dict = None
) -> Dict[str, Any]:
    """Assert response is JSON and optionally check keys/values."""
    content_type = response.headers.get("content-type", "")
    assert "application/json" in content_type, (
        f"Expected JSON response, got content-type: {content_type}"
    )
    
    data = response.json()
    
    if expected_keys:
        for key in expected_keys:
            assert key in data, f"Expected key '{key}' not found in response: {data}"
    
    if expected_values:
        for key, value in expected_values.items():
            assert data.get(key) == value, (
                f"Expected {key}={value}, got {key}={data.get(key)}"
            )
    
    return data


def assert_header(response: httpx.Response, header_name: str, expected_value: str = None) -> str:
    """Assert that a response header exists and optionally check its value."""
    value = response.headers.get(header_name)
    assert value is not None, f"Header '{header_name}' not found in response"
    
    if expected_value is not None:
        assert value == expected_value, (
            f"Header '{header_name}' expected '{expected_value}', got '{value}'"
        )
    
    return value


def assert_cookie(response: httpx.Response, cookie_name: str, expected_value: str = None) -> str:
    """Assert that a cookie exists in the response."""
    cookies = response.cookies
    assert cookie_name in cookies, (
        f"Cookie '{cookie_name}' not found. Available: {list(cookies.keys())}"
    )
    
    value = cookies[cookie_name]
    if expected_value is not None:
        assert value == expected_value, (
            f"Cookie '{cookie_name}' expected '{expected_value}', got '{value}'"
        )
    
    return value


def assert_sse_event(
    event_line: str,
    expected_event: str = None,
    expected_data: str = None,
    expected_id: str = None
) -> Dict[str, str]:
    """Parse and assert SSE event properties."""
    event = {}
    for line in event_line.strip().split("\n"):
        if line.startswith("event:"):
            event["event"] = line[6:].strip()
        elif line.startswith("data:"):
            event["data"] = line[5:].strip()
        elif line.startswith("id:"):
            event["id"] = line[3:].strip()
    
    if expected_event is not None:
        assert event.get("event") == expected_event, (
            f"Expected event '{expected_event}', got '{event.get('event')}'"
        )
    
    if expected_data is not None:
        assert event.get("data") == expected_data, (
            f"Expected data '{expected_data}', got '{event.get('data')}'"
        )
    
    if expected_id is not None:
        assert event.get("id") == expected_id, (
            f"Expected id '{expected_id}', got '{event.get('id')}'"
        )
    
    return event


def parse_sse_events(response_text: str) -> list:
    """Parse SSE events from response text."""
    events = []
    current_event = {}
    
    for line in response_text.split("\n"):
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


def make_json_request(
    client: httpx.Client,
    method: str,
    path: str,
    json_data: dict = None,
    headers: dict = None,
    **kwargs
) -> httpx.Response:
    """Make a JSON request with proper headers."""
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    
    return client.request(
        method=method.upper(),
        url=path,
        json=json_data,
        headers=request_headers,
        **kwargs
    )


def create_test_user(client: httpx.Client, name: str = "Test User", email: str = None) -> Dict[str, Any]:
    """Helper to create a test user."""
    if email is None:
        email = f"{name.lower().replace(' ', '.')}@example.com"
    
    response = client.post(
        "/crud/users",
        json={"name": name, "email": email, "age": 25}
    )
    assert_status(response, 201)
    return response.json()


def delete_test_user(client: httpx.Client, user_id: str) -> None:
    """Helper to delete a test user."""
    client.delete(f"/crud/users/{user_id}")
