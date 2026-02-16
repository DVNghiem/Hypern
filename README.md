
# Hypern

**A High-Performance Python Web Framework with Rust Runtime**

Hypern is a flexible, open-source web framework that combines the ease of Python with the raw performance of [Rust](https://github.com/rust-lang/rust). Built on top of production-ready Rust libraries, Hypern empowers you to rapidly develop high-performance web applications, RESTful APIs, and real-time systems.

With Hypern, you get seamless async/await support, built-in WebSocket and SSE capabilities, powerful task scheduling, database connection pooling, and comprehensive middleware support—all while writing familiar Python code with the performance characteristics of Rust.

### 🏁 Get started

### ⚙️ To Develop Locally

- Setup a virtual environment:
```
python3 -m venv venv
source venv/bin/activate
```
- Install required packages

```
pip install pre-commit poetry maturin
```
- Install development dependencies
```
poetry install --with dev --with test
```
- Install pre-commit git hooks
```
pre-commit install
```
- Build & install Rust package
```
maturin develop
```

## 🚀 Quick Start

### Basic Example

```python
# main.py
from hypern import Hypern

app = Hypern()

@app.get("/")
async def home(req, res, ctx):
    res.json({"message": "Hello, World!"})

@app.get("/users/:id")
async def get_user(req, res, ctx):
    user_id = req.param("id")
    res.json({"id": user_id, "name": "John Doe"})

@app.post("/users")
async def create_user(req, res, ctx):
    body = req.json()
    res.status(201).json({"created": body})

if __name__ == "__main__":
    app.listen(port=5000, host="0.0.0.0")
```

```bash
$ python3 main.py
```

Your server will be available at `http://localhost:5000`

### OpenAPI/Swagger Documentation

Enable built-in API documentation:

```python
app = Hypern()

# Enable OpenAPI
app.setup_openapi(
    title="My API",
    version="1.0.0",
    description="My awesome API"
)

# Your routes here...
```

Access documentation at:
- **Swagger UI**: `http://localhost:5000/docs`
- **ReDoc**: `http://localhost:5000/redoc`
- **OpenAPI Spec**: `http://localhost:5000/openapi.json` 

## ⚙️ Server Configuration

### Production Server

The `listen()` method is a simplified wrapper for starting the server:

```python
app.listen(
    port=5000,                   # Port number
    host="0.0.0.0",             # Host address to bind to
    callback=None,               # Optional callback after server starts
)
```

For more control, use the `start()` method:

```python
app.start(
    host="0.0.0.0",             # Host address to bind to
    port=5000,                   # Port number
    num_processes=1,             # Number of worker processes (multi-core)
    workers_threads=1,           # Number of worker threads per process
    max_blocking_threads=16,     # Max blocking threads for sync operations
    max_connections=10000,       # Max concurrent connections
)
```

### Development Server

For development with auto-reload on file changes:

```python
app.run_dev(
    port=3000,                   # Port number
    host="0.0.0.0",             # Host address
    reload=True,                 # Enable auto-reload (default: True)
    reload_dirs=[".", "./src"],  # Directories to watch
    reload_delay=0.5,            # Debounce delay in seconds
)
```

**Example - Multi-process production server:**

```python
# Utilize all CPU cores with multiple processes
app.start(
    port=8000, 
    num_processes=4,          # 4 processes
    workers_threads=2,        # 2 threads per process
    max_blocking_threads=32
)
```


## 💡 Features

### ⚡ High Performance
- **Rust-powered core** with Python flexibility
- **Multi-process architecture** for optimal CPU utilization across cores
- **Async/await support** for non-blocking I/O operations
- **Zero-copy** data handling where possible
- **Optimized routing** with efficient path matching

### 🌐 Web Capabilities
- **RESTful API** routing with decorators (`@app.get`, `@app.post`, etc.)
- **WebSocket support** with rooms and broadcasting
- **Server-Sent Events (SSE)** for real-time streaming
- **File uploads** with multipart form data handling
- **Static file serving** with caching headers
- **Streaming responses** for large data transfers

### 🔌 Integration & Extensions
- **Dependency Injection** (DI) with singleton and factory patterns
- **Middleware support** with before/after request hooks
  - CORS middleware
  - Rate limiting middleware
  - Compression middleware
  - Security headers middleware
  - Request ID tracking
  - Timeout middleware
  - Logging middleware
  - Basic authentication middleware
- **Database connection pooling** for PostgreSQL, MySQL, SQLite
- **Background task execution** with TaskExecutor
- **Task scheduling** with cron expressions and intervals
- **Router mounting** for modular application structure

### 🛠 Development Experience
- **Type hints** and comprehensive IDE support
- **Built-in Swagger/OpenAPI** documentation (Swagger UI + ReDoc)
- **Hot reload** during development
- **Comprehensive error handling** with custom exception handlers
- **Request validation** decorators for query params, body, and path params
- **Detailed logging** with configurable levels

### 🔒 Security & Authentication
- **JWT Authentication** with token validation
- **API Key authentication** for service-to-service communication
- **Role-Based Access Control (RBAC)** with decorators
- **Permission-based authorization** (`@requires_role`, `@requires_permission`)
- **CORS configuration** for cross-origin requests
- **Rate limiting** to prevent abuse
- **Request validation** to prevent malformed input
- **Security headers** middleware (HSTS, CSP, etc.)

---

## 📚 Comprehensive Examples

### Middleware

```python
from hypern import Hypern
from hypern.middleware import CorsMiddleware, RateLimitMiddleware, LogMiddleware

app = Hypern()

# Add CORS support
cors = CorsMiddleware(
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"]
)
app.use(cors)

# Add rate limiting (100 requests per minute)
rate_limit = RateLimitMiddleware(max_requests=100, window_seconds=60)
app.use(rate_limit)

# Add request logging
app.use(LogMiddleware())

# Custom middleware with before/after hooks
@app.before_request
async def log_request(req, res, ctx):
    print(f"→ {req.method} {req.path}")

@app.after_request
async def add_server_header(req, res, ctx):
    res.header("X-Powered-By", "Hypern")
```

### WebSocket Support

```python
from hypern import Hypern
from hypern.websocket import WebSocket, WebSocketRoom, WebSocketDisconnect

app = Hypern()
chat_room = WebSocketRoom()

@app.ws("/chat")
async def chat_handler(ws: WebSocket):
    await ws.accept()
    chat_room.join(ws)
    
    try:
        while True:
            message = await ws.receive_text()
            # Broadcast to all connected clients
            chat_room.broadcast(f"User: {message}")
    except WebSocketDisconnect:
        chat_room.leave(ws)
```

### Server-Sent Events (SSE)

```python
from hypern import Hypern, SSEEvent

app = Hypern()

@app.get("/events")
async def stream_events(req, res, ctx):
    events = [
        SSEEvent("Connected!", event="greeting"),
        SSEEvent('{"price": 100}', event="update"),
        SSEEvent("System online", event="status")
    ]
    res.sse(events)

# For continuous streaming
@app.get("/live")
async def live_stream(req, res, ctx):
    stream = app.sse()
    stream.send_event("message", "Hello!")
    stream.send_data("Plain data")
    # Return collected events
```

### Database Integration

```python
from hypern import Hypern
from hypern.database import Database, db, finalize_db

app = Hypern()

# Configure database connection pool (lazy initialization)
Database.configure(
    url="postgresql://user:pass@localhost:5432/mydb",
    max_size=20,
    min_idle=2,
    connect_timeout_secs=30,
    alias="default"  # Optional, defaults to "default"
)

# Multiple databases
Database.configure(
    url="postgresql://user:pass@localhost:5432/analytics",
    max_size=5,
    alias="analytics"
)

@app.get("/users")
async def get_users(req, res, ctx):
    # Get database session for this request
    session = db(ctx)
    users = session.query("SELECT * FROM users")
    res.json(users)

@app.post("/users")
async def create_user(req, res, ctx):
    session = db(ctx)
    body = req.json()
    
    # With transaction
    with session.transaction():
        user_id = session.query_one(
            "INSERT INTO users (name, email) VALUES ($1, $2) RETURNING id",
            [body["name"], body["email"]]
        )["id"]
        
        session.execute(
            "INSERT INTO logs (user_id, action) VALUES ($1, $2)",
            [user_id, "user_created"]
        )
    
    res.status(201).json({"id": user_id})

@app.get("/analytics")
async def get_analytics(req, res, ctx):
    # Use named database
    analytics = db(ctx, alias="analytics")
    logs = analytics.query("SELECT * FROM logs ORDER BY created_at DESC LIMIT 100")
    res.json({"logs": logs})

# Manual cleanup (usually automatic)
@app.after_request
async def cleanup_db(req, res, ctx):
    finalize_db(ctx)  # Finalizes all databases for this request
```

### Background Tasks

```python
from hypern import Hypern, background, submit_task, get_task

app = Hypern()

# Using decorator
@background()
def send_email(to: str, subject: str, body: str):
    # This runs in background
    print(f"Sending email to {to}")
    # ... email sending logic
    return {"status": "sent"}

@app.post("/notify")
async def notify_user(req, res, ctx):
    data = req.json()
    # Submit background task
    send_email(data["email"], "Welcome!", "Thanks for joining!")
    res.json({"status": "queued"})

# Programmatic submission with task tracking
@app.post("/process")
async def process_data(req, res, ctx):
    def heavy_computation(data):
        # CPU-intensive work
        return {"result": "processed"}
    
    task_id = submit_task(heavy_computation, args=(req.json(),))
    res.json({"task_id": task_id})

@app.get("/task/:id")
async def check_task(req, res, ctx):
    task_id = req.param("id")
    result = get_task(task_id)
    
    if result and result.is_success():
        res.json({"status": "completed", "result": result.result})
    else:
        res.json({"status": "pending"})
```

### Task Scheduling

```python
from hypern import Hypern
from hypern.scheduler import periodic, RetryPolicy

app = Hypern()

# Scheduled task - runs every 30 seconds
@periodic(seconds=30)
def health_check():
    print("Health check running...")

# Cron-style scheduling - every day at 3 AM
@app.scheduler.cron("0 3 * * *")
def nightly_cleanup():
    print("Running nightly cleanup...")

# With retry policy
@app.scheduler.task(retry=RetryPolicy(max_retries=3, backoff=2.0))
def flaky_task():
    # This will retry up to 3 times with exponential backoff
    pass
```

### Authentication & Authorization

```python
from hypern import Hypern
from hypern.auth import JWTAuth, requires_role, requires_permission

app = Hypern()

# JWT Authentication
jwt = JWTAuth(secret="your-secret-key", algorithm="HS256")

@app.post("/login")
async def login(req, res, ctx):
    body = req.json()
    # Validate credentials...
    
    token = jwt.encode(
        {"sub": "user-1", "user_id": 123, "roles": ["admin"]},
        expiry_seconds=3600  # 1 hour
    )
    res.json({"token": token})

@app.get("/protected")
@jwt.required
async def protected_route(req, res, ctx):
    # User payload is available in ctx
    user = ctx.get("auth_user")
    res.json({"user": user})

# Manual token verification
@app.get("/verify")
async def verify_token(req, res, ctx):
    token = req.header("Authorization").replace("Bearer ", "")
    try:
        payload = jwt.decode(token)
        res.json({"valid": True, "payload": payload})
    except Exception as e:
        res.status(401).json({"error": str(e)})

# Role-based access control
@app.get("/admin")
@jwt.required
@requires_role("admin")
async def admin_only(req, res, ctx):
    res.json({"message": "Admin area"})

@app.delete("/users/:id")
@jwt.required
@requires_permission("users:delete")
async def delete_user(req, res, ctx):
    res.json({"deleted": True})
```

### Request Validation

```python
from hypern import Hypern
from hypern.validation import validate_body, validate_query, validate_params

app = Hypern()

# Body validation
@app.post("/users")
@validate_body({
    "name": {"type": "string", "required": True, "min_length": 3},
    "email": {"type": "string", "required": True, "pattern": r"^[\w\.-]+@[\w\.-]+\.\w+$"},
    "age": {"type": "integer", "min": 18, "max": 120}
})
async def create_user(req, res, ctx):
    # Body is automatically validated
    body = req.json()
    res.status(201).json(body)

# Query parameter validation
@app.get("/search")
@validate_query({
    "q": {"type": "string", "required": True},
    "limit": {"type": "integer", "min": 1, "max": 100, "default": 10}
})
async def search(req, res, ctx):
    query = req.query("q")
    limit = req.query("limit", 10)
    res.json({"query": query, "limit": limit})
```

### Router Mounting

```python
from hypern import Hypern, Router

app = Hypern()

# Create API v1 router
api_v1 = Router(prefix="/api/v1")

@api_v1.get("/users")
async def get_users_v1(req, res, ctx):
    res.json({"version": "v1", "users": []})

# Create API v2 router
api_v2 = Router(prefix="/api/v2")

@api_v2.get("/users")
async def get_users_v2(req, res, ctx):
    res.json({"version": "v2", "users": []})

# Mount routers
app.use(api_v1)
app.use(api_v2)

# Routes are now available at:
# - /api/v1/users
# - /api/v2/users
```

### File Uploads

```python
from hypern import Hypern

app = Hypern()

@app.post("/upload")
async def upload_file(req, res, ctx):
    form_data = await req.form()
    
    file = form_data.get_file("document")
    if file:
        # Access file properties
        filename = file.filename
        content_type = file.content_type
        content = file.content  # bytes
        
        # Save file
        with open(f"uploads/{filename}", "wb") as f:
            f.write(content)
        
        res.json({
            "filename": filename,
            "size": len(content),
            "type": content_type
        })
    else:
        res.status(400).json({"error": "No file uploaded"})
```

### Dependency Injection

```python
from hypern import Hypern

app = Hypern()

# Register singleton (shared instance)
class DatabaseService:
    def __init__(self):
        self.connection = "db_connection"
    
    def query(self, sql):
        return [{"id": 1, "name": "John"}]

app.singleton("db", DatabaseService())

# Register factory (new instance per request)
class RequestLogger:
    def log(self, message):
        print(f"LOG: {message}")

app.factory("logger", lambda: RequestLogger())

# Use dependencies in routes
@app.get("/data")
async def get_data(req, res, ctx):
    db = ctx.get("db")
    logger = ctx.get("logger")
    
    logger.log("Fetching data")
    data = db.query("SELECT * FROM items")
    res.json(data)
```

### Error Handling

```python
from hypern import Hypern, HTTPException, NotFound, exception_handler

app = Hypern()

# Custom exception handler
@app.errorhandler(NotFound)
def handle_not_found(req, res, error):
    res.status(404).json({
        "error": "Resource not found",
        "path": req.path
    })

@app.errorhandler(Exception)
def handle_generic_error(req, res, error):
    res.status(500).json({
        "error": "Internal server error",
        "message": str(error)
    })

# Raise HTTP exceptions
@app.get("/users/:id")
async def get_user(req, res, ctx):
    user_id = req.param("id")
    
    # Simulate user not found
    if user_id == "999":
        raise NotFound("User not found")
    
    res.json({"id": user_id})
```

### Static Files

```python
from hypern import Hypern

app = Hypern()

# Serve static files from 'public' directory at '/static' URL
app.static("/static", "public")

# Serve frontend build from 'dist' directory at root
app.static("/", "dist")

# Now files are accessible:
# - /static/css/style.css → public/css/style.css
# - /static/js/app.js → public/js/app.js
# - / → dist/index.html
```

---

## 📖 Documentation

For more detailed documentation, visit:
- [Getting Started Guide](docs/getting-started.md)
- [Routing](docs/routing.md)
- [Middleware](docs/middleware.md)
- [Database](docs/database.md)
- [Authentication](docs/auth.md)
- [WebSocket](docs/websocket.md)
- [Task Scheduling](docs/scheduling.md)
- [Request Validation](docs/validation.md)

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is licensed under the terms specified in the [LICENSE](LICENSE) file.

## 🔗 Links

- [Documentation](https://hypern.dev/docs)
- [GitHub Repository](https://github.com/yourusername/hypern)
- [Issue Tracker](https://github.com/yourusername/hypern/issues)

---

**Built with ❤️ using Python and Rust**


