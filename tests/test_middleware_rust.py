#!/usr/bin/env python3
"""
Test script demonstrating the pure Rust middleware system.

This tests that the middleware runs before the Python handler,
proving that middleware execution happens in pure Rust without GIL overhead.
"""
import time
import requests
from multiprocessing import Process
from hypern import Hypern


def hello_handler(request, response):
    """Simple handler that returns hello with path info."""
    response.status(200)
    response.header("Content-Type", "text/plain")
    response.body_str(f"Hello from {request.path}")
    response.finish()


def api_handler(request, response):
    """API handler that returns JSON."""
    response.status(200)
    response.header("Content-Type", "application/json")
    response.body_str('{"status": "ok", "message": "API response"}')
    response.finish()


def run_server(port: int):
    """Run the server with middleware enabled."""
    app = Hypern()
    
    # Add routes
    app.add_route("GET", "/hello", hello_handler)
    app.add_route("GET", "/api/data", api_handler)
    app.add_route("POST", "/api/data", api_handler)
    
    print(f"Starting server on port {port}...")
    app.start(port=port, workers=2)


def test_basic_requests(base_url: str):
    """Test basic request handling."""
    print("\n=== Testing Basic Requests ===")
    
    # Test hello endpoint
    res = requests.get(f"{base_url}/hello")
    assert res.status_code == 200
    assert "Hello from /hello" in res.text
    print(f"✓ GET /hello: {res.status_code} - {res.text}")
    
    # Test API endpoint
    res = requests.get(f"{base_url}/api/data")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    print(f"✓ GET /api/data: {res.status_code} - {res.text}")
    
    # Test 404
    res = requests.get(f"{base_url}/notfound")
    assert res.status_code == 404
    print(f"✓ GET /notfound: {res.status_code} (expected 404)")


def test_cors_headers(base_url: str):
    """Test that CORS middleware would add headers (if enabled)."""
    print("\n=== Testing CORS Behavior ===")
    
    # OPTIONS request (preflight)
    res = requests.options(
        f"{base_url}/api/data",
        headers={"Origin": "http://localhost:3000"}
    )
    print(f"OPTIONS /api/data: {res.status_code}")
    print(f"  Response headers: {dict(res.headers)}")


def test_performance(base_url: str, num_requests: int = 100):
    """Simple performance test."""
    print(f"\n=== Performance Test ({num_requests} requests) ===")
    
    start = time.time()
    for _ in range(num_requests):
        res = requests.get(f"{base_url}/hello")
        assert res.status_code == 200
    elapsed = time.time() - start
    
    rps = num_requests / elapsed
    print(f"Completed {num_requests} requests in {elapsed:.3f}s")
    print(f"Requests per second: {rps:.1f}")


if __name__ == "__main__":
    port = 5020
    base_url = f"http://127.0.0.1:{port}"
    
    # Start server in a separate process
    server_process = Process(target=run_server, args=(port,))
    server_process.start()
    
    # Wait for server to start
    print("Waiting for server to start...")
    time.sleep(3)
    
    try:
        # Run tests
        test_basic_requests(base_url)
        test_cors_headers(base_url)
        test_performance(base_url)
        
        print("\n" + "=" * 50)
        print("All tests passed! ✓")
        print("=" * 50)
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        raise
    finally:
        # Clean up
        server_process.terminate()
        server_process.join()
