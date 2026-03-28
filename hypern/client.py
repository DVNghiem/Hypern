"""
Built-in async HTTP client backed by Rust/reqwest.

Provides connection pooling and GIL-free I/O at the Rust level.

Example::

    from hypern.client import HttpClient

    client = HttpClient(base_url="https://api.example.com", timeout=30)
    response = client.get("/users", params={"page": "1"})
    data = response.json()
"""

from hypern._hypern import HttpClient, ClientResponse

__all__ = ["HttpClient", "ClientResponse"]
