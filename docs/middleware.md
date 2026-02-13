# Middleware

Hypern provides high-performance Rust-based middleware for common web application needs. All middleware is implemented in Rust for maximum performance and exposed to Python through the API.

## Available Middleware

All middleware is implemented in Rust:

| Middleware | Description |
|------------|-------------|
| `CorsMiddleware` | Cross-Origin Resource Sharing handling |
| `RateLimitMiddleware` | Request rate limiting with multiple algorithms |
| `SecurityHeadersMiddleware` | Security headers (HSTS, CSP, X-Frame-Options, etc.) |
| `TimeoutMiddleware` | Request timeout enforcement |
| `CompressionMiddleware` | Response compression (gzip, deflate, brotli) |
| `RequestIdMiddleware` | Unique request ID generation/tracking |
| `LogMiddleware` | Request/response logging |
| `BasicAuthMiddleware` | HTTP Basic Authentication |

## Quick Start

```python
from hypern import Hypern
from hypern.middleware import CorsMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware, LogMiddleware

app = Hypern()

# Add middleware (order matters - they execute in order added)
app.use(LogMiddleware())                      # Logging first
app.use(SecurityHeadersMiddleware.strict())   # Security headers
app.use(CorsMiddleware.permissive())          # CORS handling
app.use(RateLimitMiddleware())                # Rate limiting

@app.get("/api/data")
def get_data(req, res, ctx):
    res.json({"message": "Hello World"})

app.listen(3000)
```

## CORS Middleware

Handles Cross-Origin Resource Sharing headers.

### Basic Usage

```python
from hypern.middleware import CorsMiddleware

# Permissive CORS (allow all origins) - good for development
cors = CorsMiddleware.permissive()
app.use(cors)
```

### Production Configuration

```python
cors = CorsMiddleware(
    allowed_origins=["https://app.example.com", "https://api.example.com"],
    allowed_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allowed_headers=["Content-Type", "Authorization", "X-Request-ID"],
    expose_headers=["X-Request-ID", "X-RateLimit-Remaining"],
    allow_credentials=True,
    max_age=86400  # Cache preflight for 24 hours
)
app.use(cors)
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `allowed_origins` | `List[str]` | `["*"]` | Allowed origins (use `["*"]` for all) |
| `allowed_methods` | `List[str]` | `["GET", "POST", ...]` | Allowed HTTP methods |
| `allowed_headers` | `List[str]` | `["Content-Type", ...]` | Allowed request headers |
| `expose_headers` | `List[str]` | `[]` | Headers exposed to the client |
| `allow_credentials` | `bool` | `False` | Allow credentials |
| `max_age` | `int` | `86400` | Preflight cache max age in seconds |

### Important Notes

- **CORS headers are only added when the `Origin` header is present in the request.** This is standard CORS behavior - if there's no cross-origin request, CORS headers are not needed.
- **Preflight OPTIONS requests** are automatically handled by the middleware and will return a 204 response with appropriate CORS headers.
- For development, use `CorsMiddleware.permissive()` which allows all origins. For production, specify exact origins for security.

## Rate Limiting Middleware

Limits request rates per client to prevent abuse.

### Basic Usage

```python
from hypern.middleware import RateLimitMiddleware

# 100 requests per minute with sliding window
rate_limit = RateLimitMiddleware(max_requests=100, window_secs=60)
app.use(rate_limit)
```

### Advanced Configuration

```python
rate_limit = RateLimitMiddleware(
    max_requests=1000,
    window_secs=3600,       # 1 hour window
    algorithm="sliding",     # Algorithm: "fixed", "sliding", or "token_bucket"
    key_header="X-API-Key", # Use API key for client identification
    skip_paths=["/health", "/metrics"]  # Skip these paths
)
app.use(rate_limit)
```

### Rate Limiting Algorithms

| Algorithm | Description | Best For |
|-----------|-------------|----------|
| `fixed` | Simple counter, resets at fixed intervals | Simple use cases, least memory |
| `sliding` | Smoother rate limiting across window boundaries | Most use cases (default) |
| `token_bucket` | Allows controlled bursts | APIs that need burst support |

### Response Headers

Rate limit middleware adds these headers to responses:

- `X-RateLimit-Limit`: Maximum requests allowed
- `X-RateLimit-Remaining`: Requests remaining in window
- `X-RateLimit-Reset`: Seconds until window resets
- `Retry-After`: Seconds until rate limit resets (only on 429)

## Security Headers Middleware

Adds security-related HTTP headers to protect against common attacks.

### Basic Usage

```python
from hypern.middleware import SecurityHeadersMiddleware

# Default security headers
security = SecurityHeadersMiddleware()
app.use(security)

# Or use strict preset (recommended for production)
security = SecurityHeadersMiddleware.strict()
app.use(security)
```

### Custom Configuration

```python
security = SecurityHeadersMiddleware(
    hsts=True,
    hsts_max_age=63072000,  # 2 years
    frame_options="DENY",   # Or "SAMEORIGIN"
    content_type_options=True,
    xss_protection=True,
    csp="default-src 'self'; script-src 'self'"
)
app.use(security)
```

### Headers Added

| Header | Description |
|--------|-------------|
| `X-Content-Type-Options` | Prevents MIME sniffing (`nosniff`) |
| `X-Frame-Options` | Clickjacking protection (`DENY` or `SAMEORIGIN`) |
| `X-XSS-Protection` | XSS filter (`1; mode=block`) |
| `Strict-Transport-Security` | HSTS enforcement |
| `Content-Security-Policy` | Content security policy (if configured) |
| `Referrer-Policy` | Controls referrer information |
| `Permissions-Policy` | Controls browser features (strict mode) |

## Timeout Middleware

Enforces request timeout at the Rust/Tokio level.

### Usage

```python
from hypern.middleware import TimeoutMiddleware

# 30 second timeout (default)
timeout = TimeoutMiddleware()
app.use(timeout)

# Custom timeout
timeout = TimeoutMiddleware(timeout_secs=60)  # 60 seconds
app.use(timeout)
```

## Compression Middleware

Compresses response bodies based on `Accept-Encoding` header.

### Usage

```python
from hypern.middleware import CompressionMiddleware

# Default: compress responses > 1KB
compression = CompressionMiddleware()
app.use(compression)

# Custom minimum size
compression = CompressionMiddleware(min_size=512)  # Compress responses > 512 bytes
app.use(compression)
```

### Supported Encodings

- `br` (Brotli) - preferred
- `gzip`
- `deflate`

## Request ID Middleware

Adds a unique request ID to each request for tracing and debugging.

### Usage

```python
from hypern.middleware import RequestIdMiddleware

# Default header: X-Request-ID
request_id = RequestIdMiddleware()
app.use(request_id)

# Custom header name
request_id = RequestIdMiddleware(header_name="X-Correlation-ID")
app.use(request_id)
```

The middleware:
- Uses existing request ID from header if present
- Generates a new ID if not present
- Adds the ID to response headers

## Logging Middleware

Logs incoming requests using Rust's tracing infrastructure.

### Usage

```python
from hypern.middleware import LogMiddleware

# Default logger
log = LogMiddleware.default_logger()
app.use(log)

# Custom configuration
log = LogMiddleware(
    level="info",           # "debug", "info", "warn", "error"
    log_headers=True,       # Include request headers in logs
    skip_paths=["/health", "/metrics"]  # Skip logging these paths
)
app.use(log)
```

### Log Output

Logs include:
- Request ID
- HTTP method
- Request path
- Response time (on completion)

## Basic Authentication Middleware

Implements HTTP Basic Authentication.

### Usage

```python
from hypern.middleware import BasicAuthMiddleware

# Configure with users
basic_auth = BasicAuthMiddleware(
    realm="Admin Area",
    users={
        "admin": "secret_password",
        "user": "user_password"
    }
)
app.use(basic_auth)
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `realm` | `str` | `"Restricted"` | Authentication realm shown in browser dialog |
| `users` | `Dict[str, str]` | `None` | Dictionary of username -> password pairs |

## Middleware Stack

Use `MiddlewareStack` to group middleware for reuse:

```python
from hypern.middleware import MiddlewareStack, CorsMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware

# Create a reusable middleware stack
api_stack = MiddlewareStack()
api_stack.use(CorsMiddleware.permissive())
api_stack.use(RateLimitMiddleware(max_requests=100, window_secs=60))
api_stack.use(SecurityHeadersMiddleware.strict())

# Apply to routes
@app.get("/api/data", middleware=api_stack)
def get_data(req, res, ctx):
    res.json({"data": "protected"})
```

## Route-Specific Middleware

Apply middleware to specific routes:

```python
from hypern.middleware import RateLimitMiddleware, BasicAuthMiddleware

# Strict rate limit for auth endpoints
auth_rate_limit = RateLimitMiddleware(max_requests=5, window_secs=60)

@app.post("/auth/login", middleware=[auth_rate_limit])
def login(req, res, ctx):
    # Handle login
    pass

# Protected admin endpoint
admin_auth = BasicAuthMiddleware(realm="Admin", users={"admin": "secret"})

@app.get("/admin/users", middleware=[admin_auth])
def list_users(req, res, ctx):
    res.json({"users": []})
```

## Middleware Order

Middleware executes in the order it's added. Recommended order:

```python
app.use(RequestIdMiddleware())       # 1. Request tracking (first for tracing)
app.use(LogMiddleware())             # 2. Logging (after request ID)
app.use(SecurityHeadersMiddleware()) # 3. Security headers
app.use(CorsMiddleware())            # 4. CORS handling
app.use(RateLimitMiddleware())       # 5. Rate limiting
app.use(TimeoutMiddleware())         # 6. Timeout enforcement
app.use(CompressionMiddleware())     # 7. Compression (last, after response is ready)
```

## Before/After Request Hooks

For simple request/response modifications without controlling the request flow, use lifecycle hooks. These execute globally for all requests.

### @before_request Hook

Executes **before** every request handler. Use for logging, adding headers, or setting up context.

**Signature:** `async def hook(req, res, ctx)` - No `next` parameter!

```python
from hypern import Hypern
from hypern.middleware import before_request

app = Hypern()

@before_request
async def log_incoming_request(req, res, ctx):
    """Log every incoming request"""
    print(f"[{ctx.request_id}] {req.method} {req.path}")
    ctx.set("start_time", time.time())

@before_request
async def add_security_headers(req, res, ctx):
    """Add security headers to all responses"""
    res.header("X-Content-Type-Options", "nosniff")
    res.header("X-Frame-Options", "DENY")

# Register hooks with app.use()
app.use(log_incoming_request)
app.use(add_security_headers)

@app.get("/api/data")
def get_data(req, res, ctx):
    # before_request hooks have already executed
    res.json({"data": "value"})
```

### @after_request Hook

Executes **after** every request handler completes. Use for logging, adding response headers, or cleanup.

**Signature:** `async def hook(req, res, ctx)` - No `next` parameter!

```python
from hypern.middleware import after_request

@after_request
async def log_response(req, res, ctx):
    """Log response details"""
    duration = time.time() - ctx.get("start_time", 0)
    print(f"[{ctx.request_id}] Response sent in {duration:.3f}s")

@after_request
async def add_custom_header(req, res, ctx):
    """Add custom header to all responses"""
    res.header("X-Powered-By", "Hypern")
    res.header("X-Response-Time", f"{ctx.elapsed_ms():.2f}ms")

app.use(log_response)
app.use(add_custom_header)
```

### Multiple Hooks Execution Order

Hooks execute in the order they are registered:

```python
@before_request
async def first_hook(req, res, ctx):
    print("1. First before hook")
    ctx.set("step", 1)

@before_request  
async def second_hook(req, res, ctx):
    print("2. Second before hook")
    ctx.set("step", 2)

app.use(first_hook)
app.use(second_hook)

@app.get("/test")
def test_handler(req, res, ctx):
    print(f"3. Handler (step={ctx.get('step')})")  # step will be 2
    res.json({"ok": True})

@after_request
async def first_after(req, res, ctx):
    print("4. First after hook")

@after_request
async def second_after(req, res, ctx):
    print("5. Second after hook")

app.use(first_after)
app.use(second_after)
```

**Output:**
```
1. First before hook
2. Second before hook
3. Handler (step=2)
4. First after hook
5. Second after hook
```

### When to Use Hooks vs Middleware

| Use Case | Use Hook | Use Middleware |
|----------|----------|----------------|
| Global logging | ✅ `@before_request` / `@after_request` | ❌ |
| Adding response headers | ✅ `@after_request` | ❌ |
| Simple request logging | ✅ `@before_request` | ❌ |
| Route-specific logic | ❌ | ✅ `@middleware` |
| Conditional request blocking | ❌ | ✅ `@middleware` |
| Chain multiple operations | ❌ | ✅ `@middleware` |
| Modifying request flow | ❌ | ✅ `@middleware` |

## Custom Middleware

For route-specific logic with control over request flow, use the `@middleware` decorator. Custom middleware can short-circuit requests, transform data, or implement complex logic.

### @middleware Decorator

**Signature:** `async def middleware(req, res, ctx, next)` - **Must include `next` parameter!**

```python
from hypern import Hypern
from hypern.middleware import middleware

app = Hypern()

@middleware
async def check_api_key(req, res, ctx, next):
    """Validate API key before allowing request to proceed"""
    api_key = req.header("X-API-Key")
    
    if not api_key:
        res.status(401).json({"error": "API key required"})
        return  # Don't call next() - short circuit!
    
    if api_key not in ["valid-key-1", "valid-key-2"]:
        res.status(403).json({"error": "Invalid API key"})
        return
    
    # Store validated key in context
    ctx.set("api_key", api_key)
    
    # Continue to next middleware or handler
    await next()

# Apply to specific routes
@app.get("/api/protected", middleware=[check_api_key])
def protected_endpoint(req, res, ctx):
    api_key = ctx.get("api_key")
    res.json({"message": "Access granted", "key": api_key})

@app.get("/api/public")
def public_endpoint(req, res, ctx):
    # No middleware - publicly accessible
    res.json({"message": "Public access"})
```

### Chaining Multiple Middleware

Multiple middleware execute in order, forming a chain:

```python
@middleware
async def authenticate(req, res, ctx, next):
    """Check authentication"""
    token = req.header("Authorization")
    if not token:
        res.status(401).json({"error": "Unauthorized"})
        return
    ctx.set("user_id", "user123")
    await next()

@middleware
async def check_permissions(req, res, ctx, next):
    """Check user permissions"""
    user_id = ctx.get("user_id")
    if user_id != "admin123":
        res.status(403).json({"error": "Forbidden"})
        return
    await next()

@middleware
async def log_access(req, res, ctx, next):
    """Log admin access"""
    print(f"Admin access: {req.path}")
    await next()

# Apply middleware chain
@app.delete("/api/users/:id", middleware=[authenticate, check_permissions, log_access])
def delete_user(req, res, ctx):
    user_id = req.param("id")
    res.json({"deleted": user_id})
```

**Execution flow:**
1. `authenticate` → validates token, sets user_id, calls `next()`
2. `check_permissions` → validates user, calls `next()`
3. `log_access` → logs access, calls `next()`
4. `delete_user` handler executes

### Short-Circuiting Requests

Middleware can stop request processing by **not calling `next()`**:

```python
@middleware
async def rate_limit(req, res, ctx, next):
    """Simple rate limiting"""
    ip = req.header("X-Forwarded-For") or req.header("X-Real-IP")
    
    if is_rate_limited(ip):
        res.status(429).json({
            "error": "Too many requests",
            "retry_after": 60
        })
        return  # Stop here - don't call next()
    
    await next()  # Allow request to proceed

@middleware
async def feature_flag(req, res, ctx, next):
    """Block access to disabled features"""
    if not is_feature_enabled("beta_api"):
        res.status(404).json({"error": "Not found"})
        return
    
    await next()

@app.get("/beta/feature", middleware=[feature_flag, rate_limit])
def beta_feature(req, res, ctx):
    res.json({"feature": "enabled"})
```

### Modifying Request/Response

Middleware can modify requests before they reach handlers:

```python
@middleware
async def add_request_context(req, res, ctx, next):
    """Enrich request context"""
    # Add custom data to context
    ctx.set("timestamp", time.time())
    ctx.set("request_id", ctx.request_id)
    
    # Add response header
    res.header("X-Request-ID", ctx.request_id)
    
    await next()
    
    # Add response header after handler completes
    elapsed = time.time() - ctx.get("timestamp")
    res.header("X-Response-Time", f"{elapsed:.3f}s")

@app.get("/api/data", middleware=[add_request_context])
def get_data(req, res, ctx):
    # Context has been enriched
    request_id = ctx.get("request_id")
    res.json({"data": "value", "request_id": request_id})
```

### Error Handling in Middleware

```python
@middleware
async def error_handler(req, res, ctx, next):
    """Catch errors from downstream middleware/handlers"""
    try:
        await next()
    except ValueError as e:
        res.status(400).json({"error": "Invalid value", "details": str(e)})
    except PermissionError as e:
        res.status(403).json({"error": "Permission denied", "details": str(e)})
    except Exception as e:
        res.status(500).json({"error": "Internal server error"})
        print(f"Error: {e}")

@app.get("/api/risky", middleware=[error_handler])
def risky_endpoint(req, res, ctx):
    # If this raises an exception, error_handler catches it
    value = int(req.query("value"))
    res.json({"result": value * 2})
```

### Async vs Sync Middleware

Both async and sync middleware are supported:

```python
# Async middleware (preferred)
@middleware
async def async_middleware(req, res, ctx, next):
    print("Before handler")
    await next()
    print("After handler")

# Sync middleware (for simple cases)
@middleware
def sync_middleware(req, res, ctx, next):
    print("Simple middleware")
    next()  # Note: no await for sync
```

### Using Middleware with MiddlewareStack

Group reusable middleware:

```python
from hypern.middleware import MiddlewareStack, middleware

@middleware
async def auth(req, res, ctx, next):
    # Authentication logic
    await next()

@middleware
async def rate_limit(req, res, ctx, next):
    # Rate limiting logic
    await next()

# Create reusable stack
protected_stack = MiddlewareStack()
protected_stack.use(auth)
protected_stack.use(rate_limit)

# Apply to multiple routes
@app.get("/api/users", middleware=protected_stack)
def get_users(req, res, ctx):
    res.json({"users": []})

@app.post("/api/users", middleware=protected_stack)
def create_user(req, res, ctx):
    res.json({"created": True})
```

### Complete Example: Custom Authentication

```python
from hypern import Hypern
from hypern.middleware import middleware, before_request, after_request
import time

app = Hypern()

# Global hooks
@before_request
async def log_request(req, res, ctx):
    """Log all requests"""
    print(f"→ {req.method} {req.path}")
    ctx.set("start_time", time.time())

@after_request
async def log_response(req, res, ctx):
    """Log response time"""
    elapsed = time.time() - ctx.get("start_time", time.time())
    print(f"← {req.method} {req.path} ({elapsed*1000:.2f}ms)")

app.use(log_request)
app.use(log_response)

# Custom middleware
@middleware
async def require_auth(req, res, ctx, next):
    """Require valid JWT token"""
    auth_header = req.header("Authorization")
    
    if not auth_header or not auth_header.startswith("Bearer "):
        res.status(401).json({"error": "Missing or invalid authorization header"})
        return
    
    token = auth_header[7:]  # Remove "Bearer "
    
    # Validate token (simplified)
    if not validate_jwt_token(token):
        res.status(401).json({"error": "Invalid token"})
        return
    
    # Extract user from token
    user = decode_jwt_token(token)
    ctx.set("user", user)
    
    await next()

@middleware
async def require_admin(req, res, ctx, next):
    """Require admin role"""
    user = ctx.get("user")
    
    if not user or user.get("role") != "admin":
        res.status(403).json({"error": "Admin access required"})
        return
    
    await next()

# Public endpoints
@app.get("/")
def home(req, res, ctx):
    res.json({"message": "Welcome"})

@app.post("/auth/login")
def login(req, res, ctx):
    # Login logic
    res.json({"token": "jwt-token-here"})

# Protected endpoints
@app.get("/api/profile", middleware=[require_auth])
def get_profile(req, res, ctx):
    user = ctx.get("user")
    res.json({"user": user})

@app.get("/admin/users", middleware=[require_auth, require_admin])
def list_all_users(req, res, ctx):
    res.json({"users": ["user1", "user2"]})

app.listen(3000)

def validate_jwt_token(token):
    # Implement JWT validation
    return token == "valid-token"

def decode_jwt_token(token):
    # Implement JWT decoding
    return {"id": "123", "role": "user"}
```

### Key Differences: Hooks vs Middleware

| Feature | `@before_request` / `@after_request` | `@middleware` |
|---------|-------------------------------------|---------------|
| **Signature** | `(req, res, ctx)` | `(req, res, ctx, next)` |
| **Scope** | Global (all routes) | Route-specific |
| **Control flow** | Cannot block requests | Can short-circuit with `return` |
| **Ordering** | Registration order | Can chain multiple |
| **Use case** | Logging, headers, setup | Auth, validation, transform |
| **`next()` callback** | ❌ No | ✅ Yes, required |
| **Short-circuit** | ❌ Cannot stop request | ✅ Can stop by not calling `next()` |


## Production Example

Complete production-ready middleware configuration:

```python
from hypern import Hypern
from hypern.middleware import (
    RequestIdMiddleware, LogMiddleware, SecurityHeadersMiddleware, CorsMiddleware, 
    RateLimitMiddleware, TimeoutMiddleware, CompressionMiddleware
)

app = Hypern()

# Request tracking
app.use(RequestIdMiddleware())

# Logging
app.use(LogMiddleware(
    level="info",
    skip_paths=["/health", "/metrics", "/ready"]
))

# Security
app.use(SecurityHeadersMiddleware(
    hsts=True,
    hsts_max_age=63072000,  # 2 years
    frame_options="DENY",
    csp="default-src 'self'"
))

# CORS
app.use(CorsMiddleware(
    allowed_origins=[
        "https://app.example.com",
        "https://admin.example.com"
    ],
    allowed_methods=["GET", "POST", "PUT", "DELETE"],
    allow_credentials=True
))

# Rate limiting
app.use(RateLimitMiddleware(
    max_requests=1000,
    window_secs=3600,
    algorithm="sliding",
    skip_paths=["/health", "/metrics"]
))

# Timeout
app.use(TimeoutMiddleware(timeout_secs=30))

# Compression
app.use(CompressionMiddleware(min_size=1024))

# Health check endpoint (bypasses rate limiting)
@app.get("/health")
def health(req, res, ctx):
    res.json({"status": "healthy"})

# Protected API endpoint
@app.get("/api/data")
def get_data(req, res, ctx):
    res.json({"data": "value"})

app.listen(3000)
```

## Request Modification in Middleware

Middleware can modify request data before it reaches the handler. This allows you to transform, validate, or enrich requests.

### Modifying Request Headers

```python
from hypern import Hypern
from hypern.middleware import middleware

app = Hypern()

@middleware
async def add_custom_header(ctx, next):
    """Add a custom header to all requests"""
    ctx.set_header("X-Processed-By", "Hypern")
    ctx.set_header("X-Request-Time", str(ctx.start_time))
    await next()

app.use(add_custom_header)
```

### Modifying Query Parameters

```python
@middleware
async def normalize_params(ctx, next):
    """Normalize query parameters"""
    # Convert page to integer, default to 1
    page = ctx.get_query("page")
    if page:
        try:
            ctx.set_query("page", str(max(1, int(page))))
        except ValueError:
            ctx.set_query("page", "1")
    else:
        ctx.set_query("page", "1")
    
    # Ensure limit is within bounds
    limit = ctx.get_query("limit")
    if limit:
        try:
            ctx.set_query("limit", str(min(100, max(1, int(limit)))))
        except ValueError:
            ctx.set_query("limit", "10")
    
    await next()

app.use(normalize_params)
```

### Modifying Request Body

```python
@middleware
async def sanitize_body(ctx, next):
    """Sanitize request body data"""
    body = ctx.body()
    if body:
        import json
        try:
            data = json.loads(body.decode('utf-8'))
            # Remove sensitive fields
            data.pop('internal_id', None)
            data.pop('_metadata', None)
            # Set modified body
            ctx.set_body_str(json.dumps(data))
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    
    await next()

app.use(sanitize_body)
```

### Modifying Path

```python
@middleware
async def rewrite_path(ctx, next):
    """Rewrite legacy API paths to new paths"""
    path = ctx.path
    
    # Rewrite old API paths
    if path.startswith("/api/v1/"):
        new_path = path.replace("/api/v1/", "/api/v2/")
        ctx.set_path(new_path)
    
    await next()

app.use(rewrite_path)
```

### Complete Example: API Request Enrichment

```python
from hypern import Hypern
from hypern.middleware import middleware
import json
from datetime import datetime

app = Hypern()

@middleware
async def enrich_request(ctx, next):
    """Enrich request with additional data"""
    # Add timestamp header
    ctx.set_header("X-Request-Timestamp", datetime.utcnow().isoformat())
    
    # Add API version if not present
    if not ctx.get_header("API-Version"):
        ctx.set_header("API-Version", "2.0")
    
    # Normalize user agent
    user_agent = ctx.get_header("User-Agent")
    if user_agent:
        ctx.set_header("X-Original-User-Agent", user_agent)
        ctx.set_header("User-Agent", user_agent.lower())
    
    # For POST/PUT requests, enrich body
    if ctx.method in ["POST", "PUT"]:
        body = ctx.body()
        if body:
            try:
                data = json.loads(body.decode('utf-8'))
                # Add metadata
                data['_enriched'] = True
                data['_timestamp'] = datetime.utcnow().isoformat()
                ctx.set_body_str(json.dumps(data))
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
    
    await next()

app.use(enrich_request)

@app.post("/api/data")
def create_data(req, res, ctx):
    # Request data has been enriched by middleware
    data = req.json()
    res.json({
        "received": data,
        "headers": dict(req.headers)
    })

app.listen(3000)
```

### Available Modification Methods

The `MiddlewareContext` object provides these methods for modifying requests:

| Method | Description |
|--------|-------------|
| `ctx.set_header(name, value)` | Set or update a request header |
| `ctx.remove_header(name)` | Remove a request header |
| `ctx.set_query(name, value)` | Set or update a query parameter |
| `ctx.remove_query(name)` | Remove a query parameter |
| `ctx.set_query_string(qs)` | Replace entire query string |
| `ctx.set_body(bytes)` | Set request body from bytes |
| `ctx.set_body_str(string)` | Set request body from string |
| `ctx.clear_body()` | Clear the request body |
| `ctx.set_path(path)` | Change the request path |
| `ctx.set_param(name, value)` | Set a path parameter |

### Important Notes

- **Modifications happen before validation**: Changes made in middleware occur before request validation and handler execution
- **Thread-safe**: All modification methods are thread-safe and can be called from any middleware
- **Persistent**: Changes persist through the entire request lifecycle
- **Query string sync**: When using `set_query()`, remember that the query string itself isn't automatically rebuilt. Use `set_query_string()` if you need to replace the entire query string
- **Body encoding**: When modifying the body with `set_body_str()`, ensure proper encoding (UTF-8 is recommended)

