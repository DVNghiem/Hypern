# Application Guide

This guide covers the `Hypern` application class, which is the core of your web application.

## Overview

The `Hypern` class is the main entry point for building web applications. It manages routing, configuration, server lifecycle, and middleware orchestration.

## Creating an Application

### Basic Application

The simplest way to create an application:

```python
from hypern import Hypern

app = Hypern()

if __name__ == "__main__":
    app.start()
```

### Application with Routes

Create an application with predefined routes:

```python
from hypern import Hypern
from hypern.hypern import Route

def home_handler(request, response):
    response.status(200)
    response.body_str("Welcome to Hypern!")
    response.finish()

routes = [
    Route(path="/", function=home_handler, method="GET")
]

app = Hypern(routes=routes)

if __name__ == "__main__":
    app.start()
```

## Application Configuration

### Server Parameters

Configure the server when starting your application:

```python
app.start(
    host="0.0.0.0",              # Bind address (default: "0.0.0.0")
    port=8000,                    # Port number (default: 5000)
    workers=4,                    # Worker threads (default: 1)
    max_blocking_threads=32,      # Max blocking threads (default: 1)
    max_connections=10000         # Max concurrent connections (default: 10000)
)
```

### Configuration Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `host` | str | `"0.0.0.0"` | Host address to bind to |
| `port` | int | `5000` | Port number to listen on |
| `workers` | int | `1` | Number of worker threads |
| `max_blocking_threads` | int | `1` | Maximum number of blocking threads |
| `max_connections` | int | `10000` | Maximum concurrent connections |

### Environment-Based Configuration

Use environment variables for configuration:

```python
import os
from hypern import Hypern

app = Hypern()

if __name__ == "__main__":
    app.start(
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", 5000)),
        workers=int(os.getenv("WORKERS", 4))
    )
```

### Configuration Class Pattern

Create a configuration class:

```python
import os
from dataclasses import dataclass

@dataclass
class Config:
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", 5000))
    WORKERS: int = int(os.getenv("WORKERS", 4))
    MAX_BLOCKING_THREADS: int = int(os.getenv("MAX_BLOCKING_THREADS", 32))
    MAX_CONNECTIONS: int = int(os.getenv("MAX_CONNECTIONS", 10000))

from hypern import Hypern

app = Hypern()

if __name__ == "__main__":
    config = Config()
    app.start(
        host=config.HOST,
        port=config.PORT,
        workers=config.WORKERS,
        max_blocking_threads=config.MAX_BLOCKING_THREADS,
        max_connections=config.MAX_CONNECTIONS
    )
```

## Adding Routes

### Method 1: add_route()

Add routes programmatically:

```python
from hypern import Hypern

app = Hypern()

def get_users(request, response):
    response.status(200)
    response.body_str("List of users")
    response.finish()

def create_user(request, response):
    response.status(201)
    response.body_str("User created")
    response.finish()

app.add_route("GET", "/api/users", get_users)
app.add_route("POST", "/api/users", create_user)
```

### Method 2: Decorators

Use decorators for cleaner syntax:

```python
from hypern import Hypern

app = Hypern()

@app.get("/api/users")
def get_users(request, response):
    response.status(200)
    response.body_str("List of users")
    response.finish()

@app.post("/api/users")
def create_user(request, response):
    response.status(201)
    response.body_str("User created")
    response.finish()

@app.put("/api/users/{id}")
def update_user(request, response):
    response.status(200)
    response.body_str("User updated")
    response.finish()

@app.delete("/api/users/{id}")
def delete_user(request, response):
    response.status(204)
    response.finish()
```

### Method 3: Route Objects

Use Route objects for advanced configuration:

```python
from hypern import Hypern
from hypern.hypern import Route

def user_handler(request, response):
    response.status(200)
    response.body_str("User data")
    response.finish()

routes = [
    Route(
        path="/api/users/{id}",
        function=user_handler,
        method="GET",
        doc="Get user by ID"
    )
]

app = Hypern(routes=routes)
```

## Application Factory Pattern

For larger applications, use the factory pattern:

```python
from hypern import Hypern
from typing import Optional

def create_app(config: Optional[dict] = None) -> Hypern:
    """
    Application factory function.
    
    Args:
        config: Optional configuration dictionary
    
    Returns:
        Configured Hypern application
    """
    app = Hypern()
    
    # Register routes
    register_routes(app)
    
    # Setup middleware
    setup_middleware(app)
    
    return app

def register_routes(app: Hypern):
    """Register all application routes."""
    
    @app.get("/")
    def index(request, response):
        response.status(200)
        response.body_str("Home Page")
        response.finish()
    
    @app.get("/health")
    def health(request, response):
        response.status(200)
        response.body_str('{"status": "healthy"}')
        response.finish()

def setup_middleware(app: Hypern):
    """Setup application middleware."""
    # Add middleware configuration here
    pass

if __name__ == "__main__":
    app = create_app()
    app.start(port=8000)
```

## Application Lifecycle

### Startup Process

1. **Initialization**: Create Hypern instance
2. **Route Registration**: Register all routes
3. **Configuration**: Set server parameters
4. **Server Start**: Begin accepting requests

```python
from hypern import Hypern

# 1. Initialization
app = Hypern()

# 2. Route Registration
@app.get("/")
def index(request, response):
    response.status(200)
    response.body_str("Hello")
    response.finish()

# 3. Configuration & 4. Server Start
if __name__ == "__main__":
    app.start(port=8000)
```

### Request Processing Flow

```
1. Client sends HTTP request
2. Server receives request
3. Router matches request to handler
4. Handler processes request
5. Handler builds response
6. Server sends response to client
```

## Multi-Process Architecture

### Understanding Workers

Hypern uses a multi-process architecture for optimal performance:

```python
app.start(
    workers=4,  # Creates 4 worker processes
    max_blocking_threads=32
)
```

**Worker Characteristics:**
- Each worker is a separate process
- Workers handle requests independently
- No shared memory between workers
- Better CPU utilization

### Choosing Worker Count

```python
import os

# Option 1: Match CPU cores
workers = os.cpu_count()

# Option 2: CPU cores * 2 (for I/O bound)
workers = os.cpu_count() * 2

# Option 3: Fixed number
workers = 4

app.start(workers=workers)
```

**Guidelines:**
- **CPU-bound tasks**: workers = CPU cores
- **I/O-bound tasks**: workers = CPU cores * 2
- **Development**: workers = 1 (easier debugging)
- **Production**: workers = 4-8 (typical)

### Blocking Threads

Configure threads for blocking operations:

```python
app.start(
    workers=4,
    max_blocking_threads=32  # For blocking I/O
)
```

**When to increase:**
- Database queries
- File I/O operations
- External API calls
- Synchronous operations

## Error Handling

### Application-Level Error Handling

Handle errors at the application level:

```python
from hypern import Hypern
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Hypern()

@app.get("/api/resource")
def get_resource(request, response):
    try:
        # Your logic here
        data = fetch_data()
        response.status(200)
        response.body_str(data)
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        response.status(400)
        response.body_str(f'{{"error": "{str(e)}"}}')
    except Exception as e:
        logger.exception("Unexpected error")
        response.status(500)
        response.body_str('{"error": "Internal server error"}')
    finally:
        response.finish()
```

### Global Error Handler Pattern

Create a wrapper for consistent error handling:

```python
import json
import logging
from functools import wraps

logger = logging.getLogger(__name__)

def handle_errors(handler):
    """Decorator for consistent error handling."""
    @wraps(handler)
    def wrapper(request, response):
        try:
            return handler(request, response)
        except ValueError as e:
            logger.warning(f"Client error: {e}")
            response.status(400)
            response.header("Content-Type", "application/json")
            response.body_str(json.dumps({"error": str(e)}))
            response.finish()
        except Exception as e:
            logger.exception("Server error")
            response.status(500)
            response.header("Content-Type", "application/json")
            response.body_str(json.dumps({"error": "Internal server error"}))
            response.finish()
    return wrapper

@app.get("/api/users")
@handle_errors
def get_users(request, response):
    # Your logic - errors are handled automatically
    users = fetch_users()
    response.status(200)
    response.body_str(json.dumps(users))
    response.finish()
```

## Performance Tuning

### Connection Management

Tune connection settings for your workload:

```python
# High-traffic API
app.start(
    workers=8,
    max_connections=50000,
    max_blocking_threads=64
)

# Low-traffic internal service
app.start(
    workers=2,
    max_connections=1000,
    max_blocking_threads=16
)
```

### Memory Optimization

Hypern uses efficient memory allocators:

- **Linux/macOS**: jemalloc (default)
- **Windows**: mimalloc
- **Result**: Better memory management, lower overhead

### Response Optimization

Optimize response handling:

```python
import orjson  # Fast JSON library (included with Hypern)

@app.get("/api/data")
def get_data(request, response):
    data = {"key": "value"}
    
    # Use orjson for faster JSON serialization
    json_bytes = orjson.dumps(data)
    
    response.status(200)
    response.header("Content-Type", "application/json")
    response.body(json_bytes)  # Use body() for bytes
    response.finish()
```

## Best Practices

### 1. Use Application Factory

```python
def create_app(env="production"):
    app = Hypern()
    
    if env == "development":
        app.start(workers=1, port=5000)
    else:
        app.start(workers=4, port=8000)
    
    return app
```

### 2. Separate Configuration

Keep configuration separate from code:

```python
# config.py
class Config:
    HOST = "0.0.0.0"
    PORT = 8000
    WORKERS = 4

# main.py
from config import Config

app = Hypern()
app.start(
    host=Config.HOST,
    port=Config.PORT,
    workers=Config.WORKERS
)
```

### 3. Modular Route Registration

Organize routes by feature:

```python
# routes/users.py
def register_user_routes(app):
    @app.get("/users")
    def get_users(request, response):
        pass

# routes/products.py
def register_product_routes(app):
    @app.get("/products")
    def get_products(request, response):
        pass

# main.py
from routes.users import register_user_routes
from routes.products import register_product_routes

app = Hypern()
register_user_routes(app)
register_product_routes(app)
```

### 4. Health Check Endpoints

Always include health checks:

```python
@app.get("/health")
def health_check(request, response):
    response.status(200)
    response.header("Content-Type", "application/json")
    response.body_str('{"status": "healthy", "version": "1.0.0"}')
    response.finish()

@app.get("/readiness")
def readiness_check(request, response):
    # Check database, dependencies, etc.
    ready = check_dependencies()
    
    if ready:
        response.status(200)
        response.body_str('{"ready": true}')
    else:
        response.status(503)
        response.body_str('{"ready": false}')
    response.finish()
```

### 5. Graceful Shutdown

Handle shutdown signals properly:

```python
import signal
import sys
from hypern import Hypern

app = Hypern()

def signal_handler(sig, frame):
    print("Shutting down gracefully...")
    # Cleanup code here
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

if __name__ == "__main__":
    app.start()
```

## Testing Applications

### Basic Testing

```python
import pytest
from hypern import Hypern

def test_app_creation():
    app = Hypern()
    assert app is not None

def test_route_registration():
    app = Hypern()
    
    @app.get("/test")
    def test_handler(request, response):
        response.status(200)
        response.finish()
    
    # Test that route was registered
    # (implementation depends on your testing setup)
```

### Integration Testing

```python
import requests
from multiprocessing import Process
import time

def run_server():
    app = Hypern()
    
    @app.get("/test")
    def test_handler(request, response):
        response.status(200)
        response.body_str("test")
        response.finish()
    
    app.start(port=5001)

def test_endpoint():
    # Start server in separate process
    p = Process(target=run_server)
    p.start()
    time.sleep(1)  # Wait for server to start
    
    # Test endpoint
    response = requests.get("http://localhost:5001/test")
    assert response.status_code == 200
    assert response.text == "test"
    
    # Cleanup
    p.terminate()
    p.join()
```

## Next Steps

- [Routing Guide](routing.md) - Learn about advanced routing
- [Request Handling](requests.md) - Work with requests
- [Response Building](responses.md) - Construct responses
- [Middleware](middleware.md) - Add middleware layers
- [Performance](../advanced/performance.md) - Optimize performance

## Examples

### Minimal API

```python
from hypern import Hypern

app = Hypern()

@app.get("/")
def index(request, response):
    response.status(200)
    response.body_str("Hello, World!")
    response.finish()

if __name__ == "__main__":
    app.start()
```

### RESTful API

```python
from hypern import Hypern
import json

app = Hypern()

# In-memory data store
users = {}
next_id = 1

@app.get("/api/users")
def list_users(request, response):
    response.status(200)
    response.header("Content-Type", "application/json")
    response.body_str(json.dumps(list(users.values())))
    response.finish()

@app.post("/api/users")
def create_user(request, response):
    global next_id
    # Parse request body
    user = {"id": next_id, "name": "User"}
    users[next_id] = user
    next_id += 1
    
    response.status(201)
    response.header("Content-Type", "application/json")
    response.body_str(json.dumps(user))
    response.finish()

@app.get("/api/users/{id}")
def get_user(request, response):
    user_id = int(request.path_params.get("id"))
    user = users.get(user_id)
    
    if user:
        response.status(200)
        response.body_str(json.dumps(user))
    else:
        response.status(404)
        response.body_str('{"error": "User not found"}')
    
    response.finish()

if __name__ == "__main__":
    app.start(port=8000, workers=4)
```

## Summary

The `Hypern` application class provides:

- **Simple API**: Easy to create and configure
- **Flexible routing**: Multiple ways to define routes
- **High performance**: Multi-process architecture
- **Type safety**: Full type hint support
- **Scalability**: Configurable workers and connections
- **Production-ready**: Built on Rust for reliability

Start building your high-performance web applications with Hypern today!