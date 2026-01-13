# Project Structure

This guide explains how to organize your Hypern applications for maintainability and scalability.

## Overview

A well-organized project structure makes your code easier to understand, test, and maintain. This guide presents best practices for structuring Hypern applications of various sizes.

## Small Applications

For simple APIs or microservices, a flat structure works well:

```
my-app/
├── main.py              # Application entry point
├── handlers.py          # Request handlers
├── models.py            # Data models
├── config.py            # Configuration
├── requirements.txt     # Python dependencies
└── README.md           # Project documentation
```

### Example: Simple API

```python
# main.py
from hypern import Hypern
from handlers import register_routes
from config import get_config

def create_app():
    app = Hypern()
    register_routes(app)
    return app

if __name__ == "__main__":
    app = create_app()
    config = get_config()
    app.start(**config)
```

```python
# handlers.py
from hypern import Request, Response
import json

def health_handler(request: Request, response: Response):
    response.status(200)
    response.header("Content-Type", "application/json")
    response.body_str('{"status": "healthy"}')
    response.finish()

def register_routes(app):
    app.add_route("GET", "/health", health_handler)
```

```python
# config.py
import os

def get_config():
    return {
        "host": os.getenv("HOST", "0.0.0.0"),
        "port": int(os.getenv("PORT", 5000)),
        "workers": int(os.getenv("WORKERS", 4)),
    }
```

## Medium Applications

For more complex applications, organize code by feature or layer:

```
my-app/
├── app/
│   ├── __init__.py
│   ├── main.py          # Application factory
│   ├── config.py        # Configuration management
│   ├── handlers/        # Request handlers
│   │   ├── __init__.py
│   │   ├── users.py
│   │   ├── products.py
│   │   └── orders.py
│   ├── models/          # Data models
│   │   ├── __init__.py
│   │   ├── user.py
│   │   └── product.py
│   ├── services/        # Business logic
│   │   ├── __init__.py
│   │   ├── user_service.py
│   │   └── product_service.py
│   └── utils/           # Utilities
│       ├── __init__.py
│       └── validators.py
├── tests/               # Test suite
│   ├── __init__.py
│   ├── test_users.py
│   └── test_products.py
├── requirements.txt
├── .env.example
└── README.md
```

### Application Factory Pattern

```python
# app/main.py
from hypern import Hypern
from app.handlers import users, products
from app.config import Config

def create_app(config: Config = None):
    """Application factory function."""
    if config is None:
        config = Config()
    
    app = Hypern()
    
    # Register route blueprints
    users.register_routes(app)
    products.register_routes(app)
    
    return app

def main():
    config = Config()
    app = create_app(config)
    app.start(
        host=config.HOST,
        port=config.PORT,
        workers=config.WORKERS
    )

if __name__ == "__main__":
    main()
```

### Handler Modules

```python
# app/handlers/users.py
from hypern import Request, Response
from app.services.user_service import UserService
import json

user_service = UserService()

def get_users_handler(request: Request, response: Response):
    """Get all users."""
    try:
        users = user_service.get_all()
        response.status(200)
        response.header("Content-Type", "application/json")
        response.body_str(json.dumps(users))
    except Exception as e:
        response.status(500)
        response.body_str(json.dumps({"error": str(e)}))
    finally:
        response.finish()

def get_user_handler(request: Request, response: Response):
    """Get user by ID."""
    try:
        user_id = request.path_params.get("id")
        user = user_service.get_by_id(user_id)
        
        if user:
            response.status(200)
            response.body_str(json.dumps(user))
        else:
            response.status(404)
            response.body_str(json.dumps({"error": "User not found"}))
    except Exception as e:
        response.status(500)
        response.body_str(json.dumps({"error": str(e)}))
    finally:
        response.finish()

def register_routes(app):
    """Register user routes."""
    app.add_route("GET", "/api/users", get_users_handler)
    app.add_route("GET", "/api/users/{id}", get_user_handler)
```

## Large Applications

For enterprise applications, use a more sophisticated structure:

```
my-app/
├── src/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── development.py
│   │   │   └── production.py
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── v1/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── users.py
│   │   │   │   └── products.py
│   │   │   └── v2/
│   │   │       └── __init__.py
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── dependencies.py
│   │   │   ├── security.py
│   │   │   └── database.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── user.py
│   │   │   └── product.py
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── user.py
│   │   │   └── product.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── user_service.py
│   │   │   └── product_service.py
│   │   ├── repositories/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   └── user_repository.py
│   │   ├── middleware/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   └── logging.py
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── validators.py
│   │       └── helpers.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_services.py
│   │   └── test_repositories.py
│   ├── integration/
│   │   └── test_api.py
│   └── e2e/
│       └── test_workflows.py
├── docs/
│   ├── api.md
│   └── deployment.md
├── scripts/
│   ├── migrate.py
│   └── seed.py
├── .env.example
├── .gitignore
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Directory Breakdown

### `/app` or `/src/app`

Main application code.

**Purpose:** Contains all application logic.

### `/app/api` or `/app/handlers`

API endpoints and request handlers.

**Purpose:** Handle HTTP requests and responses.

**Organization:**
- By resource (users.py, products.py)
- By version (v1/, v2/)
- By feature (auth/, billing/)

### `/app/models`

Data models and database schemas.

**Purpose:** Define data structures.

```python
# models/user.py
from dataclasses import dataclass
from typing import Optional

@dataclass
class User:
    id: int
    username: str
    email: str
    is_active: bool = True
```

### `/app/schemas`

Request/response validation schemas.

**Purpose:** Validate input/output data.

```python
# schemas/user.py
from typing import Optional
from pydantic import BaseModel, EmailStr

class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: int
    username: str
    email: EmailStr
```

### `/app/services`

Business logic layer.

**Purpose:** Implement business rules and operations.

```python
# services/user_service.py
from app.repositories.user_repository import UserRepository
from app.models.user import User

class UserService:
    def __init__(self):
        self.repository = UserRepository()
    
    def create_user(self, username: str, email: str) -> User:
        # Business logic
        user = self.repository.create(username, email)
        # Send welcome email, etc.
        return user
```

### `/app/repositories`

Data access layer.

**Purpose:** Abstract database operations.

```python
# repositories/user_repository.py
from typing import List, Optional
from app.models.user import User

class UserRepository:
    def get_all(self) -> List[User]:
        # Database query
        pass
    
    def get_by_id(self, user_id: int) -> Optional[User]:
        # Database query
        pass
    
    def create(self, username: str, email: str) -> User:
        # Database insert
        pass
```

### `/app/middleware`

Custom middleware components.

**Purpose:** Process requests/responses globally.

### `/app/utils`

Helper functions and utilities.

**Purpose:** Shared utility functions.

### `/app/config`

Configuration management.

**Purpose:** Manage environment-specific settings.

```python
# config/base.py
import os

class BaseConfig:
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", 5000))
    DEBUG = False

# config/development.py
from .base import BaseConfig

class DevelopmentConfig(BaseConfig):
    DEBUG = True
    WORKERS = 1

# config/production.py
from .base import BaseConfig

class ProductionConfig(BaseConfig):
    WORKERS = 4
    MAX_CONNECTIONS = 10000
```

### `/tests`

Test suite.

**Organization:**
- `unit/` - Unit tests
- `integration/` - Integration tests
- `e2e/` - End-to-end tests

## Design Patterns

### Layered Architecture

Separate concerns into distinct layers:

```
Presentation Layer (Handlers)
        ↓
Business Logic Layer (Services)
        ↓
Data Access Layer (Repositories)
        ↓
Database
```

### Dependency Injection

Pass dependencies explicitly:

```python
# app/main.py
def create_app():
    app = Hypern()
    
    # Create dependencies
    db = Database()
    user_repo = UserRepository(db)
    user_service = UserService(user_repo)
    
    # Inject into handlers
    def get_users(request, response):
        users = user_service.get_all()
        # ...
    
    app.add_route("GET", "/users", get_users)
    return app
```

### Repository Pattern

Abstract data access:

```python
class BaseRepository:
    def get_all(self):
        raise NotImplementedError
    
    def get_by_id(self, id):
        raise NotImplementedError
    
    def create(self, data):
        raise NotImplementedError
    
    def update(self, id, data):
        raise NotImplementedError
    
    def delete(self, id):
        raise NotImplementedError
```

## Configuration Management

### Environment Variables

Use `.env` files for configuration:

```bash
# .env
HOST=0.0.0.0
PORT=8000
WORKERS=4
DATABASE_URL=postgresql://user:pass@localhost/db
SECRET_KEY=your-secret-key
DEBUG=true
```

### Configuration Class

```python
# config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", 5000))
    WORKERS = int(os.getenv("WORKERS", 4))
    DATABASE_URL = os.getenv("DATABASE_URL")
    SECRET_KEY = os.getenv("SECRET_KEY")
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
```

## Best Practices

### 1. Separation of Concerns

Keep different responsibilities in separate modules:
- Handlers handle HTTP
- Services handle business logic
- Repositories handle data access

### 2. DRY (Don't Repeat Yourself)

Extract common code into utilities:

```python
# utils/response.py
import json
from hypern import Response

def json_response(response: Response, data: dict, status: int = 200):
    response.status(status)
    response.header("Content-Type", "application/json")
    response.body_str(json.dumps(data))
    response.finish()

def error_response(response: Response, message: str, status: int = 500):
    json_response(response, {"error": message}, status)
```

### 3. Type Hints

Use type hints everywhere:

```python
from typing import List, Optional
from app.models.user import User

def get_users() -> List[User]:
    pass

def get_user_by_id(user_id: int) -> Optional[User]:
    pass
```

### 4. Documentation

Document your code:

```python
def create_user(username: str, email: str) -> User:
    """
    Create a new user.
    
    Args:
        username: The username for the new user
        email: The email address for the new user
    
    Returns:
        The created User object
    
    Raises:
        ValueError: If username or email is invalid
    """
    pass
```

### 5. Testing Structure

Mirror your app structure in tests:

```
app/
├── handlers/
│   └── users.py
tests/
├── unit/
│   └── handlers/
│       └── test_users.py
```

## Example: Complete Structure

Here's a complete example of a well-structured application:

```python
# src/app/main.py
from hypern import Hypern
from app.config import Config
from app.api.v1 import users, products

def create_app(config: Config = None) -> Hypern:
    if config is None:
        config = Config()
    
    app = Hypern()
    
    # Register API v1 routes
    users.register_routes(app)
    products.register_routes(app)
    
    return app

if __name__ == "__main__":
    config = Config()
    app = create_app(config)
    app.start(
        host=config.HOST,
        port=config.PORT,
        workers=config.WORKERS,
        max_connections=config.MAX_CONNECTIONS
    )
```

## Next Steps

- [Application Guide](../guide/application.md) - Learn about application lifecycle
- [Routing](../guide/routing.md) - Advanced routing techniques
- [Testing](../advanced/testing.md) - Test your application
- [Deployment](../advanced/deployment.md) - Deploy to production

## Resources

- [Python Project Structure Best Practices](https://realpython.com/python-application-layouts/)
- [Clean Architecture in Python](https://www.cosmicpython.com/)
- [The Twelve-Factor App](https://12factor.net/)