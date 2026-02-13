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
├── database/              # Database configuration
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
from database import init_database

# Create app instance
app = Hypern()

# Load configuration
app.config = settings

# Setup middleware
setup_middleware(app)

# Setup database
init_database(app)

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
    
    # Database
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

## Database Best Practices

### Connection Pooling

```python
# database/init.py
from hypern.database import Database
from config import settings

def init_database(app):
    app.db = Database(
        settings.DATABASE_URL,
        pool_size=settings.DATABASE_POOL_SIZE,
        timeout=settings.DATABASE_TIMEOUT
    )
    
    # Run migrations
    migrate(app.db)

def get_db(ctx):
    """Get database from context"""
    return ctx.app.db
```

### Query Optimization

1. **Use connection pooling** - Configured by default in Hypern
2. **Use prepared statements** - Prevent SQL injection
3. **Index frequently queried columns** - Improve query performance
4. **Batch operations** - Use transactions for multiple operations

```python
# services/user_service.py
from database import get_db

class UserService:
    @staticmethod
    def create_users_batch(ctx, users):
        db = get_db(ctx)
        
        # Start transaction
        with db.transaction():
            user_ids = []
            for user in users:
                result = db.execute(
                    "INSERT INTO users (name, email) VALUES (?, ?)",
                    [user["name"], user["email"]]
                )
                user_ids.append(result.last_insert_id)
        
        return user_ids
```

### Connection Management

```python
@app.middleware("before_route")
def setup_db_context(req, res, ctx, next):
    ctx.db = app.db
    try:
        next()
    finally:
        # Clean up if needed
        pass
```

## Dependency Injection Best Practices

```python
# services/user_service.py
class UserService:
    def __init__(self, db):
        self.db = db
    
    def get_by_id(self, user_id):
        return self.db.execute("SELECT * FROM users WHERE id = ?", [user_id])

# main.py - Setup DI
from hypern import Hypern
from hypern.database import Database
from services import UserService

app = Hypern()

# Register database
db = Database("postgresql://localhost/mydb")
app.singleton("db", db)

# Register services
user_service = UserService(db)
app.singleton("user_service", user_service)

# routes/users.py
@app.get("/users/:id")
@app.inject("user_service")
def get_user(req, res, ctx, user_service):
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
from hypern.validation import validate_body
from models.schemas import UserCreate, UserResponse

@app.post("/users")
@validate_body(UserCreate)
def create_user(req, res, ctx, body: UserCreate):
    user_service = ctx.services.user
    user = user_service.create(body)
    res.status(201).json(user)
```

## Error Handling

```python
# middleware/error_handler.py
from hypern.exceptions import RequestError
import logging

logger = logging.getLogger(__name__)

def error_handler_middleware(req, res, ctx, next):
    try:
        next()
    except RequestError as e:
        logger.warning(f"{req.method} {req.path} - {type(e).__name__}: {e.message}")
        res.status(e.status_code).json({
            "error": type(e).__name__,
            "message": e.message,
            "request_id": req.id
        })
    except Exception as e:
        logger.error(f"Unhandled error on {req.method} {req.path}", exc_info=True)
        res.status(500).json({
            "error": "Internal Server Error",
            "request_id": req.id
        })
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
@app.post("/users")
@validate_body(UserCreate)
def create_user(req, res, ctx, body: UserCreate):
    user = ctx.services.user.create(body)
    
    # Queue background task
    send_welcome_email.queue(user.email, user.name)
    
    res.status(201).json(user)
```

## File Upload Handling

```python
# routes/files.py
from hypern.exceptions import ValidationError
import os

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf", ".doc", ".docx"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

def validate_upload(file):
    _, ext = os.path.splitext(file.filename)
    if ext.lower() not in ALLOWED_EXTENSIONS:
        raise ValidationError(f"File type {ext} not allowed")
    
    if file.size > MAX_FILE_SIZE:
        raise ValidationError("File exceeds maximum size")

@app.post("/upload")
def upload_file(req, res, ctx):
    files = req.files()
    
    if "file" not in files:
        raise ValidationError("No file provided")
    
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
    import csv
    import io
    
    def generate_csv():
        users = ctx.db.query("SELECT id, name, email FROM users")
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["id", "name", "email"])
        writer.writeheader()
        
        for user in users:
            yield output.getvalue()
            output.truncate(0)
            output.seek(0)
            writer.writerow(user)
    
    res.stream(
        generate_csv(),
        content_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=users.csv"}
    )
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
from hypern.exceptions import UnauthorizedError
from functools import wraps

def require_auth(handler):
    @wraps(handler)
    def wrapper(req, res, ctx, *args, **kwargs):
        auth_header = req.header("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise UnauthorizedError("Missing or invalid authorization")
        
        token = auth_header[7:]
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
            ctx.user_id = payload["user_id"]
            ctx.user = get_user(payload["user_id"])
        except jwt.InvalidTokenError:
            raise UnauthorizedError("Invalid token")
        
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

1. **Use connection pooling** - Default in Hypern
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
        "database": check_database(ctx),
        "cache": check_cache(ctx),
    }
    
    all_healthy = all(checks.values())
    status = 200 if all_healthy else 503
    
    res.status(status).json({
        "status": "healthy" if all_healthy else "unhealthy",
        "checks": checks
    })

def check_database(ctx):
    try:
        ctx.db.query("SELECT 1")
        return "ok"
    except:
        return "error"
```
