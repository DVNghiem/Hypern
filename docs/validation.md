# Request Binding and Validation

Hypern validates request data through typed handler parameters. Binding plans are compiled when application registration freezes, so request handling performs no signature inspection.

Each non-transport handler parameter declares exactly one source:

| Marker | Source |
| --- | --- |
| `Json()` | JSON request body, decoded with the parameter annotation. |
| `Query(name=None)` | A `msgspec.Struct` query object or one scalar query value. |
| `Header(name)` | A request header. |
| `Path(name=None)` | A declared route parameter. |
| `Body()` | The raw request body as `bytes`. |
| `Inject(key=None)` | A provider registered with `app.provide()`. |

`req`, `res`, and `ctx` are reserved transport parameters and may appear anywhere in a handler signature.

## JSON bodies

```python
import msgspec

from hypern import Hypern, Json

app = Hypern()


class UserInput(msgspec.Struct):
    name: str
    email: str
    age: int


@app.post("/users")
def create_user(res, payload: UserInput = Json()):
    res.status(201).json({
        "name": payload.name,
        "email": payload.email,
        "age": payload.age,
    })
```

Malformed JSON, missing fields, and invalid field types produce a `400 Bad Request` response through the normal exception pipeline.

## Query parameters

Use `Query()` with a `msgspec.Struct` to bind the complete query string. String values are coerced to the declared field types and omitted fields use struct defaults.

```python
from hypern import Query


class SearchQuery(msgspec.Struct):
    q: str = ""
    page: int = 1
    limit: int = 20


@app.get("/search")
def search(res, query: SearchQuery = Query()):
    res.json({"q": query.q, "page": query.page, "limit": query.limit})
```

For one scalar query parameter, provide its external name when it differs from the Python parameter name:

```python
@app.get("/items")
def list_items(res, page_size: int = Query("limit")):
    res.json({"limit": page_size})
```

## Path parameters and headers

```python
from hypern import Header, Path


@app.get("/users/:user_id")
def get_user(
    res,
    user_id: int = Path(),
    request_id: str | None = Header("X-Request-ID"),
):
    res.json({"user_id": user_id, "request_id": request_id})
```

`Path()` uses the Python parameter name by default. Both `Path(name)` and `Query(name)` accept an explicit external name. Missing required values and coercion failures are validation errors; optional header annotations accept missing headers.

## Raw request bodies

Use `Body()` when parsing and validation belong to the application:

```python
from hypern import Body


@app.post("/events")
def receive_event(res, payload: bytes = Body()):
    res.json({"size": len(payload)})
```

## Combining sources

Every parameter declares its own source, so declaration order does not couple dependency injection to validation:

```python
from hypern import Inject, Json, Query


@app.post("/orders")
async def create_order(
    payload: OrderInput = Json(),
    service: OrderService = Inject(),
    options: OrderQuery = Query(),
):
    return await service.create(payload, options)
```

`req`, `res`, and `ctx` remain reserved transport parameters and may appear anywhere in the handler signature.

## Errors and marker composition

Malformed JSON, invalid field types, and missing required query, header, or path values are request-time validation errors. They are handled by Hypern's normal exception pipeline and produce the configured validation response (the default is `400 Bad Request`). Invalid marker declarations, such as `Json()` without an annotation, `Body()` with a non-`bytes` annotation, or a `Path()` name absent from the route, fail when the handler plan is compiled.

Markers compose by parameter rather than by decorator wrapping. You can reorder parameters without changing where they are read from, and no DI or validation decorator order affects binding. The legacy decorator-based validation API is removed.
