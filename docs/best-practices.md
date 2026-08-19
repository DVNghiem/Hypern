# Best Practices

This guide covers best practices for building production-ready applications with Hypern.

## Project Structure

Organize your project for scalability and maintainability:

```
my_app/
├── main.py                 # Application entry point
├── config.py              # Configuration management
├── routes/                # Route handlers organized by domain
│   ├── __init__.py
│   ├── users.py
│   ├── products.py
│   └── orders.py
├── models/                # Data models and schemas
│   ├── __init__.py
│   ├── user.py
│   ├── product.py
│   └── schemas.py
├── services/              # Business logic
│   ├── __init__.py
│   ├── user_service.py
│   ├── product_service.py
│   └── order_service.py
├── middleware/            # Custom middleware
│   ├── __init__.py
│   ├── auth.py
│   ├── logging.py
│   └── error_handler.py
├── tasks/                 # Background tasks
│   ├── __init__.py
│   ├── email_tasks.py
│   └── report_tasks.py
├── utils/                 # Utility functions
│   ├── __init__.py
│   ├── validators.py
│   ├── formatters.py
│   └── helpers.py
├── persistence/           # Application-owned persistence adapter
│   ├── __init__.py
│   └── models.py
└── tests/                 # Test files
    ├── __init__.py
    ├── test_routes.py
    ├── test_services.py
    └── conftest.py
```

## Application Initialization

Set up your application properly:

```python
# main.py
from hypern import Hypern
from config import settings
from routes import setup_routes
from middleware import setup_middleware
from persistence import init_persistence

# Create app instance
app = Hypern()

# Load configuration
app.config = settings

# Setup middleware
setup_middleware(app)

# Setup application-owned persistence
init_persistence(app)

# Setup routes
setup_routes(app)

if __name__ == "__main__":
    app.start(
        host=settings.HOST,
        port=settings.PORT,
        workers=settings.WORKERS,
        reload=settings.DEBUG
    )
```

## Configuration Management

Use environment-based configuration:

```python
# config.py
import os
from dataclasses import dataclass
from typing import Optional

@dataclass
class Settings:
    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    WORKERS: int = int(os.getenv("WORKERS", "4"))
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    
    # Application-owned persistence configuration
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite://./db.sqlite")
    DATABASE_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "20"))
    DATABASE_TIMEOUT: int = int(os.getenv("DB_TIMEOUT", "30"))
    
    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production")
    ALLOWED_ORIGINS: list = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    JWT_EXPIRY: int = int(os.getenv("JWT_EXPIRY", "3600"))
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: Optional[str] = os.getenv("LOG_FILE", None)
    
    # File uploads
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "/tmp/uploads")
    MAX_UPLOAD_SIZE: int = int(os.getenv("MAX_UPLOAD_SIZE", "10485760"))  # 10MB

settings = Settings()
```

## Application-Owned Persistence Best Practices

### Connection Pooling

```python
# persistence/init.py
from config import settings

def init_persistence(app):
    repository = UserRepository(settings.DATABASE_URL)
    app.provide(UserRepository, repository)

    # The application configures its driver, pool, and migrations.
    migrate(repository)
```

### Query Optimization

1. **Use connection pooling** - Configure it in your persistence adapter
2. **Use prepared statements** - Prevent SQL injection
3. **Index frequently queried columns** - Improve query performance
4. **Batch operations** - Use transactions for multiple operations

```python
# services/user_service.py
class UserService:
    def __init__(self, user_repository):
        self.user_repository = user_repository

    def create_users_batch(self, users):
        return self.user_repository.create_batch(users)
```

### Connection Management

Your application owns its persistence lifecycle. Inject a repository or service into handlers:

```python
@app.get("/users/:id")
def get_user(
    req,
    res,
    ctx,
    user_repository: UserRepository = Inject(),
):
    user = user_repository.find_by_id(req.param("id"))
    res.json(user)
```

## Dependency Injection Best Practices

```python
# services/user_service.py
class UserService:
    def __init__(self, user_repository):
        self.user_repository = user_repository
    
    def get_by_id(self, user_id):
        return self.user_repository.find_by_id(user_id)

# main.py - Setup DI
from hypern import Hypern, Inject
from services import UserService

app = Hypern()

# Register an application-owned repository
user_repository = UserRepository()
app.provide(UserRepository, user_repository)

# Register services
user_service = UserService(user_repository)
app.provide(UserService, user_service)

# routes/users.py
@app.get("/users/:id")
def get_user(req, res, ctx, user_service: UserService = Inject()):
    user = user_service.get_by_id(req.param("id"))
    res.json(user)
```

## Request/Response Validation

Always validate input and output:

```python
# models/schemas.py
import msgspec
from typing import Optional

class UserCreate(msgspec.Struct):
    name: str
    email: str
    age: int
    phone: Optional[str] = None

class UserResponse(msgspec.Struct):
    id: int
    name: str
    email: str
    age: int
    created_at: str

# routes/users.py
from hypern import Inject, Json
from models.schemas import UserCreate, UserResponse
from services import UserService

@app.post("/users")
def create_user(
    res,
    body: UserCreate = Json(),
    user_service: UserService = Inject(),
):
    user = user_service.create(body)
    res.status(201).json(user)
```

## Error Handling

```python
# middleware/error_handler.py
from hypern import HTTPException
import logging

logger = logging.getLogger(__name__)

def error_handler_middleware(req, res, ctx, next):
    try:
        next()
    except HTTPException as e:
        logger.warning(f"{req.method} {req.path} - {type(e).__name__}: {e.detail}")
        res.status(e.status_code).json(e.to_dict())
    except Exception:
        logger.error(f"Unhandled error on {req.method} {req.path}", exc_info=True)
        res.status(500).json({"error": True, "message": "Internal Server Error"})
```

## Background Tasks

Use background tasks for long-running operations:

```python
# tasks/email_tasks.py
from hypern.tasks import background_task
from services import EmailService

@background_task
def send_welcome_email(user_email: str, user_name: str):
    email_service = EmailService()
    email_service.send(
        to=user_email,
        subject="Welcome!",
        template="welcome.html",
        context={"name": user_name}
    )

# routes/users.py
from hypern import Inject, Json
from services import UserService

@app.post("/users")
def create_user(
    res,
    body: UserCreate = Json(),
    user_service: UserService = Inject(),
):
    user = user_service.create(body)
    
    # Queue background task
    send_welcome_email.queue(user.email, user.name)
    
    res.status(201).json(user)
```

## File Upload Handling

```python
# routes/files.py
from hypern import UnprocessableEntity, BadRequest
import os

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf", ".doc", ".docx"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

def validate_upload(file):
    _, ext = os.path.splitext(file.filename)
    if ext.lower() not in ALLOWED_EXTENSIONS:
        raise UnprocessableEntity(
            f"File type {ext} not allowed",
            data={"field": "file", "value": ext},
        )

    if file.size > MAX_FILE_SIZE:
        raise UnprocessableEntity(
            "File exceeds maximum size",
            data={"field": "file", "limit_bytes": MAX_FILE_SIZE},
        )

@app.post("/upload")
def upload_file(req, res, ctx):
    files = req.files()

    if "file" not in files:
        raise BadRequest("No file provided", data={"field": "file"})

    file = files["file"]
    validate_upload(file)
    
    # Save file with unique name
    import uuid
    filename = f"{uuid.uuid4()}_{file.filename}"
    filepath = os.path.join(settings.UPLOAD_DIR, filename)
    
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    with open(filepath, "wb") as f:
        f.write(file.read())
    
    # Queue background task to process file
    process_upload.queue(filename)
    
    res.json({"filename": filename, "message": "File uploaded"})
```

## Streaming Best Practices

Use streaming for large responses:

```python
@app.get("/export/users")
def export_users_csv(req, res, ctx):
    from hypern import StreamingResponse

    import csv
    import io

    stream = StreamingResponse(content_type="text/csv")
    stream.append_header("Content-Disposition", "attachment; filename=users.csv")

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["id", "name", "email"])
    writer.writeheader()

    for user in ctx.db.query("SELECT id, name, email FROM users"):
        writer.writerow(user)
        stream.write_str(output.getvalue())
        output.truncate(0)
        output.seek(0)

    stream.close()
    return stream
```

## Security Best Practices

### CORS Configuration

```python
from hypern.middleware import CORS

app.use(CORS(
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"]
))
```

### Authentication & Authorization

```python
import jwt
from hypern import Unauthorized
from functools import wraps

def require_auth(handler):
    @wraps(handler)
    def wrapper(req, res, ctx, *args, **kwargs):
        auth_header = req.header("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise Unauthorized("Missing or invalid authorization")
        
        token = auth_header[7:]
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
            ctx.user_id = payload["user_id"]
            ctx.user = get_user(payload["user_id"])
        except jwt.InvalidTokenError:
            raise Unauthorized("Invalid token")
        
        return handler(req, res, ctx, *args, **kwargs)
    
    return wrapper

@app.get("/profile")
@require_auth
def get_profile(req, res, ctx):
    res.json({"user": ctx.user})
```

### Rate Limiting

```python
from hypern.middleware import RateLimit

app.use(RateLimit(
    requests_per_second=100,
    burst=10
))
```

## Logging

```python
import logging
from logging.handlers import RotatingFileHandler

def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(settings.LOG_LEVEL)
    
    # Console handler
    console = logging.StreamHandler()
    console.setLevel(settings.LOG_LEVEL)
    
    # File handler
    if settings.LOG_FILE:
        file_handler = RotatingFileHandler(
            settings.LOG_FILE,
            maxBytes=10485760,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(settings.LOG_LEVEL)
        logger.addHandler(file_handler)
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console.setFormatter(formatter)
    logger.addHandler(console)

setup_logging()
```

## Testing

```python
# tests/conftest.py
import pytest
from main import app
from config import Settings

@pytest.fixture
def test_app():
    test_settings = Settings(DEBUG=True, DATABASE_URL="sqlite:///:memory:")
    app.config = test_settings
    return app

@pytest.fixture
def client(test_app):
    from hypern.testing import TestClient
    return TestClient(test_app)

# tests/test_users.py
def test_create_user(client):
    response = client.post("/users", json={
        "name": "John Doe",
        "email": "john@example.com",
        "age": 30
    })
    
    assert response.status_code == 201
    assert response.json()["name"] == "John Doe"
```

## Performance Optimization

1. **Use connection pooling** - Configure it in your persistence adapter
2. **Cache frequently accessed data** - Use in-memory caching
3. **Use database indexes** - Index columns used in WHERE clauses
4. **Batch operations** - Use transactions for multiple operations
5. **Compress responses** - Enable gzip compression
6. **Use CDN** - Serve static files from CDN
7. **Monitor performance** - Use APM tools like New Relic or DataDog

## Deployment Checklist

- [ ] Set SECRET_KEY environment variable
- [ ] Configure ALLOWED_ORIGINS for CORS
- [ ] Set DATABASE_URL to production database
- [ ] Enable logging to file
- [ ] Configure SSL/TLS certificates
- [ ] Set DEBUG=false
- [ ] Configure worker count based on CPU cores
- [ ] Set up health check endpoint
- [ ] Configure log rotation
- [ ] Set up error tracking (Sentry, etc.)
- [ ] Configure monitoring and alerting
- [ ] Test graceful shutdown
- [ ] Document API endpoints with OpenAPI
- [ ] Set up automated backups for database
- [ ] Configure rate limiting in production

## Health Check Endpoint

```python
@app.get("/health")
def health_check(req, res, ctx):
    checks = {
        "persistence": check_persistence(ctx),
        "cache": check_cache(ctx),
    }
    
    all_healthy = all(checks.values())
    status = 200 if all_healthy else 503
    
    res.status(status).json({
        "status": "healthy" if all_healthy else "unhealthy",
        "checks": checks
    })

def check_persistence(ctx):
    try:
        ctx.get("health_service").check_persistence()
        return "ok"
    except:
        return "error"
```

## Middleware Best Practices

### Order Is Execution Order

Middleware executes in the order added. Each middleware wraps everything after it. Place broad/early middleware first:

```python
# CORRECT: outer wraps inner
app.use(RequestIdMiddleware())        # 1. Track before anything else
app.use(LogMiddleware())              # 2. Log with request ID
app.use(SecurityHeadersMiddleware()) # 3. Security on every response
app.use(CorsMiddleware())            # 4. CORS after security
app.use(RateLimitMiddleware())      # 5. Rate limit after CORS
app.use(TimeoutMiddleware())        # 6. Timeout last — catches slow handlers
app.use(CompressionMiddleware())    # 7. Compress at the very end
```

Wrong order causes subtle bugs: CORS running after RateLimit means preflight OPTIONS requests count toward rate limits.

### Always Call `next()` or Return — Never Both

Short-circuit by returning without calling `next()`. Do not call `next()` and then continue:

```python
# WRONG — handler runs, then continues after next()
@middleware
async def broken(req, res, ctx, next):
    if is_denied(req):
        res.status(403).json({"error": "denied"})
        await next()  # DANGER: continues to handler anyway!
    await next()

# CORRECT — short circuit stops here
@middleware
async def correct(req, res, ctx, next):
    if is_denied(req):
        res.status(403).json({"error": "denied"})
        return  # Stop — don't call next()
    await next()

# CORRECT — always proceed
@middleware
async def always_proceed(req, res, ctx, next):
    ctx.set("processed", True)
    await next()
```

### Catch and Re-Raise, Never Swallow

Error-handling middleware must re-raise after responding, or the chain silently continues:

```python
# WRONG — handler never runs, chain breaks silently
@middleware
async def bad_catch(req, res, ctx, next):
    try:
        await next()
    except ValueError:
        pass  # Silently drops the error!

# CORRECT — respond, then re-raise so outer handlers see it
@middleware
async def good_catch(req, res, ctx, next):
    try:
        await next()
    except ValueError as e:
        res.status(400).json({"error": str(e)})
        raise  # Re-raise so outer middleware / framework sees it
    except Exception:
        res.status(500).json({"error": "Internal error"})
        raise
```

For global error catching at the outermost level only, let the framework handle unhandled exceptions.

### Context Isolation — One Middleware Per Concern

Each middleware should own one piece of state. Mixing concerns creates hidden dependencies:

```python
# WRONG — auth_middleware does too much
@middleware
async def auth_middleware(req, res, ctx, next):
    token = req.header("Authorization")
    ctx.set("user", validate(token))    # sets user
    ctx.set("start", time.time())       # also sets timing — mixed concern
    await next()

# CORRECT — split by concern
@middleware
async def auth(req, res, ctx, next):
    token = req.header("Authorization")
    ctx.set("user", validate(token))
    await next()

@middleware
async def timing(req, res, ctx, next):
    start = time.time()
    await next()
    elapsed = time.time() - start
    res.header("X-Response-Time", f"{elapsed:.3f}s")
```

Split middleware is also easier to test and reuse in different stacks.

### Avoid Blocking I/O in Sync Middleware

Sync middleware holds the async event loop. Move database calls, HTTP requests, and file I/O to async:

```python
# WRONG — blocks the event loop
@middleware
def slow_sync(req, res, ctx, next):
    result = blocking_db_query()  # blocks everything
    ctx.set("data", result)
    next()

# CORRECT — async middleware releases the event loop during I/O
@middleware
async def fast_async(req, res, ctx, next):
    result = await async_db_query()  # yields control while waiting
    ctx.set("data", result)
    await next()
```

If you must use sync I/O in sync middleware, offload to a thread pool:

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

_executor = ThreadPoolExecutor(max_workers=4)

@middleware
def threaded_middleware(req, res, ctx, next):
    loop = asyncio.new_event_loop()
    result = loop.run_until_complete(
        asyncio.get_event_loop().run_in_executor(_executor, blocking_call)
    )
    ctx.set("result", result)
    next()
```

### Test Middleware in Isolation

Test each middleware independently. The `@middleware` decorator wraps a function that receives `(req, res, ctx, next)` — construct and pass these directly:

```python
import pytest
from unittest.mock import Mock, AsyncMock
from app.middleware import check_api_key

@pytest.mark.asyncio
async def test_check_api_key_missing():
    req = Mock()
    req.header = Mock(return_value=None)
    res = Mock()
    res.status = Mock(return_value=res)
    res.json = Mock()
    ctx = Mock()
    ctx.set = Mock()
    next = AsyncMock()

    await check_api_key(req, res, ctx, next)

    res.status.assert_called_once_with(401)
    res.json.assert_called_once_with({"error": "API key required"})
    next.assert_not_called()  # short-circuited

@pytest.mark.asyncio
async def test_check_api_key_valid():
    req = Mock()
    req.header = Mock(return_value="valid-key-1")
    res = Mock()
    ctx = Mock()
    ctx.set = Mock()
    next = AsyncMock()

    await check_api_key(req, res, ctx, next)

    ctx.set.assert_called_once_with("api_key", "valid-key-1")
    next.assert_called_once()
```

### Prefer Hooks for Global Side Effects

If middleware only needs to run before/after every request without controlling flow, `@before_request` / `@after_request` hooks are cleaner than `@middleware`:

```python
# Hook — runs globally, no control over flow
@before_request
async def add_timestamp(req, res, ctx):
    ctx.set("arrived_at", time.time())

@after_request
async def add_timing_header(req, res, ctx):
    arrived = ctx.get("arrived_at", 0)
    if arrived:
        res.header("X-Response-Time", f"{time.time() - arrived:.3f}s")

# Middleware — use only when you need to block or modify flow
@middleware
async def require_auth(req, res, ctx, next):
    if not ctx.get("user"):
        res.status(401).json({"error": "Unauthorized"})
        return
    await next()
```

### Minimal Middleware — Do One Thing

Small middleware composes cleanly. Avoid middleware that both authenticates AND logs AND modifies the request AND checks a feature flag:

```python
# WRONG — one middleware doing four things
@middleware
async def god_middleware(req, res, ctx, next):
    ctx.set("user", validate_auth(req))
    log_request(req)
    req.headers["X-Forwarded-Proto"] = "https"
    if not is_feature_enabled("v2"):
        req.path = req.path.replace("/v2/", "/v1/")
    await next()

# CORRECT — four small middleware, composed
app.use(auth)                # 1. set user
app.use(request_logger)       # 2. log
app.use(https_forwarder)     # 3. modify headers
app.use(version_router)       # 4. route to version
```

Small middleware is easier to test, swap, and reason about under load.

### Don't Store Per-Request State on the Middleware Instance

Using `self` attributes for per-request data causes race conditions under concurrent requests:

```python
# WRONG — shared mutable state across requests
class BadMiddleware:
    def __init__(self):
        self.current_user = None  # shared!

    async def __call__(self, req, res, ctx, next):
        self.current_user = validate(req)  # overwrites for all concurrent requests
        await next()

# CORRECT — per-request state lives in ctx
class GoodMiddleware:
    async def __call__(self, req, res, ctx, next):
        ctx.set("user", validate(req))  # isolated per request
        await next()
```

Use `ctx` for per-request data. Use `self` only for shared configuration (connection pools, rate limiters, feature flags).
