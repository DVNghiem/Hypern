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

app = Hypern()

# Register configuration as singleton
config = {
    "debug": True,
    "service_endpoint": "https://api.example.com",
    "secret_key": "your-secret-key"
}
app.singleton("config", config)

# Register an application-owned repository
class UserRepository:
    def find_by_id(self, user_id: str):
        return {"id": user_id, "name": "Ada"}

app.singleton("user_repository", UserRepository())
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
    def __init__(self, repository):
        self.repository = repository
    
    def get_user(self, user_id: str):
        return self.repository.find_by_id(user_id)

# Register service as singleton
user_repository = UserRepository()
user_service = UserService(user_repository)
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
@inject("order_service", "email", "config")
async def create_order(req, res, ctx, order_service, email, config):
    data = req.json()
```

Or stack multiple `@inject` decorators (order matches argument order):

```python
@app.post("/orders")
@inject("config")
@inject("email")
@inject("order_service")
async def create_order(req, res, ctx, order_service, email, config):
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
@app.inject("order_service")
@app.inject("email")
@app.inject("config")
async def create_order(req, res, ctx, order_service, email, config):
    data = req.json()

    order = await order_service.create(data)
    
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

# Inject an application-owned repository
@app.inject("user_repository")
def get_user(req, res, ctx, user_repository):
    user_id = req.param("id")
    user = user_repository.find_by_id(user_id)
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
# Application-owned services define their own lifecycle.
class SearchService:
    def start(self):
        pass

    def close(self):
        pass

search_service = SearchService()
search_service.start()
app.singleton("search_service", search_service)
```

## Patterns

### Repository Pattern

```python
class ApplicationStorage:
    """A small application-owned storage adapter for this example."""
    def __init__(self):
        self.users = {}

    def get(self, user_id: int):
        return self.users.get(user_id)

    def find_by_email(self, email: str):
        return next(
            (user for user in self.users.values() if user["email"] == email),
            None,
        )

    def save(self, data: dict):
        user = {"id": len(self.users) + 1, **data}
        self.users[user["id"]] = user
        return user


class UserRepository:
    def __init__(self, storage):
        self.storage = storage
    
    def find_by_id(self, user_id: str):
        return self.storage.get(user_id)
    
    def find_by_email(self, email: str):
        return self.storage.find_by_email(email)
    
    def create(self, data: dict):
        return self.storage.save(data)

# Register repository
storage = ApplicationStorage()
user_repo = UserRepository(storage)
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
    def __init__(self, account_repository):
        self.account_repository = account_repository
        self.transaction = None
    
    def __enter__(self):
        # Start transaction
        self.transaction = True
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Commit or rollback is owned by the application service.
        self.transaction = False
    
    def transfer(self, amount, source_account, destination_account):
        self.account_repository.transfer(amount, source_account, destination_account)

# Usage in handler
@app.post("/transfer")
@app.inject("account_repository")
def transfer_funds(req, res, ctx, account_repository):
    data = req.json()
    
    with UnitOfWork(account_repository) as uow:
        # Both operations succeed or both fail
        uow.transfer(data["amount"], data["from_account"], data["to_account"])
    
    res.json({"status": "success"})
```
