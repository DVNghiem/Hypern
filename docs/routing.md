# Routing

## HTTP Methods

Hypern supports all standard HTTP methods:

```python
from hypern import Hypern

app = Hypern()

@app.get("/resource")
def get_resource(req, res, ctx):
    res.json({"action": "get"})

@app.post("/resource")
def create_resource(req, res, ctx):
    body = req.json()
    res.status(201).json({"created": body})

@app.put("/resource/:id")
def update_resource(req, res, ctx):
    res.json({"action": "update"})

@app.patch("/resource/:id")
def patch_resource(req, res, ctx):
    res.json({"action": "patch"})

@app.delete("/resource/:id")
def delete_resource(req, res, ctx):
    res.json({"action": "delete"})

@app.options("/resource")
def options_resource(req, res, ctx):
    res.header("Allow", "GET, POST, PUT, DELETE")
    res.status(204).send(None)

@app.head("/resource")
def head_resource(req, res, ctx):
    res.header("X-Resource-Count", "42")
    res.status(200).send(None)
```

## Route Parameters

Use `:param` syntax for dynamic path segments:

```python
@app.get("/users/:user_id")
def get_user(req, res, ctx):
    user_id = req.param("user_id")
    res.json({"user_id": user_id})

@app.get("/users/:user_id/posts/:post_id")
def get_user_post(req, res, ctx):
    user_id = req.param("user_id")
    post_id = req.param("post_id")
    res.json({"user_id": user_id, "post_id": post_id})
```

## Wildcard Routes

Capture remaining path segments:

```python
@app.get("/files/*filepath")
def serve_file(req, res, ctx):
    filepath = req.param("filepath")
    # filepath = "path/to/file.txt" for /files/path/to/file.txt
    res.json({"filepath": filepath})
```

## Router Groups

Organize routes with routers and prefixes:

```python
from hypern import Router

# API v1
api_v1 = Router(prefix="/api/v1")

@api_v1.get("/users")
def v1_users(req, res, ctx):
    res.json({"version": "v1", "users": []})

@api_v1.get("/users/:id")
def v1_user(req, res, ctx):
    res.json({"version": "v1"})

# API v2
api_v2 = Router(prefix="/api/v2")

@api_v2.get("/users")
def v2_users(req, res, ctx):
    res.json({"version": "v2", "users": []})

# Mount routers
app.mount(api_v1)
app.mount(api_v2)
```

## Route-Specific Middleware

Apply middleware to specific routes:

```python
from hypern.middleware import CorsMiddleware

cors = CorsMiddleware(allowed_origins=["https://example.com"])

@app.get("/api/data", middleware=[cors])
def get_data(req, res, ctx):
    res.json({"data": "sensitive"})
```

## Route Metadata (OpenAPI)

Add metadata for API documentation using decorators:

```python
from hypern import api_tags, api_doc

# Using decorators
@api_tags("users")
@api_doc("Get User")
@app.get("/users/:id")
def get_user(req, res, ctx):
    """Retrieve a user by their ID"""
    res.json({"id": req.param("id")})

# Multiple tags
@api_tags("users", "admin")
@app.get("/users/:id/admin")
def get_user_admin(req, res, ctx):
    """Admin user retrieval endpoint"""
    res.json({"id": req.param("id")})
```

### Using Docstrings

OpenAPI automatically extracts documentation from docstrings:

```python
@api_tags("users")
@app.get("/users/:id")
def get_user(req, res, ctx):
    """
    Get User
    
    Retrieve a user by their ID. Returns the user object
    with all available fields.
    """
    res.json({"id": req.param("id")})
```

### Available Decorators

```python
from hypern.openapi import (
    tags,              # Add tags to endpoint
    summary,           # Set summary
    description,       # Set description  
    deprecated,        # Mark as deprecated
    response,          # Document response
    operation_id,      # Set custom operation ID
    requires_auth,     # Mark as requiring auth
)

# Complete example
@tags("users")
@summary("Create User")
@description("Create a new user account")
@response(201, "User created successfully")
@response(400, "Invalid input")
@app.post("/users")
def create_user(req, res, ctx):
    """Create a new user"""
    data = req.json()
    res.status(201).json({"id": 123, **data})
```

## Async Handlers

Hypern supports both sync and async handlers:

```python
import asyncio

@app.get("/sync")
def sync_handler(req, res, ctx):
    res.json({"type": "sync"})

@app.get("/async")
async def async_handler(req, res, ctx):
    await asyncio.sleep(0.1)
    res.json({"type": "async"})
```

## Route Priority

Hypern uses a high-performance radix tree router (powered by the `matchit` crate) for O(k) route matching, where k is the path length. Routes are matched in order of specificity:

1. Exact matches (e.g., `/users/me`)
2. Parameterized routes (e.g., `/users/:id`)
3. Wildcard routes (e.g., `/files/*filepath`)

```python
# This order matters for correct matching
@app.get("/users/me")       # Matched first for /users/me
def current_user(req, res, ctx):
    res.json({"user": "current"})

@app.get("/users/:id")      # Matched for /users/123
def get_user(req, res, ctx):
    res.json({"user_id": req.param("id")})
```

### Route Syntax

Hypern uses Express.js-style routing syntax:

| Syntax | Description | Example |
|--------|-------------|---------|
| `:param` | Named parameter | `/users/:id` matches `/users/123` |
| `*param` | Wildcard (catch-all) | `/files/*filepath` matches `/files/a/b/c.txt` |

The wildcard parameter captures everything after the prefix, including slashes.
