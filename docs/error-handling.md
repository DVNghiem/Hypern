# Error Handling

Hypern provides comprehensive error handling with `HTTPException` subclasses,
per-type `ExceptionHandler` registration, and an `@error_boundary` decorator
for local exception capture.

## Built-in Exceptions

Every HTTP exception inherits from `HTTPException` and carries a `status_code`,
`detail` message, optional `data` payload, and optional `headers`. The
exception envelope returned to clients is:

```json
{
  "error": true,
  "status_code": 404,
  "message": "Not Found"
}
```

Available exceptions (all importable from `hypern`):

| Exception | Status | Purpose |
| --- | --- | --- |
| `HTTPException` | any | Base class — pass any status code |
| `BadRequest` | 400 | General request errors |
| `Unauthorized` | 401 | Authentication required |
| `Forbidden` | 403 | Access denied |
| `NotFound` | 404 | Resource not found |
| `MethodNotAllowed` | 405 | HTTP method not allowed |
| `Conflict` | 409 | Resource conflict |
| `UnprocessableEntity` | 422 | Validation failures |
| `TooManyRequests` | 429 | Rate limit exceeded |
| `InternalServerError` | 500 | Server errors |
| `ServiceUnavailable` | 503 | Service unavailable |

Helpers: `ExceptionHandler` (per-type handler registry), `error_boundary`
(handler-local exception capture decorator).

## Basic Error Handling

```python
from hypern import Hypern, NotFound, BadRequest

app = Hypern()

@app.get("/users/:id")
def get_user(req, res, ctx):
    user_id = req.param("id")

    user = find_user_by_id(user_id)
    if not user:
        raise NotFound(f"User {user_id} not found")

    res.json(user)

@app.post("/users")
def create_user(req, res, ctx):
    body = req.json()

    if not body.get("email"):
        raise BadRequest("Email is required", data={"field": "email"})

    res.status(201).json({"message": "User created"})
```

## Custom Error Classes

Subclass `HTTPException` to add domain-specific errors. The framework will
serialize any subclass through the same envelope:

```python
from hypern import HTTPException

class DatabaseError(HTTPException):
    def __init__(self, message: str):
        super().__init__(500, message, data={"code": "DB_ERROR"})

class PaymentError(HTTPException):
    def __init__(self, message: str, amount: float | None = None):
        super().__init__(
            402,
            message,
            data={"code": "PAYMENT_ERROR", "amount": amount},
        )

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

Raising an `HTTPException` (or any subclass) returns JSON automatically:

```python
raise NotFound("Resource not found")

# Response body
{
    "error": true,
    "status_code": 404,
    "message": "Resource not found"
}
```

## `ExceptionHandler` — Per-Type Handlers

`ExceptionHandler` lets you register custom handlers for specific exception
classes and wire them into the application:

```python
from hypern import Hypern, ExceptionHandler, HTTPException, BadRequest

app = Hypern()
handler = ExceptionHandler()

@handler.handle(HTTPException)
def http_handler(req, res, exc):
    res.status(exc.status_code).json(exc.to_dict())

@handler.handle(ValueError)
def value_error_handler(req, res, exc):
    res.status(400).json({"error": True, "message": str(exc)})

app.set_exception_handler(handler)
```

`ExceptionHandler.handle(exc_class)` returns a decorator. `add_handler(...)`
registers a handler programmatically. `set_default_handler(...)` catches
anything that has no specific handler.

## `@error_boundary` Decorator

Wrap a single handler to catch exceptions locally instead of relying on global
plumbing. Handlers wrapped in `@error_boundary` raise `HTTPException` straight
to JSON, and route everything else through the registered default handler:

```python
from hypern import Hypern, error_boundary, NotFound

app = Hypern()

@app.get("/users/:id")
@error_boundary
def get_user(req, res, ctx):
    user = db.fetch_user(req.param("id"))
    if user is None:
        raise NotFound("User not found")
    res.json(user)
```

## Validation Error Details

`UnprocessableEntity` (or `BadRequest`) is the right tool for input validation:

```python
import msgspec
from hypern import Json, UnprocessableEntity, Conflict

class UserSchema(msgspec.Struct):
    name: str
    email: str
    age: int

@app.post("/users")
def create_user(req, res, ctx, body: UserSchema = Json()):
    if body.age < 18:
        raise UnprocessableEntity(
            "User must be at least 18 years old",
            data={"field": "age", "value": body.age},
        )

    if user_exists(body.email):
        raise Conflict("Email already registered",
                       data={"field": "email"})

    res.status(201).json({"message": "User created"})
```

## Persistence Error Handling

```python
from hypern import Hypern, Inject, Conflict, InternalServerError

app = Hypern()

class ProductRepository:
    def create(self, product):
        # The application's persistence adapter owns this operation.
        return {"id": "new-product", **product}

app.provide(ProductRepository, ProductRepository())

@app.post("/products")
def create_product(
    req,
    res,
    ctx,
    product_repository: ProductRepository = Inject(),
):
    body = req.json()

    try:
        product = product_repository.create(body)
        res.status(201).json(product)
    except Exception as e:
        if "unique constraint" in str(e):
            raise Conflict("Product name already exists")
        raise InternalServerError(f"Persistence error: {str(e)}")
```

## Async Error Handling

```python
from hypern import Hypern, HTTPException
import asyncio

app = Hypern()

@app.get("/async-data")
async def get_async_data(req, res, ctx):
    try:
        data = await fetch_remote_data()
        res.json(data)
    except asyncio.TimeoutError:
        raise HTTPException(504, "Request timeout")
    except Exception as e:
        raise HTTPException(502, str(e))
```

## Try-Catch Patterns

### Option 1: Let exceptions propagate

```python
from hypern import NotFound

@app.get("/users/:id")
def get_user(req, res, ctx):
    user = db.fetch_user(req.param("id"))
    if user is None:
        raise NotFound("User not found")
    res.json(user)
```

### Option 2: Handle and transform

```python
from hypern import NotFound, InternalServerError

@app.get("/users/:id")
def get_user(req, res, ctx):
    try:
        user = db.fetch_user(req.param("id"))
        if user is None:
            raise NotFound("User not found")
        res.json(user)
    except NotFound:
        raise  # Re-raise
    except Exception as e:
        raise InternalServerError(str(e))
```

### Option 3: Return error response

```python
@app.get("/users/:id")
def get_user(req, res, ctx):
    try:
        user = db.fetch_user(req.param("id"))
        if user is None:
            res.status(404).json({"error": "User not found"})
            return
        res.json(user)
    except Exception as e:
        res.status(500).json({"error": str(e)})
```

## Error Logging

```python
import logging
from hypern import Hypern, HTTPException

logger = logging.getLogger(__name__)
app = Hypern()

@app.middleware("after_route")
def log_errors(req, res, ctx, next):
    try:
        next()
    except HTTPException as e:
        logger.warning(f"{req.method} {req.path} - {type(e).__name__}: {e.detail}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error on {req.method} {req.path}: {e}", exc_info=True)
        raise
```

## Best Practices

1. **Use appropriate status codes** — 400, 401, 403, 404, 409, 422, 500, etc.
2. **Provide machine-readable codes** — put them in the `data` field, not in the message.
3. **Include request IDs** — trace errors through logs using `ctx.request_id`.
4. **Don't expose internals** — hide stack traces in production.
5. **Log all errors** — comprehensive logging for debugging.
6. **Handle async errors** — properly catch exceptions in async handlers.
7. **Validate early** — catch errors at the validation stage.
8. **Centralize** — register one `ExceptionHandler` instead of try/except in every route.
9. **Test error scenarios** — include error handling in tests.
10. **Document errors** — list the error envelope in your API docs.