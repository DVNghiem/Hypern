# Error Handling

Hypern provides comprehensive error handling capabilities with custom exceptions and error responses.

## Built-in Exceptions

Hypern defines several built-in exception classes for common scenarios:

```python
from hypern.exceptions import (
    RequestError,           # General request errors
    ValidationError,        # Validation failures
    NotFoundError,         # Resource not found
    UnauthorizedError,     # Authentication required
    ForbiddenError,        # Access denied
    ConflictError,         # Resource conflict
    InternalServerError,   # Server errors
)
```

## Basic Error Handling

```python
from hypern import Hypern
from hypern.exceptions import NotFoundError, ValidationError

app = Hypern()

@app.get("/users/:id")
def get_user(req, res, ctx):
    user_id = req.param("id")
    
    # Check if user exists
    user = find_user_by_id(user_id)
    if not user:
        raise NotFoundError(f"User {user_id} not found")
    
    res.json(user)

@app.post("/users")
def create_user(req, res, ctx):
    body = req.json()
    
    # Validate input
    if not body.get("email"):
        raise ValidationError("Email is required")
    
    res.status(201).json({"message": "User created"})
```

## Custom Error Classes

Create custom exception classes for domain-specific errors:

```python
from hypern.exceptions import RequestError

class DatabaseError(RequestError):
    def __init__(self, message: str, code: str = "DB_ERROR"):
        self.status_code = 500
        self.message = message
        self.code = code

class AuthenticationError(RequestError):
    def __init__(self, message: str = "Authentication failed"):
        self.status_code = 401
        self.message = message
        self.code = "AUTH_ERROR"

class PaymentError(RequestError):
    def __init__(self, message: str, amount: float = None):
        self.status_code = 402
        self.message = message
        self.code = "PAYMENT_ERROR"
        self.amount = amount

# Usage
@app.post("/charge")
def charge_user(req, res, ctx):
    body = req.json()
    amount = body.get("amount")
    
    try:
        process_payment(amount)
    except Exception as e:
        raise PaymentError(str(e), amount)
```

## Error Response Format

Exceptions are automatically converted to JSON responses:

```python
# Exception
raise NotFoundError("Resource not found")

# Response
{
    "error": "Not Found",
    "message": "Resource not found",
    "status_code": 404,
    "timestamp": "2024-01-17T10:30:00Z"
}
```

## Error Handler Middleware

Create custom error handlers using middleware:

```python
from hypern import Hypern
from hypern.exceptions import RequestError
import traceback

app = Hypern()

@app.middleware("after_route")
def error_handler(req, res, ctx, next):
    try:
        next()
    except RequestError as e:
        res.status(e.status_code).json({
            "error": type(e).__name__,
            "message": e.message,
            "code": getattr(e, "code", "ERROR")
        })
    except Exception as e:
        # Log error
        print(f"Unexpected error: {e}")
        traceback.print_exc()
        
        res.status(500).json({
            "error": "Internal Server Error",
            "message": "An unexpected error occurred"
        })
```

## Validation Error Details

Provide detailed validation error information:

```python
import msgspec
from hypern.validation import validate_body
from hypern.exceptions import ValidationError

class UserSchema(msgspec.Struct):
    name: str
    email: str
    age: int

@app.post("/users")
@validate_body(UserSchema)
def create_user(req, res, ctx, body: UserSchema):
    # Additional validation
    if body.age < 18:
        raise ValidationError("User must be at least 18 years old")
    
    if user_exists(body.email):
        raise ValidationError("Email already registered")
    
    res.status(201).json({"message": "User created"})
```

## Database Error Handling

```python
from hypern import Hypern
from hypern.exceptions import InternalServerError, ConflictError
from hypern.database import Database

app = Hypern()
db = Database("postgresql://localhost/myapp")

@app.post("/products")
def create_product(req, res, ctx):
    body = req.json()
    
    try:
        result = db.execute(
            "INSERT INTO products (name, price) VALUES (?, ?)",
            [body["name"], body["price"]]
        )
        res.status(201).json({"id": result.last_insert_id})
    except Exception as e:
        if "unique constraint" in str(e):
            raise ConflictError("Product name already exists")
        raise InternalServerError(f"Database error: {str(e)}")
```

## Async Error Handling

```python
from hypern import Hypern
from hypern.exceptions import RequestError
import asyncio

app = Hypern()

@app.get("/async-data")
async def get_async_data(req, res, ctx):
    try:
        data = await fetch_remote_data()
        res.json(data)
    except asyncio.TimeoutError:
        raise RequestError("Request timeout", status_code=504)
    except Exception as e:
        raise RequestError(str(e), status_code=502)
```

## Try-Catch Patterns

### Option 1: Let exceptions propagate

```python
@app.get("/users/:id")
def get_user(req, res, ctx):
    user = db.query(f"SELECT * FROM users WHERE id = {req.param('id')}")
    if not user:
        raise NotFoundError("User not found")
    res.json(user)
```

### Option 2: Handle and transform

```python
@app.get("/users/:id")
def get_user(req, res, ctx):
    try:
        user = db.query(f"SELECT * FROM users WHERE id = {req.param('id')}")
        if not user:
            raise NotFoundError("User not found")
        res.json(user)
    except NotFoundError:
        raise  # Re-raise
    except Exception as e:
        raise InternalServerError(str(e))
```

### Option 3: Return error response

```python
@app.get("/users/:id")
def get_user(req, res, ctx):
    try:
        user = db.query(f"SELECT * FROM users WHERE id = {req.param('id')}")
        if not user:
            res.status(404).json({"error": "User not found"})
            return
        res.json(user)
    except Exception as e:
        res.status(500).json({"error": str(e)})
```

## Error Logging

```python
import logging
from hypern import Hypern
from hypern.exceptions import RequestError

logger = logging.getLogger(__name__)
app = Hypern()

@app.middleware("after_route")
def log_errors(req, res, ctx, next):
    try:
        next()
    except RequestError as e:
        logger.warning(f"{req.method} {req.path} - {type(e).__name__}: {e.message}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error on {req.method} {req.path}: {e}", exc_info=True)
        raise
```

## Best Practices

1. **Use appropriate status codes** - 400, 401, 403, 404, 409, 422, 500, etc.
2. **Provide error codes** - Use consistent, machine-readable error codes
3. **Include request IDs** - Trace errors through logs
4. **Don't expose internals** - Hide stack traces in production
5. **Log all errors** - Comprehensive logging for debugging
6. **Handle async errors** - Properly catch exceptions in async handlers
7. **Validate early** - Catch errors at the validation stage
8. **Use middleware** - Centralize error handling
9. **Test error scenarios** - Include error handling in tests
10. **Document errors** - Include error responses in API documentation
