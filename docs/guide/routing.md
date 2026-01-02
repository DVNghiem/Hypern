# Routing Guide

This guide covers routing in Hypern, including route definition, parameters, HTTP methods, and advanced routing techniques.

## Overview

Routing is the process of mapping HTTP requests to handler functions. Hypern provides a flexible and powerful routing system that supports various patterns and configurations.

## Basic Routing

### Defining Routes

There are three ways to define routes in Hypern:

#### 1. Using `add_route()`

```python
from hypern import Hypern, Request, Response

app = Hypern()

def home_handler(request: Request, response: Response):
    response.status(200)
    response.body_str("Welcome to Hypern!")
    response.finish()

app.add_route("GET", "/", home_handler)
```

#### 2. Using Decorators

```python
from hypern import Hypern

app = Hypern()

@app.get("/")
def home(request, response):
    response.status(200)
    response.body_str("Welcome to Hypern!")
    response.finish()
```

#### 3. Using Route Objects

```python
from hypern import Hypern
from hypern.hypern import Route

def home_handler(request, response):
    response.status(200)
    response.body_str("Welcome!")
    response.finish()

routes = [
    Route(path="/", function=home_handler, method="GET")
]

app = Hypern(routes=routes)
```

## HTTP Methods

Hypern supports all standard HTTP methods:

### GET - Retrieve Resources

```python
@app.get("/users")
def get_users(request, response):
    users = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
    response.status(200)
    response.header("Content-Type", "application/json")
    response.body_str(json.dumps(users))
    response.finish()
```

### POST - Create Resources

```python
@app.post("/users")
def create_user(request, response):
    # Parse request body
    # Create user
    response.status(201)
    response.header("Content-Type", "application/json")
    response.body_str(json.dumps({"id": 3, "message": "User created"}))
    response.finish()
```

### PUT - Update Resources (Full Replacement)

```python
@app.put("/users/{id}")
def update_user(request, response):
    user_id = request.path_params.get("id")
    # Update user
    response.status(200)
    response.header("Content-Type", "application/json")
    response.body_str(json.dumps({"id": user_id, "message": "User updated"}))
    response.finish()
```

### PATCH - Partial Update

```python
@app.patch("/users/{id}")
def patch_user(request, response):
    user_id = request.path_params.get("id")
    # Partially update user
    response.status(200)
    response.body_str(json.dumps({"id": user_id, "message": "User patched"}))
    response.finish()
```

### DELETE - Remove Resources

```python
@app.delete("/users/{id}")
def delete_user(request, response):
    user_id = request.path_params.get("id")
    # Delete user
    response.status(204)
    response.finish()
```

### HEAD - Get Headers Only

```python
@app.head("/users/{id}")
def head_user(request, response):
    response.status(200)
    response.header("Content-Length", "1234")
    response.finish()
```

### OPTIONS - Get Available Methods

```python
@app.options("/users")
def options_users(request, response):
    response.status(200)
    response.header("Allow", "GET, POST, OPTIONS")
    response.finish()
```

## Route Parameters

### Path Parameters

Capture dynamic segments in URL paths:

```python
# Single parameter
@app.get("/users/{id}")
def get_user(request, response):
    user_id = request.path_params.get("id")
    response.status(200)
    response.body_str(f"User ID: {user_id}")
    response.finish()

# Multiple parameters
@app.get("/users/{user_id}/posts/{post_id}")
def get_user_post(request, response):
    user_id = request.path_params.get("user_id")
    post_id = request.path_params.get("post_id")
    response.status(200)
    response.body_str(f"User {user_id}, Post {post_id}")
    response.finish()
```

**Example Requests:**

```bash
GET /users/123
# user_id = "123"

GET /users/42/posts/100
# user_id = "42", post_id = "100"
```

### Query Parameters

Access query string parameters:

```python
@app.get("/search")
def search(request, response):
    # Get query parameters
    query = request.query_params.get("q")
    page = request.query_params.get("page", "1")
    limit = request.query_params.get("limit", "10")
    
    response.status(200)
    response.body_str(f"Search: {query}, Page: {page}, Limit: {limit}")
    response.finish()
```

**Example Request:**

```bash
GET /search?q=python&page=2&limit=20
# query = "python", page = "2", limit = "20"
```

### Parameter Validation

Validate parameters in your handlers:

```python
@app.get("/users/{id}")
def get_user(request, response):
    try:
        user_id = int(request.path_params.get("id"))
        
        if user_id <= 0:
            raise ValueError("User ID must be positive")
        
        # Fetch user
        user = get_user_by_id(user_id)
        
        if not user:
            response.status(404)
            response.body_str(json.dumps({"error": "User not found"}))
        else:
            response.status(200)
            response.body_str(json.dumps(user))
    except ValueError as e:
        response.status(400)
        response.body_str(json.dumps({"error": str(e)}))
    finally:
        response.finish()
```

## Route Patterns

### Static Routes

Exact path matching:

```python
@app.get("/about")
def about(request, response):
    response.status(200)
    response.body_str("About page")
    response.finish()
```

### Dynamic Routes

Routes with parameters:

```python
@app.get("/products/{category}")
def products_by_category(request, response):
    category = request.path_params.get("category")
    response.status(200)
    response.body_str(f"Products in {category}")
    response.finish()
```

### Nested Routes

Deeply nested paths:

```python
@app.get("/api/v1/users/{user_id}/orders/{order_id}/items/{item_id}")
def get_order_item(request, response):
    user_id = request.path_params.get("user_id")
    order_id = request.path_params.get("order_id")
    item_id = request.path_params.get("item_id")
    
    response.status(200)
    response.body_str(f"User: {user_id}, Order: {order_id}, Item: {item_id}")
    response.finish()
```

## Route Organization

### Grouping by Feature

Organize routes by feature or resource:

```python
# users.py
def register_user_routes(app):
    @app.get("/users")
    def list_users(request, response):
        # Implementation
        pass
    
    @app.get("/users/{id}")
    def get_user(request, response):
        # Implementation
        pass
    
    @app.post("/users")
    def create_user(request, response):
        # Implementation
        pass

# products.py
def register_product_routes(app):
    @app.get("/products")
    def list_products(request, response):
        # Implementation
        pass

# main.py
from hypern import Hypern
from users import register_user_routes
from products import register_product_routes

app = Hypern()
register_user_routes(app)
register_product_routes(app)
```

### API Versioning

Organize routes by API version:

```python
# api/v1/users.py
def register_v1_user_routes(app):
    @app.get("/api/v1/users")
    def list_users_v1(request, response):
        # Version 1 implementation
        pass

# api/v2/users.py
def register_v2_user_routes(app):
    @app.get("/api/v2/users")
    def list_users_v2(request, response):
        # Version 2 implementation
        pass

# main.py
from api.v1.users import register_v1_user_routes
from api.v2.users import register_v2_user_routes

app = Hypern()
register_v1_user_routes(app)
register_v2_user_routes(app)
```

### Route Prefixes

Use consistent prefixes for route groups:

```python
# API routes with /api prefix
@app.get("/api/users")
def api_users(request, response):
    pass

@app.get("/api/products")
def api_products(request, response):
    pass

# Admin routes with /admin prefix
@app.get("/admin/dashboard")
def admin_dashboard(request, response):
    pass

@app.get("/admin/users")
def admin_users(request, response):
    pass
```

## RESTful Routing

Follow REST conventions for resource routes:

```python
from hypern import Hypern
import json

app = Hypern()

# Collection endpoints
@app.get("/api/users")
def list_users(request, response):
    """List all users"""
    users = []  # Fetch from database
    response.status(200)
    response.body_str(json.dumps(users))
    response.finish()

@app.post("/api/users")
def create_user(request, response):
    """Create a new user"""
    # Parse and validate request body
    response.status(201)
    response.body_str(json.dumps({"id": 1, "created": True}))
    response.finish()

# Resource endpoints
@app.get("/api/users/{id}")
def get_user(request, response):
    """Get a specific user"""
    user_id = request.path_params.get("id")
    # Fetch user
    response.status(200)
    response.body_str(json.dumps({"id": user_id}))
    response.finish()

@app.put("/api/users/{id}")
def update_user(request, response):
    """Update a user (full replacement)"""
    user_id = request.path_params.get("id")
    # Update user
    response.status(200)
    response.body_str(json.dumps({"id": user_id, "updated": True}))
    response.finish()

@app.patch("/api/users/{id}")
def patch_user(request, response):
    """Partially update a user"""
    user_id = request.path_params.get("id")
    # Partial update
    response.status(200)
    response.body_str(json.dumps({"id": user_id, "patched": True}))
    response.finish()

@app.delete("/api/users/{id}")
def delete_user(request, response):
    """Delete a user"""
    user_id = request.path_params.get("id")
    # Delete user
    response.status(204)
    response.finish()
```

### REST Resource Pattern

| HTTP Method | Route | Action | Status Code |
|-------------|-------|--------|-------------|
| GET | `/resources` | List all | 200 |
| GET | `/resources/{id}` | Get one | 200 |
| POST | `/resources` | Create | 201 |
| PUT | `/resources/{id}` | Update (full) | 200 |
| PATCH | `/resources/{id}` | Update (partial) | 200 |
| DELETE | `/resources/{id}` | Delete | 204 |

## Route Priority

Routes are matched in the order they are registered:

```python
# This will match first
@app.get("/users/admin")
def admin_handler(request, response):
    response.status(200)
    response.body_str("Admin user")
    response.finish()

# This will only match if above doesn't
@app.get("/users/{id}")
def user_handler(request, response):
    user_id = request.path_params.get("id")
    response.status(200)
    response.body_str(f"User {user_id}")
    response.finish()
```

**Best Practice:** Register specific routes before generic ones.

## Special Routes

### Health Check

```python
@app.get("/health")
def health_check(request, response):
    response.status(200)
    response.header("Content-Type", "application/json")
    response.body_str(json.dumps({
        "status": "healthy",
        "timestamp": time.time()
    }))
    response.finish()
```

### Root Route

```python
@app.get("/")
def root(request, response):
    response.status(200)
    response.header("Content-Type", "text/html")
    response.body_str("<h1>Welcome to the API</h1>")
    response.finish()
```

### Catch-All Route

Handle all unmatched routes:

```python
@app.get("/{path:path}")
def catch_all(request, response):
    path = request.path
    response.status(404)
    response.body_str(f"Path not found: {path}")
    response.finish()
```

## Complete Example

Here's a complete example with organized routes:

```python
from hypern import Hypern, Request, Response
import json

app = Hypern()

# ============ Home Routes ============
@app.get("/")
def home(request: Request, response: Response):
    response.status(200)
    response.header("Content-Type", "text/html")
    response.body_str("<h1>API Home</h1>")
    response.finish()

@app.get("/health")
def health(request: Request, response: Response):
    response.status(200)
    response.header("Content-Type", "application/json")
    response.body_str(json.dumps({"status": "healthy"}))
    response.finish()

# ============ User Routes ============
@app.get("/api/users")
def list_users(request: Request, response: Response):
    users = [
        {"id": 1, "name": "Alice"},
        {"id": 2, "name": "Bob"}
    ]
    response.status(200)
    response.header("Content-Type", "application/json")
    response.body_str(json.dumps(users))
    response.finish()

@app.get("/api/users/{id}")
def get_user(request: Request, response: Response):
    user_id = request.path_params.get("id")
    user = {"id": user_id, "name": "User Name"}
    response.status(200)
    response.header("Content-Type", "application/json")
    response.body_str(json.dumps(user))
    response.finish()

@app.post("/api/users")
def create_user(request: Request, response: Response):
    # Parse request body
    new_user = {"id": 3, "name": "Charlie"}
    response.status(201)
    response.header("Content-Type", "application/json")
    response.body_str(json.dumps(new_user))
    response.finish()

@app.put("/api/users/{id}")
def update_user(request: Request, response: Response):
    user_id = request.path_params.get("id")
    updated_user = {"id": user_id, "name": "Updated Name"}
    response.status(200)
    response.header("Content-Type", "application/json")
    response.body_str(json.dumps(updated_user))
    response.finish()

@app.delete("/api/users/{id}")
def delete_user(request: Request, response: Response):
    response.status(204)
    response.finish()

# ============ Product Routes ============
@app.get("/api/products")
def list_products(request: Request, response: Response):
    page = request.query_params.get("page", "1")
    limit = request.query_params.get("limit", "10")
    
    products = [
        {"id": 1, "name": "Product A"},
        {"id": 2, "name": "Product B"}
    ]
    
    response.status(200)
    response.header("Content-Type", "application/json")
    response.body_str(json.dumps({
        "products": products,
        "page": page,
        "limit": limit
    }))
    response.finish()

@app.get("/api/products/{id}")
def get_product(request: Request, response: Response):
    product_id = request.path_params.get("id")
    product = {"id": product_id, "name": "Product Name"}
    response.status(200)
    response.header("Content-Type", "application/json")
    response.body_str(json.dumps(product))
    response.finish()

if __name__ == "__main__":
    app.start(port=8000)
```

## Best Practices

### 1. Use Consistent Naming

```python
# Good
@app.get("/api/users")
@app.get("/api/products")

# Avoid
@app.get("/api/users")
@app.get("/Products")  # Inconsistent capitalization
```

### 2. Use Plural Resource Names

```python
# Good
@app.get("/api/users/{id}")
@app.get("/api/products/{id}")

# Avoid
@app.get("/api/user/{id}")
@app.get("/api/product/{id}")
```

### 3. Version Your API

```python
@app.get("/api/v1/users")
@app.get("/api/v2/users")
```

### 4. Use Appropriate HTTP Methods

```python
# Retrieve - GET
@app.get("/users")

# Create - POST
@app.post("/users")

# Update - PUT/PATCH
@app.put("/users/{id}")

# Delete - DELETE
@app.delete("/users/{id}")
```

### 5. Return Appropriate Status Codes

```python
# 200 - Success
response.status(200)

# 201 - Created
response.status(201)

# 204 - No Content
response.status(204)

# 400 - Bad Request
response.status(400)

# 404 - Not Found
response.status(404)

# 500 - Server Error
response.status(500)
```

## Next Steps

- [Request Handling](requests.md) - Learn about processing requests
- [Response Building](responses.md) - Build responses effectively
- [Middleware](middleware.md) - Add middleware to routes
- [Error Handling](error-handling.md) - Handle errors gracefully
- [Examples](../examples/rest-api.md) - See real-world examples

## Summary

Routing in Hypern is:

- **Flexible** - Multiple ways to define routes
- **Powerful** - Support for parameters and patterns
- **Organized** - Easy to structure and maintain
- **RESTful** - Follow REST conventions
- **Type-safe** - Full type hint support

Master routing to build well-structured APIs with Hypern! 🚀