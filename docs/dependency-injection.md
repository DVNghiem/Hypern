# Dependency Injection

Hypern provides a powerful dependency injection (DI) system for managing application services, configuration, and request-scoped data.

## Overview

The DI system supports three types of dependencies:

1. **Singletons** - Shared instances (created once)
2. **Factories** - New instance per injection
3. **Request Context** - Request-scoped data

## Registering Dependencies

### Singleton Registration

Singletons are created once and shared across all requests:

```python
from hypern import Hypern
from hypern.database import Database

app = Hypern()

# Register configuration as singleton
config = {
    "debug": True,
    "database_url": "postgresql://localhost/mydb",
    "redis_url": "redis://localhost:6379",
    "secret_key": "your-secret-key"
}
app.singleton("config", config)

# Register a database instance
db = Database("postgresql://localhost/mydb")
app.singleton("db", db)
```

### Factory Registration

Factories create a new instance each time they're injected:

```python
def create_logger():
    import logging
    logger = logging.getLogger("hypern")
    logger.setLevel(logging.INFO)
    return logger

app.factory("logger", create_logger)

# With dependent factories
def create_email_service():
    class EmailService:
        def __init__(self, smtp_host):
            self.smtp_host = smtp_host
        
        def send(self, to, subject, body):
            # Send email logic
            pass
    
    return EmailService("localhost")

app.factory("email", create_email_service)
```

### Class-Based Services

```python
class UserService:
    def __init__(self, db):
        self.db = db
    
    def get_user(self, user_id: str):
        # Query database
        user = self.db.execute(
            "SELECT * FROM users WHERE id = ?", [user_id]
        )
        return user

# Register service as singleton
db = Database("postgresql://localhost/mydb")
user_service = UserService(db)
app.singleton("user_service", user_service)
```

## Injecting Dependencies

### Using the Standalone @inject Decorator

The recommended way to inject dependencies is the standalone `@inject` decorator, 
which can be imported and used in any module without referencing the app instance:

```python
from hypern import inject

@app.get("/config")
@inject("config")
def get_config(req, res, ctx, config):
    res.json(config)

@app.get("/users/:id")
@inject("user_service")
async def get_user(req, res, ctx, user_service):
    user_id = req.param("id")
    user = await user_service.get_user(user_id)
    if user:
        res.json(user)
    else:
        res.status(404).json({"error": "User not found"})
```

### Multiple Injections

You can inject multiple dependencies in a single decorator call:

```python
from hypern import inject

@app.post("/orders")
@inject("db_pool", "email", "config")
async def create_order(req, res, ctx, db_pool, email, config):
    data = req.json()
```

Or stack multiple `@inject` decorators (order matches argument order):

```python
@app.post("/orders")
@inject("config")
@inject("email")
@inject("db_pool")
async def create_order(req, res, ctx, db_pool, email, config):
    data = req.json()
```

### Using @app.inject (legacy)

`@app.inject` still works and delegates to the standalone `@inject` internally:

```python
@app.get("/config")
@app.inject("config")
def get_config(req, res, ctx, config):
    res.json(config)

@app.get("/users/:id")
@app.inject("user_service")
@app.inject("logger")
async def get_user(req, res, ctx, user_service, logger):
    user_id = req.param("id")
    logger.info(f"Fetching user {user_id}")
    
    user = await user_service.get_user(user_id)
    if user:
        res.json(user)
    else:
        res.status(404).json({"error": "User not found"})
```

### Using Standalone @inject in Separate Modules

The standalone `@inject` decorator avoids circular imports in large apps:

```python
# services/user_routes.py
from hypern import inject, Router

router = Router(prefix="/users")

@router.get("/")
@inject("user_service")
async def list_users(req, res, ctx, user_service):
    users = await user_service.get_all()
    res.json(users)

@router.get("/:id")
@inject("user_service", "logger")
async def get_user(req, res, ctx, user_service, logger):
    user_id = req.param("id")
    logger.info(f"Fetching user {user_id}")
    user = await user_service.get_user(user_id)
    res.json(user)
```

### Multiple Injections (legacy)

```python
@app.post("/orders")
@app.inject("db_pool")
@app.inject("email")
@app.inject("config")
async def create_order(req, res, ctx, db_pool, email, config):
    data = req.json()
    
    # Create order in database
    order = await db_pool.fetchrow(
        "INSERT INTO orders (user_id, items) VALUES ($1, $2) RETURNING *",
        data["user_id"], data["items"]
    )
    
    # Send confirmation email
    email.send(
        to=data["email"],
        subject="Order Confirmation",
        body=f"Your order #{order['id']} has been placed"
    )
    
    res.status(201).json(order)
```

## Request Context

The context object provides request-scoped data storage:

### Basic Context Usage

```python
@app.get("/user")
def get_user(req, res, ctx):
    # Store values in context
    ctx.set("request_id", "req-12345")
    ctx.set("user_id", "user-123")
    ctx.set("role", "admin")
    
    # Retrieve values
    user_id = ctx.get("user_id")
    has_role = ctx.has("role")
    
    # Get with default
    locale = ctx.get("locale", "en-US")
    
    res.json({
        "user_id": user_id,
        "locale": locale
    })
```

### Authentication Context

```python
class AuthMiddleware(Middleware):
    async def before(self, req, res, next):
        token = req.header("Authorization")
        if not token:
            res.status(401).json({"error": "Unauthorized"})
            return
        
        # Validate token and extract user info
        user = validate_token(token)
        
        # Set authentication context
        ctx = req.context
        ctx.set_auth(
            user_id=user["id"],
            roles=user["roles"]
        )
        
        await next()

@app.get("/admin/dashboard")
def admin_dashboard(req, res, ctx):
    # Check if user has admin role
    if not ctx.has_role("admin"):
        res.status(403).json({"error": "Forbidden"})
        return
    
    # Get authenticated user ID
    user_id = ctx.get("user_id")
    
    res.json({"dashboard": "admin data"})
```

### Request Timing

```python
@app.get("/slow-endpoint")
async def slow_endpoint(req, res, ctx):
    # Do some work
    await asyncio.sleep(0.5)
    
    # Get elapsed time since request start
    elapsed = ctx.elapsed_ms()
    
    res.json({
        "result": "done",
        "processing_time_ms": elapsed
    })
```

## DI Container API

### Injecting Dependencies

Use the `@app.inject()` decorator to inject dependencies into route handlers:

```python
# Inject configuration
@app.inject("config")
def settings_page(req, res, ctx, config):
    res.json({
        "debug": config["debug"],
        "version": "1.0.0"
    })

# Inject database
@app.inject("db")
def get_user(req, res, ctx, db):
    user_id = req.param("id")
    user = db.execute("SELECT * FROM users WHERE id = ?", [user_id])
    res.json(user)

# Inject service
@app.inject("user_service")
def create_user(req, res, ctx, user_service):
    data = req.json()
    user = user_service.create(data)
    res.status(201).json(user)
```

### Getting from Context

Dependencies are also available through the context object:

```python
@app.get("/user-profile")
def user_profile(req, res, ctx):
    # Get injected dependency from context
    user_service = ctx.get("user_service")
    if user_service:
        profile = user_service.get_profile()
        res.json(profile)
    else:
        res.status(500).json({"error": "Service not available"})
```

### Service Lifecycle

```python
# Register with cleanup
class DatabasePool:
    def __init__(self, url):
        self.db = None
        self.url = url
    
    def connect(self):
        # Use Hypern's Database class
        from hypern.database import Database
        self.db = Database(self.url)
    
    def close(self):
        # Database connections are managed by Hypern
        pass

# Register singleton
db_pool = DatabasePool("postgresql://localhost/mydb")
db_pool.connect()
app.singleton("db", db_pool.db)
```

## Patterns

### Repository Pattern

```python
class UserRepository:
    def __init__(self, db):
        self.db = db
    
    def find_by_id(self, user_id: str):
        return self.db.execute(
            "SELECT * FROM users WHERE id = ?", [user_id]
        )
    
    def find_by_email(self, email: str):
        return self.db.execute(
            "SELECT * FROM users WHERE email = ?", [email]
        )
    
    def create(self, data: dict):
        result = self.db.execute(
            "INSERT INTO users (name, email) VALUES (?, ?)",
            [data["name"], data["email"]]
        )
        return result

# Register repository
from hypern.database import Database
db = Database("postgresql://localhost/mydb")
user_repo = UserRepository(db)
app.singleton("user_repo", user_repo)
```

### Service Layer Pattern

```python
class AuthService:
    def __init__(self, user_repo):
        self.user_repo = user_repo
    
    def login(self, email: str, password: str):
        user = self.user_repo.find_by_email(email)
        if not user:
            return None
        
        # Verify password logic here
        return {"user": user, "token": "jwt_token"}
    
    def register(self, data: dict):
        data["password_hash"] = hash_password(data["password"])
        del data["password"]
        return self.user_repo.create(data)

# Register service with dependencies
user_repo = app._di  # Access via context or inject
auth_service = AuthService(user_repo)
app.singleton("auth_service", auth_service)
```

### Unit of Work Pattern

```python
class UnitOfWork:
    def __init__(self, db):
        self.db = db
        self.transaction = None
    
    def __enter__(self):
        # Start transaction
        self.transaction = True
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Commit or rollback handled by database
        self.transaction = False
    
    def execute(self, query, args):
        return self.db.execute(query, args)

# Usage in handler
@app.post("/transfer")
@app.inject("db")
def transfer_funds(req, res, ctx, db):
    data = req.json()
    
    with UnitOfWork(db) as uow:
        # Both operations succeed or both fail
        uow.execute(
            "UPDATE accounts SET balance = balance - ? WHERE id = ?",
            [data["amount"], data["from_account"]]
        )
        uow.execute(
            "UPDATE accounts SET balance = balance + ? WHERE id = ?",
            [data["amount"], data["to_account"]]
        )
    
    res.json({"status": "success"})
```
