# GraphQL

Hypern supports GraphQL via [Strawberry](https://strawberry.rocks/), an optional dependency.

## Installation

```bash
pip install hypern[graphql]
# or
pip install strawberry-graphql
```

## Quick Start

```python
import strawberry
from hypern import Hypern
from hypern.graphql import GraphQLRoute

@strawberry.type
class Query:
    @strawberry.field
    def hello(self) -> str:
        return "world"

    @strawberry.field
    def greeting(self, name: str) -> str:
        return f"Hello, {name}!"

schema = strawberry.Schema(Query)
app = Hypern()
app.mount("/graphql", GraphQLRoute(schema))
```

## Features

- **POST `/graphql`** — Standard GraphQL JSON body: `{"query": "...", "variables": {...}}`
- **GET `/graphql?query=...`** — Simple queries via query parameter
- **GraphiQL IDE** — Served at `GET /graphql` when `Accept: text/html`

## API Reference

### GraphQLRoute

```python
GraphQLRoute(schema, graphiql=True)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `schema` | `strawberry.Schema` | — | The Strawberry schema to serve |
| `graphiql` | `bool` | `True` | Serve GraphiQL IDE on GET with text/html accept |

### Request Format

**POST request:**

```json
{
    "query": "query GetUser($id: ID!) { user(id: $id) { name email } }",
    "variables": {"id": "123"},
    "operationName": "GetUser"
}
```

**GET request:**

```
GET /graphql?query={hello}
```

### Response Format

```json
{
    "data": {"hello": "world"},
    "errors": null
}
```

## Example with Mutations

```python
import strawberry
from typing import List

@strawberry.type
class User:
    id: str
    name: str
    email: str

users_db: List[User] = []

@strawberry.type
class Query:
    @strawberry.field
    def users(self) -> List[User]:
        return users_db

    @strawberry.field
    def user(self, id: str) -> User | None:
        return next((u for u in users_db if u.id == id), None)

@strawberry.type
class Mutation:
    @strawberry.mutation
    def create_user(self, name: str, email: str) -> User:
        user = User(id=str(len(users_db) + 1), name=name, email=email)
        users_db.append(user)
        return user

schema = strawberry.Schema(query=Query, mutation=Mutation)
app.mount("/graphql", GraphQLRoute(schema))
```

## Disabling GraphiQL

For production, you may want to disable the GraphiQL IDE:

```python
app.mount("/graphql", GraphQLRoute(schema, graphiql=False))
```
