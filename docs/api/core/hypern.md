# Hypern Class

The `Hypern` class is the main application class for building web applications with Hypern.

## Overview

The `Hypern` class serves as the core container for your web application. It manages routing, middleware, configuration, and the server lifecycle.

## Import

```python
from hypern import Hypern
```

## Class Definition

```python
class Hypern:
    def __init__(self, routes: List[Route] | None = None) -> None:
        """
        Initialize a Hypern application.
        
        Args:
            routes: Optional list of Route objects to register at initialization.
        """
```

## Constructor

### `__init__(routes=None)`

Creates a new Hypern application instance.

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `routes` | `List[Route] \| None` | `None` | Optional list of routes to register at initialization |

**Example:**

```python
from hypern import Hypern

# Create empty application
app = Hypern()

# Create application with routes
from hypern.hypern import Route

routes = [
    Route(path="/", function=home_handler, method="GET"),
    Route(path="/api/users", function=users_handler, method="GET")
]

app = Hypern(routes=routes)
```

## Methods

### `start()`

Starts the Hypern server with the specified configuration.

**Signature:**

```python
def start(
    self,
    host: str = '0.0.0.0',
    port: int = 5000,
    workers: int = 1,
    max_blocking_threads: int = 1,
    max_connections: int = 10000,
) -> None:
    """
    Start the Hypern server.
    
    Args:
        host: The host address to bind to. Defaults to '0.0.0.0'.
        port: The port number to bind to. Defaults to 5000.
        workers: The number of worker threads to use. Defaults to 1.
        max_blocking_threads: The maximum number of blocking threads. Defaults to 1.
        max_connections: Maximum concurrent connections. Defaults to 10000.
    """
```

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `host` | `str` | `"0.0.0.0"` | Host address to bind the server to |
| `port` | `int` | `5000` | Port number for the server to listen on |
| `workers` | `int` | `1` | Number of worker threads for handling requests |
| `max_blocking_threads` | `int` | `1` | Maximum number of threads for blocking operations |
| `max_connections` | `int` | `10000` | Maximum number of concurrent connections |

**Example:**

```python
from hypern import Hypern

app = Hypern()

if __name__ == "__main__":
    # Start with default settings
    app.start()
    
    # Start with custom configuration
    app.start(
        host="127.0.0.1",
        port=8000,
        workers=4,
        max_blocking_threads=32,
        max_connections=50000
    )
```

**Performance Recommendations:**

- **Development**: Use `workers=1` for easier debugging
- **Production (CPU-bound)**: Set `workers` equal to number of CPU cores
- **Production (I/O-bound)**: Set `workers` to CPU cores × 2
- **High I/O**: Increase `max_blocking_threads` for database/API calls
- **High traffic**: Increase `max_connections` for concurrent requests

### `add_route()`

Adds a single route to the application.

**Signature:**

```python
def add_route(
    self,
    method: str,
    endpoint: str,
    handler: Callable[..., Any]
) -> None:
    """
    Add a route to the router.
    
    Args:
        method: The HTTP method for the route (e.g., GET, POST).
        endpoint: The endpoint path for the route.
        handler: The function that handles requests to the route.
    """
```

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `method` | `str` | HTTP method (GET, POST, PUT, DELETE, etc.) |
| `endpoint` | `str` | URL path for the route |
| `handler` | `Callable` | Handler function to process requests |

**Example:**

```python
from hypern import Hypern, Request, Response

app = Hypern()

def user_handler(request: Request, response: Response):
    response.status(200)
    response.header("Content-Type", "application/json")
    response.body_str('{"user": "John Doe"}')
    response.finish()

# Add route
app.add_route("GET", "/api/user", user_handler)
app.add_route("POST", "/api/user", create_user_handler)
```

### `get()`

Decorator for registering GET routes.

**Signature:**

```python
def get(self, path: str) -> Callable:
    """
    Decorator to register a GET route.
    
    Args:
        path: The URL path for the route
    
    Returns:
        Decorator function
    """
```

**Example:**

```python
from hypern import Hypern

app = Hypern()

@app.get("/users")
def get_users(request, response):
    response.status(200)
    response.body_str("List of users")
    response.finish()

@app.get("/users/{id}")
def get_user(request, response):
    user_id = request.path_params.get("id")
    response.status(200)
    response.body_str(f"User {user_id}")
    response.finish()
```

### `post()`

Decorator for registering POST routes.

**Signature:**

```python
def post(self, path: str) -> Callable:
    """
    Decorator to register a POST route.
    
    Args:
        path: The URL path for the route
    
    Returns:
        Decorator function
    """
```

**Example:**

```python
@app.post("/users")
def create_user(request, response):
    # Handle user creation
    response.status(201)
    response.body_str('{"message": "User created"}')
    response.finish()
```

### `put()`

Decorator for registering PUT routes.

**Signature:**

```python
def put(self, path: str) -> Callable:
    """
    Decorator to register a PUT route.
    
    Args:
        path: The URL path for the route
    
    Returns:
        Decorator function
    """
```

**Example:**

```python
@app.put("/users/{id}")
def update_user(request, response):
    user_id = request.path_params.get("id")
    # Handle user update
    response.status(200)
    response.body_str(f'{{"message": "User {user_id} updated"}}')
    response.finish()
```

### `delete()`

Decorator for registering DELETE routes.

**Signature:**

```python
def delete(self, path: str) -> Callable:
    """
    Decorator to register a DELETE route.
    
    Args:
        path: The URL path for the route
    
    Returns:
        Decorator function
    """
```

**Example:**

```python
@app.delete("/users/{id}")
def delete_user(request, response):
    user_id = request.path_params.get("id")
    # Handle user deletion
    response.status(204)
    response.finish()
```

## Attributes

### `router`

The internal `Router` instance that manages all routes.

**Type:** `Router`

**Example:**

```python
from hypern import Hypern

app = Hypern()

# Access router
router = app.router

# Get all routes
routes = router.routes
```

### `response_headers`

Dictionary of default response headers to include in all responses.

**Type:** `dict`

**Example:**

```python
app = Hypern()

# Set default headers
app.response_headers = {
    "X-Custom-Header": "value",
    "X-API-Version": "1.0"
}
```

## Complete Example

Here's a complete example showing various features:

```python
from hypern import Hypern, Request, Response
import json
import os

def create_app():
    """Application factory function."""
    app = Hypern()
    
    # Home endpoint
    @app.get("/")
    def home(request: Request, response: Response):
        response.status(200)
        response.header("Content-Type", "text/html")
        response.body_str("<h1>Welcome to Hypern!</h1>")
        response.finish()
    
    # Health check
    @app.get("/health")
    def health(request: Request, response: Response):
        health_status = {
            "status": "healthy",
            "version": "1.0.0"
        }
        response.status(200)
        response.header("Content-Type", "application/json")
        response.body_str(json.dumps(health_status))
        response.finish()
    
    # Get all users
    @app.get("/api/users")
    def get_users(request: Request, response: Response):
        users = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"}
        ]
        response.status(200)
        response.header("Content-Type", "application/json")
        response.body_str(json.dumps(users))
        response.finish()
    
    # Get user by ID
    @app.get("/api/users/{id}")
    def get_user(request: Request, response: Response):
        user_id = request.path_params.get("id")
        user = {"id": user_id, "name": "User Name"}
        response.status(200)
        response.header("Content-Type", "application/json")
        response.body_str(json.dumps(user))
        response.finish()
    
    # Create user
    @app.post("/api/users")
    def create_user(request: Request, response: Response):
        # Parse request body and create user
        result = {"id": 3, "message": "User created"}
        response.status(201)
        response.header("Content-Type", "application/json")
        response.body_str(json.dumps(result))
        response.finish()
    
    # Update user
    @app.put("/api/users/{id}")
    def update_user(request: Request, response: Response):
        user_id = request.path_params.get("id")
        result = {"id": user_id, "message": "User updated"}
        response.status(200)
        response.header("Content-Type", "application/json")
        response.body_str(json.dumps(result))
        response.finish()
    
    # Delete user
    @app.delete("/api/users/{id}")
    def delete_user(request: Request, response: Response):
        response.status(204)
        response.finish()
    
    return app

if __name__ == "__main__":
    app = create_app()
    
    # Start server with configuration
    app.start(
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", 5000)),
        workers=int(os.getenv("WORKERS", 4)),
        max_blocking_threads=32,
        max_connections=10000
    )
```

## Best Practices

### 1. Use Application Factory

```python
def create_app(config=None):
    app = Hypern()
    # Setup routes, middleware, etc.
    return app
```

### 2. Environment-Based Configuration

```python
import os

app.start(
    host=os.getenv("HOST", "0.0.0.0"),
    port=int(os.getenv("PORT", 5000)),
    workers=int(os.getenv("WORKERS", 4))
)
```

### 3. Organize Routes by Feature

```python
# users.py
def register_user_routes(app):
    @app.get("/users")
    def get_users(request, response):
        pass

# main.py
from users import register_user_routes

app = Hypern()
register_user_routes(app)
```

### 4. Include Health Checks

```python
@app.get("/health")
def health(request, response):
    response.status(200)
    response.body_str('{"status": "healthy"}')
    response.finish()
```

### 5. Set Appropriate Worker Count

```python
import os

workers = os.cpu_count()  # Match CPU cores
app.start(workers=workers)
```

## See Also

- [Router](router.md) - Route management
- [Route](route.md) - Individual route configuration
- [Request](../http/request.md) - Request handling
- [Response](../http/response.md) - Response building
- [Application Guide](../../guide/application.md) - Detailed application guide