# Validation

Hypern provides high-performance request validation using [msgspec](https://jcristharif.com/msgspec/).

## Basic Validation

```python
from hypern import Hypern
from hypern.validation import validate_body
import msgspec

app = Hypern()

class UserSchema(msgspec.Struct):
    name: str
    email: str
    age: int

@app.post("/users")
@validate_body(UserSchema)
def create_user(req, res, ctx, body: UserSchema):
    # body is validated UserSchema instance
    res.status(201).json({
        "name": body.name,
        "email": body.email,
        "age": body.age
    })
```

## Schema Definition

### Using msgspec.Struct

```python
import msgspec
from typing import Optional

class ProductSchema(msgspec.Struct):
    # Required fields
    name: str
    price: float
    
    # Optional with default
    description: Optional[str] = None
    quantity: int = 0
    
    # List of items
    tags: list[str] = []
```

## Query Parameter Validation

```python
import msgspec
from hypern.validation import validate_query

class SearchParams(msgspec.Struct):
    q: str
    page: int = 1
    limit: int = 20
    sort: str = "desc"

@app.get("/search")
@validate_query(SearchParams)
def search(req, res, ctx, query: SearchParams):
    res.json({
        "query": query.q,
        "page": query.page,
        "limit": query.limit,
        "sort": query.sort
    })
```

## Path Parameter Validation

```python
import msgspec
from hypern.validation import validate_params

class UserParams(msgspec.Struct):
    user_id: str

@app.get("/users/:user_id")
@validate_params(UserParams)
def get_user(req, res, ctx, params: UserParams):
    res.json({"user_id": params.user_id})
```

## Combined Validation

```python
import msgspec
from hypern.validation import validate

class CreateOrderBody(msgspec.Struct):
    items: list[dict]
    shipping_address: str

class CreateOrderQuery(msgspec.Struct):
    express: bool = False

@app.post("/orders")
@validate(body=CreateOrderBody, query=CreateOrderQuery)
def create_order(req, res, ctx, body: CreateOrderBody, query: CreateOrderQuery):
    res.json({
        "items": body.items,
        "express": query.express
    })
```

## Nested Schemas

```python
import msgspec

class AddressSchema(msgspec.Struct):
    street: str
    city: str
    country: str
    zip_code: str

class CustomerSchema(msgspec.Struct):
    name: str
    email: str
    billing_address: AddressSchema
    shipping_address: Optional[AddressSchema] = None

@app.post("/customers")
@validate_body(CustomerSchema)
def create_customer(req, res, ctx, body: CustomerSchema):
    res.json({
        "name": body.name,
        "city": body.billing_address.city
    })
```

## Error Handling

Validation errors return 400 status with details:

```json
{
    "message": "Expected `str`, got `int`",
    "errors": [
        {
            "type": "validation_error",
            "msg": "Expected `str`, got `int`"
        }
    ]
}
```

### Custom Error Response

```python
from hypern.validation import Validator, ValidationError

validator = Validator(UserSchema)

@app.post("/users")
def create_user(req, res, ctx):
    try:
        body = validator.validate(req.body_bytes())
        res.json({"valid": True, "data": body})
    except ValidationError as e:
        res.status(400).json(e.to_dict())
```

## Manual Validation

Use the `Validator` class for manual validation:

```python
from hypern.validation import Validator
import msgspec

class UserSchema(msgspec.Struct):
    name: str
    email: str
    age: int

validator = Validator(UserSchema)

@app.post("/users")
def create_user(req, res, ctx):
    try:
        # Validate JSON body
        user = validator.validate(req.body_bytes())
        
        # Use validated data
        res.json({
            "name": user.name,
            "email": user.email
        })
    except Exception as e:
        res.status(400).json({"error": str(e)})
```

## Type Coercion for Query/Path Parameters

Query and path parameters come as strings. The validation decorators automatically coerce them to the expected types:

```python
class QueryParams(msgspec.Struct):
    page: int = 1
    limit: int = 10

@app.get("/items")
@validate_query(QueryParams)
def list_items(req, res, ctx, query: QueryParams):
    # query.page and query.limit are automatically converted to int
    res.json({
        "page": query.page,
        "limit": query.limit
    })
```

## Important Notes

### Handler Signature with ctx Parameter

All route handlers in Hypern receive three parameters: `req`, `res`, and `ctx`. When using validation decorators, you **must** include the `ctx` parameter in your handler signature:

```python
# ✅ Correct - includes ctx parameter
@app.post("/users")
@validate_body(UserSchema)
def create_user(req, res, ctx, body: UserSchema):
    res.json({"name": body.name})

# ❌ Wrong - missing ctx parameter
@app.post("/users")
@validate_body(UserSchema)
def create_user(req, res, body: UserSchema):  # This will cause errors!
    res.json({"name": body.name})
```

The validation decorators pass validated data as additional parameters **after** `ctx`:

```python
# Body validation: (req, res, ctx, body)
@validate_body(Schema)
def handler(req, res, ctx, body: Schema):
    pass

# Query validation: (req, res, ctx, query)
@validate_query(Schema)
def handler(req, res, ctx, query: Schema):
    pass

# Combined validation: (req, res, ctx, body, query)
@validate(body=BodySchema, query=QuerySchema)
def handler(req, res, ctx, body: BodySchema, query: QuerySchema):
    pass
```

