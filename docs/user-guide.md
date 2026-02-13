# Hypern User Guide

A comprehensive guide to building high-performance web applications with Hypern - the Express.js-style Python web framework powered by Rust (Axum/Tokio).

## Table of Contents

1. [Getting Started](#getting-started)
2. [Routing](#routing)
3. [Request Handling](#request-handling)
4. [Response Methods](#response-methods)
5. [Middleware](#middleware)
6. [Server-Sent Events (SSE)](#server-sent-events-sse)
7. [Validation](#validation)
8. [Dependency Injection](#dependency-injection)
9. [Background Tasks](#background-tasks)
10. [Error Handling](#error-handling)
11. [File Uploads](#file-uploads)
12. [OpenAPI Documentation](#openapi-documentation)
13. [Development Mode](#development-mode)
14. [Best Practices](#best-practices)

---

## Getting Started

### Installation

```bash
# Install with pip
pip install hypern

# Or build from source with maturin
pip install maturin
maturin develop --release
```

### Your First Application

```python
from hypern import Hypern

app = Hypern()

@app.get("/")
def home(req, res, ctx):
    res.json({"message": "Hello, World!"})

@app.get("/users/:id")
def get_user(req, res, ctx):
    user_id = req.param("id")
    res.json({"user_id": user_id})

if __name__ == "__main__":
    app.start(host="0.0.0.0", port=8000)
```

### Running the Server

```bash
python app.py
# Server running at http://0.0.0.0:8000
```

---

## Routing

### HTTP Methods

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

### Route Parameters

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

### Router Groups

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

---

## Request Handling

### Accessing Request Data

```python
@app.post("/example")
def example(req, res, ctx):
    # Path parameters
    param_value = req.param("name")
    
    # Query string parameters
    query_value = req.query("search")
    all_queries = req.queries()  # Dict of all query params
    
    # Headers
    auth = req.header("Authorization")
    content_type = req.header("Content-Type")
    all_headers = req.headers()
    
    # Body
    json_body = req.json()           # Parse JSON body
    text_body = req.text()           # Raw text body
    bytes_body = req.body()          # Raw bytes
    form_data = req.form()           # Parse form data
    
    # Cookies
    session = req.cookie("session_id")
    
    # Request metadata
    method = req.method              # HTTP method
    path = req.path                  # Request path
    url = req.url                    # Full URL
    
    res.json({"received": True})
```

### Async Handlers

Hypern supports both sync and async handlers:

```python
import asyncio

@app.get("/sync")
def sync_handler(req, res, ctx):
    res.json({"type": "sync"})

@app.get("/async")
async def async_handler(req, res, ctx):
    await asyncio.sleep(0.1)  # Async operation
    res.json({"type": "async"})
```

---

## Response Methods

### Setting Status and Headers

```python
@app.get("/example")
def example(req, res, ctx):
    # Method chaining
    res.status(200) \
       .header("X-Custom", "value") \
       .header("X-Another", "value2") \
       .json({"ok": True})
```

### Response Types

```python
# JSON Response
@app.get("/json")
def json_response(req, res, ctx):
    res.json({
        "string": "value",
        "number": 42,
        "array": [1, 2, 3],
        "nested": {"key": "value"}
    })

# HTML Response
@app.get("/html")
def html_response(req, res, ctx):
    res.html("<html><body><h1>Hello!</h1></body></html>")

# Plain Text Response
@app.get("/text")
def text_response(req, res, ctx):
    res.text("Plain text content")

# XML Response
@app.get("/xml")
def xml_response(req, res, ctx):
    res.xml("<root><item>value</item></root>")

# Generic Send (auto-detects type)
@app.get("/send")
def send_response(req, res, ctx):
    res.send("Auto-detected content")  # Sends as HTML
    # res.send({"key": "value"})       # Sends as JSON
    # res.send(b"binary")              # Sends as bytes
```

### Redirects

```python
@app.get("/old-page")
def redirect_example(req, res, ctx):
    res.redirect("/new-page", 302)  # 302 Found (default)
    # res.redirect("/new-page", 301)  # 301 Permanent

@app.get("/new-page")
def new_page(req, res, ctx):
    res.json({"page": "new"})
```

### Cookies

```python
@app.get("/set-cookie")
def set_cookie(req, res, ctx):
    res.cookie(
        "session",
        "abc123",
        max_age=3600,        # Expires in 1 hour
        path="/",
        domain=None,
        secure=True,         # HTTPS only
        http_only=True,      # No JavaScript access
        same_site="Strict"   # CSRF protection
    )
    res.json({"cookie": "set"})

@app.get("/clear-cookie")
def clear_cookie(req, res, ctx):
    res.clear_cookie("session")
    res.json({"cookie": "cleared"})
```

### Cache Control

```python
@app.get("/cached")
def cached_response(req, res, ctx):
    res.cache_control(max_age=3600, private=False)
    res.json({"cached": True})

@app.get("/no-cache")
def no_cache_response(req, res, ctx):
    res.no_cache()
    res.json({"cached": False})
```

### File Downloads

```python
@app.get("/download/:filename")
def download_file(req, res, ctx):
    filename = req.param("filename")
    res.send_file(f"./files/{filename}")

@app.get("/attachment")
def attachment(req, res, ctx):
    res.attachment("report.pdf")
    res.send_file("./reports/report.pdf")
```

### CORS Headers

```python
@app.get("/api/data")
def cors_example(req, res, ctx):
    res.cors(
        origin="https://example.com",
        methods=["GET", "POST"],
        headers=["Content-Type", "Authorization"],
        credentials=True,
        max_age=3600
    )
    res.json({"data": "value"})
```

---

## Middleware

### Global Middleware

```python
from hypern import Hypern

app = Hypern()

# Logging middleware
async def logging_middleware(req, res, ctx, next):
    print(f"Request: {req.method} {req.path}")
    await next()
    print(f"Response sent")

# Authentication middleware
async def auth_middleware(req, res, ctx, next):
    token = req.header("Authorization")
    if not token:
        res.status(401).json({"error": "Unauthorized"})
        return
    
    # Validate token and set user in context
    ctx.set("user_id", "user-123")
    await next()

# Apply middleware globally
app.use(logging_middleware)
app.use(auth_middleware)

@app.get("/protected")
def protected(req, res, ctx):
    user_id = ctx.get("user_id")
    res.json({"user_id": user_id})
```

### Route-Specific Middleware

```python
async def admin_only(req, res, ctx, next):
    role = ctx.get("role")
    if role != "admin":
        res.status(403).json({"error": "Forbidden"})
        return
    await next()

@app.get("/admin", middleware=[admin_only])
def admin_panel(req, res, ctx):
    res.json({"admin": True})
```

### Built-in Middleware

```python
from hypern import CORSMiddleware, RateLimitMiddleware

# CORS Middleware
cors = CORSMiddleware(
    allow_origins=["https://example.com", "https://app.example.com"],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
    allow_credentials=True,
    max_age=86400
)
app.use(cors)

# Rate Limiting Middleware
rate_limit = RateLimitMiddleware(
    max_requests=100,
    window_seconds=60
)
app.use(rate_limit)
```

---

## Server-Sent Events (SSE)

### Basic SSE

```python
from hypern import Hypern, SSEEvent

app = Hypern()

@app.get("/events")
def sse_events(req, res, ctx):
    # Create multiple SSE events
    events = [
        SSEEvent("Connected!", event="connect"),
        SSEEvent("Hello World", event="message", id="1"),
        SSEEvent("Goodbye", event="close", id="2"),
    ]
    
    # Send all events as SSE response
    res.sse(events)

# Client-side JavaScript:
# const eventSource = new EventSource('/events');
# eventSource.addEventListener('message', (e) => console.log(e.data));
```

### Single SSE Event

```python
@app.get("/notification")
def single_notification(req, res, ctx):
    res.sse_event(
        data="New notification!",
        event="notification",
        id="notif-1"
    )
```

### SSE Event Properties

```python
from hypern import SSEEvent

# Basic event (data only)
event = SSEEvent("Hello World")

# Named event
event = SSEEvent("User logged in", event="user_login")

# Event with ID (for client reconnection)
event = SSEEvent("Data update", id="12345", event="update")

# Event with retry (reconnection time in ms)
event = SSEEvent("Data", retry=5000)

# Full event
event = SSEEvent(
    "Full event data",
    id="evt-1",
    event="custom_event",
    retry=3000
)

# Get formatted SSE string
formatted = event.format()
# Output: "id: evt-1\nevent: custom_event\nretry: 3000\ndata: Full event data\n\n"

# Get as bytes
event_bytes = event.to_bytes()
```

### SSE Stream (for building events)

```python
from hypern import SSEStream

# Create a stream to build events
stream = app.sse(buffer_size=100)

# Send different types of events
stream.send_data("Plain data")
stream.send_event("update", '{"count": 42}')
stream.keepalive()  # Send comment for keepalive

# Check stream state
print(stream.event_count())  # Number of events sent
print(stream.is_closed())    # Check if closed

# Close when done
stream.close()
```

### Manual SSE Headers

```python
@app.get("/manual-sse")
def manual_sse(req, res, ctx):
    # Set SSE headers manually
    res.sse_headers()
    
    # Build custom response body
    event = SSEEvent("Custom data", event="custom")
    res.body_str(event.format())
    res.finish()
```

---

## Validation

### Using msgspec for Validation

```python
import msgspec
from hypern import Hypern
from hypern.validation import validate, validate_body, validate_query

app = Hypern()

# Define models with msgspec
class CreateUserInput(msgspec.Struct):
    name: str
    email: str
    age: int

class QueryParams(msgspec.Struct):
    page: int = 1
    limit: int = 10
    search: str = ""

# Validate request body
@app.post("/users")
@validate_body(CreateUserInput)
def create_user(req, res, ctx, body: CreateUserInput):
    res.json({
        "name": body.name,
        "email": body.email,
        "age": body.age
    })

# Validate query parameters
@app.get("/users")
@validate_query(QueryParams)
def list_users(req, res, ctx, query: QueryParams):
    res.json({
        "page": query.page,
        "limit": query.limit,
        "search": query.search
    })

# Validate both body and query
@app.post("/search")
@validate(body=CreateUserInput, query=QueryParams)
async def search(req, res, ctx, body: CreateUserInput, query: QueryParams):
    res.json({"body": body, "query": query})
```

### Nested Validation

```python
class Address(msgspec.Struct):
    street: str
    city: str
    zip_code: str

class UserProfile(msgspec.Struct):
    name: str
    email: str
    address: Address
    tags: list[str] = []

@app.post("/profiles")
@validate_body(UserProfile)
def create_profile(req, res, ctx, body: UserProfile):
    res.json({
        "name": body.name,
        "city": body.address.city
    })
```

### Manual Validation

```python
from hypern.validation import Validator

validator = Validator(CreateUserInput)

@app.post("/users")
def create_user(req, res, ctx):
    try:
        body = validator.validate(req.json())
        res.json({"valid": True, "data": body})
    except Exception as e:
        res.status(400).json({"error": str(e)})
```

---

## Dependency Injection

### Registering Dependencies

```python
from hypern import Hypern

app = Hypern()

# Singleton - shared instance
app.singleton("config", {
    "debug": True,
    "database_url": "postgresql://..."
})

# Factory - new instance each time
def create_database_connection():
    return {"connection": "new"}

app.factory("database", create_database_connection)
```

### Injecting Dependencies

```python
@app.get("/config")
@app.inject("config")
def get_config(req, res, ctx, config):
    res.json(config)

@app.get("/data")
@app.inject("database")
@app.inject("config")
def get_data(req, res, ctx, database, config):
    res.json({
        "database": database,
        "debug": config["debug"]
    })
```

### Request Context

```python
@app.get("/user")
def get_user(req, res, ctx):
    # Context is request-scoped
    ctx.set("user_id", "user-123")
    ctx.set("role", "admin")
    
    # Get values
    user_id = ctx.get("user_id")
    has_role = ctx.has("role")
    
    # Authentication helpers
    ctx.set_auth("user-123", roles=["admin", "user"])
    ctx.has_role("admin")  # True
    
    # Request timing
    elapsed = ctx.elapsed_ms()  # Milliseconds since request start
    
    res.json({
        "user_id": user_id,
        "elapsed": elapsed
    })
```

---

## Background Tasks

### Using the Background Decorator

```python
from hypern import Hypern

app = Hypern()

@app.background(priority="normal")
def send_email(to: str, subject: str, body: str):
    # This runs in a background thread
    print(f"Sending email to {to}")
    # ... send email logic

@app.post("/notify")
def notify_user(req, res, ctx):
    data = req.json()
    
    # Submit background task
    send_email(data["email"], "Hello!", "Welcome to our app")
    
    # Respond immediately
    res.json({"status": "queued"})
```

### Programmatic Task Submission

```python
def process_data(data):
    # Heavy processing
    return {"processed": True}

@app.post("/process")
def start_processing(req, res, ctx):
    data = req.json()
    
    # Submit task and get task ID
    task_id = app.submit_task(
        process_data,
        args=(data,)
    )
    
    res.json({"task_id": task_id})

@app.get("/tasks/:task_id")
def get_task_status(req, res, ctx):
    task_id = req.param("task_id")
    result = app.get_task(task_id)
    
    if result:
        res.json({
            "status": result.status.name,
            "result": result.result,
            "error": result.error
        })
    else:
        res.status(404).json({"error": "Task not found"})
```

---

## Error Handling

### Custom Error Handlers

```python
from hypern import Hypern, HTTPException, NotFound, BadRequest

app = Hypern()

# Handle specific exception types
@app.errorhandler(NotFound)
def handle_not_found(req, res, error):
    res.status(404).json({
        "error": "Resource not found",
        "path": req.path
    })

@app.errorhandler(BadRequest)
def handle_bad_request(req, res, error):
    res.status(400).json({
        "error": "Bad request",
        "detail": error.detail
    })

# Catch-all handler
@app.errorhandler(Exception)
def handle_error(req, res, error):
    res.status(500).json({
        "error": "Internal server error"
    })
```

### Raising HTTP Exceptions

```python
from hypern import HTTPException, NotFound, BadRequest

@app.get("/users/:id")
def get_user(req, res, ctx):
    user_id = req.param("id")
    user = find_user(user_id)  # Your logic
    
    if not user:
        raise NotFound(f"User {user_id} not found")
    
    res.json(user)

@app.post("/users")
def create_user(req, res, ctx):
    body = req.json()
    
    if not body.get("email"):
        raise BadRequest("Email is required")
    
    res.json({"created": True})
```

---

## File Uploads

### Handling File Uploads

```python
@app.post("/upload")
async def upload_file(req, res, ctx):
    # Get form data with files
    form = await req.form()
    
    # Access uploaded file
    file = form.get_file("document")
    
    if file:
        # File properties
        filename = file.filename
        content_type = file.content_type
        size = file.size
        content = file.content  # bytes
        
        # Save file
        with open(f"./uploads/{filename}", "wb") as f:
            f.write(content)
        
        res.json({
            "filename": filename,
            "size": size,
            "content_type": content_type
        })
    else:
        res.status(400).json({"error": "No file uploaded"})
```

### Multiple File Uploads

```python
@app.post("/upload-multiple")
async def upload_multiple(req, res, ctx):
    form = await req.form()
    
    uploaded = []
    for file in form.get_files("files"):
        with open(f"./uploads/{file.filename}", "wb") as f:
            f.write(file.content)
        uploaded.append(file.filename)
    
    res.json({"uploaded": uploaded})
```

---

## OpenAPI Documentation

### Setting Up OpenAPI

```python
from hypern import Hypern

app = Hypern()

# Enable OpenAPI documentation
app.setup_openapi(
    title="My API",
    version="1.0.0",
    description="My awesome API documentation"
)

# Routes will be documented automatically
@app.get("/users")
def list_users(req, res, ctx):
    """List all users."""
    res.json({"users": []})

@app.post("/users")
def create_user(req, res, ctx):
    """Create a new user."""
    res.status(201).json({"id": 1})
```

### Accessing Documentation

Once enabled, documentation is available at:
- `/docs` - Swagger UI
- `/redoc` - ReDoc
- `/openapi.json` - OpenAPI JSON spec

### Custom Documentation Paths

```python
app.setup_openapi(
    title="My API",
    version="1.0.0",
    description="My API",
    docs_path="/swagger",
    redoc_path="/documentation",
    openapi_path="/api/openapi.json"
)
```

---

## Development Mode

### Auto-Reload

Enable auto-reload for development:

```python
from hypern import Hypern

app = Hypern()

@app.get("/")
def home(req, res, ctx):
    res.json({"message": "Hello!"})

if __name__ == "__main__":
    # Development mode with auto-reload
    app.run_dev(
        host="0.0.0.0",
        port=8000,
        watch_dirs=[".", "./modules"],  # Directories to watch
        watch_extensions=[".py", ".json", ".yaml"]  # File types to watch
    )
```

### Lifecycle Hooks

```python
@app.on_startup
async def startup():
    print("Server starting up...")
    # Initialize database connections, etc.

@app.on_shutdown
async def shutdown():
    print("Server shutting down...")
    # Cleanup resources
```

---

## Best Practices

### Project Structure

```
myapp/
├── app.py              # Main application
├── routes/
│   ├── __init__.py
│   ├── users.py        # User routes
│   └── products.py     # Product routes
├── middleware/
│   ├── __init__.py
│   └── auth.py         # Authentication middleware
├── models/
│   ├── __init__.py
│   └── user.py         # Data models
├── services/
│   ├── __init__.py
│   └── email.py        # Business logic
└── tests/
    └── test_app.py
```

### Modular Route Organization

```python
# routes/users.py
from hypern import Router

users = Router(prefix="/users")

@users.get("/")
def list_users(req, res, ctx):
    res.json({"users": []})

@users.get("/:id")
def get_user(req, res, ctx):
    res.json({"user": {}})

# app.py
from routes.users import users

app.mount(users)
```

### Error Handling Best Practices

```python
# Always validate input
@app.post("/users")
@validate_body(CreateUserInput)
def create_user(req, res, body):
    try:
        user = create_user_in_db(body)
        res.status(201).json(user)
    except DuplicateError:
        res.status(409).json({"error": "User already exists"})
    except Exception as e:
        res.status(500).json({"error": "Internal error"})
```

### Security Best Practices

1. **Always validate input** - Use msgspec validation
2. **Use HTTPS in production** - Enable TLS
3. **Set secure cookies** - Use `secure=True, http_only=True`
4. **Enable CORS properly** - Don't use `*` in production
5. **Rate limit** - Use RateLimitMiddleware
6. **Sanitize output** - Escape HTML in responses

### Performance Tips

1. **Use async handlers** for I/O-bound operations
2. **Use background tasks** for heavy processing
3. **Enable response caching** with `cache_control()`
4. **Use SSE** instead of polling for real-time updates
5. **Profile your code** to find bottlenecks

---

## API Reference

### Hypern Class

```python
class Hypern:
    def __init__(self)
    
    # HTTP Methods
    def get(path: str, middleware: list = None)
    def post(path: str, middleware: list = None)
    def put(path: str, middleware: list = None)
    def patch(path: str, middleware: list = None)
    def delete(path: str, middleware: list = None)
    def options(path: str, middleware: list = None)
    def head(path: str, middleware: list = None)
    
    # Middleware
    def use(middleware: Callable)
    def mount(router: Router)
    
    # DI
    def singleton(name: str, value: Any)
    def factory(name: str, factory: Callable)
    def inject(name: str)
    
    # SSE/Streaming
    def sse(buffer_size: int = 100) -> SSEStream
    def stream(content_type: str, buffer_size: int) -> StreamingResponse
    
    # Background Tasks
    def background(priority: str = "normal")
    def submit_task(handler, args, priority) -> str
    def get_task(task_id: str) -> TaskResult
    
    # Lifecycle
    def on_startup
    def on_shutdown
    
    # Server
    def start(host, port, num_processes, worker_threads)
    def run_dev(host, port, watch_dirs, watch_extensions)
    
    # OpenAPI
    def setup_openapi(title, version, description, docs_path, redoc_path, openapi_path)
```

### Response Class

```python
class Response:
    # Status & Headers
    def status(code: int) -> Response
    def header(key: str, value: str) -> Response
    def headers(dict) -> Response
    
    # Body
    def json(data: Any) -> Response
    def html(content: str) -> Response
    def text(content: str) -> Response
    def xml(content: str) -> Response
    def send(data: Any) -> Response
    def body(bytes) -> Response
    def body_str(str) -> Response
    
    # SSE
    def sse(events: list[SSEEvent]) -> Response
    def sse_event(data, event, id) -> Response
    def sse_headers() -> Response
    
    # Cookies
    def cookie(name, value, **options) -> Response
    def clear_cookie(name) -> Response
    
    # Cache
    def cache_control(**options) -> Response
    def no_cache() -> Response
    
    # Redirects
    def redirect(url: str, status: int = 302) -> Response
    
    # CORS
    def cors(**options) -> Response
    
    # Files
    def send_file(path, filename, content_type) -> Response
    def download(path, filename) -> Response
    def attachment(filename) -> Response
```

---

## License

MIT License - See LICENSE file for details.
