# HTTP Client

Hypern includes a high-performance HTTP client backed by Rust (`reqwest`). It supports GET, POST, PUT, PATCH, and DELETE methods with connection pooling and TLS support.

## Quick Start

```python
from hypern.client import HttpClient

client = HttpClient()

# Simple GET request
response = client.get("https://api.example.com/data")
print(response.status)   # 200
print(response.text())    # response body as string
print(response.json())    # parsed JSON as dict
```

## API Reference

### HttpClient

```python
from hypern.client import HttpClient

client = HttpClient()
```

#### Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `get` | `get(url, headers=None)` | HTTP GET |
| `post` | `post(url, body=None, headers=None)` | HTTP POST |
| `put` | `put(url, body=None, headers=None)` | HTTP PUT |
| `patch` | `patch(url, body=None, headers=None)` | HTTP PATCH |
| `delete` | `delete(url, headers=None)` | HTTP DELETE |

**Parameters:**

- `url` (`str`): The request URL
- `body` (`str`, optional): Request body (for POST/PUT/PATCH)
- `headers` (`dict`, optional): Request headers as `{name: value}` pairs

**Returns:** `ClientResponse`

### ClientResponse

| Property/Method | Return Type | Description |
|-----------------|-------------|-------------|
| `status` | `int` | HTTP status code |
| `headers()` | `dict` | Response headers |
| `text()` | `str` | Body as UTF-8 string |
| `json()` | `dict` | Body parsed as JSON |
| `bytes()` | `bytes` | Raw response bytes |

## Examples

### POST with JSON body

```python
import json

response = client.post(
    "https://api.example.com/users",
    body=json.dumps({"name": "Alice", "email": "alice@example.com"}),
    headers={"Content-Type": "application/json"}
)

if response.status == 201:
    user = response.json()
    print(f"Created user: {user['id']}")
```

### Custom headers

```python
response = client.get(
    "https://api.example.com/protected",
    headers={
        "Authorization": "Bearer my-token",
        "Accept": "application/json",
    }
)
```

### Error handling

```python
response = client.get("https://api.example.com/data")

if response.status >= 400:
    print(f"Error {response.status}: {response.text()}")
else:
    data = response.json()
```

## Features

- **Connection pooling** — connections are reused automatically
- **TLS support** — uses `rustls` for secure connections
- **Gzip decompression** — transparent response decompression
- **Zero-copy** — response data stays in Rust until accessed from Python
