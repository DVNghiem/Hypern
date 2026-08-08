# SQLAlchemy Integration

Hypern does not provide a built-in database adapter. Your application owns the
SQLAlchemy engine, sessions, transactions, and shutdown sequence. This keeps
database configuration independent from the framework and lets you choose the
SQLAlchemy dialect and ORM style that fits your project.

This guide uses SQLAlchemy's asyncio extension and PostgreSQL. The same
structure works with other async dialects.

## What you will build

The integration has three lifetimes:

| Object | Lifetime | Rule |
| --- | --- | --- |
| `AsyncEngine` | Application | Create once and dispose on shutdown. |
| `AsyncSession` | One database operation or request | Create with `async with`; never share it between concurrent tasks. |
| Transaction | One unit of work | Commit on success and roll back on failure. |

```text
Hypern application
        |
        +-- Database singleton
        |     +-- AsyncEngine
        |     +-- async_sessionmaker
        |
        +-- Handler
              +-- async with database.session() as session
              +-- execute queries and commit the transaction
```

## Installation

Install SQLAlchemy and an async database driver. For PostgreSQL:

```bash
poetry add sqlalchemy asyncpg
```

Or with pip:

```bash
python -m pip install sqlalchemy asyncpg
```

For a synchronous SQLAlchemy integration, install a synchronous driver instead:

```bash
poetry add sqlalchemy "psycopg[binary]"
```

```bash
python -m pip install sqlalchemy "psycopg[binary]"
```

Set the connection URL outside your source code:

```bash
export DATABASE_URL='postgresql+asyncpg://app_user:change-me@localhost/app_db'
```

Do not commit real credentials. In production, use your deployment platform's
secret manager or environment configuration.

## Complete example

Create `database.py`:

```python
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool


class Database:
    """Own the SQLAlchemy engine and create short-lived sessions."""

    def __init__(self, url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(
            url,
            poolclass=NullPool,
        )
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
        )

    async def check_connection(self) -> None:
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def close(self) -> None:
        await self.engine.dispose()


database = Database(os.environ["DATABASE_URL"])
```

Create `app.py`:

```python
from hypern import Hypern, Inject
from sqlalchemy import text

from database import Database, database


app = Hypern()
app.provide(Database, database)


@app.on_startup
async def open_database() -> None:
    await database.check_connection()


@app.on_shutdown
async def close_database() -> None:
    await database.close()


@app.get("/health/database")
async def database_health(res, db: Database = Inject()):
    async with db.session() as session:
        await session.execute(text("SELECT 1"))
    res.json({"database": "ok"})


if __name__ == "__main__":
    app.start(host="0.0.0.0", port=8000)
```

Run the application:

```bash
python app.py
```

Verify the connection:

```bash
curl http://localhost:8000/health/database
```

Expected response:

```json
{"database": "ok"}
```

## Synchronous SQLAlchemy

Use SQLAlchemy's synchronous engine when your application and database layer
are synchronous. The lifecycle rules are the same: create one engine per
application process, create a session for each unit of work, and dispose the
engine during shutdown.

Install a synchronous driver, then create `database_sync.py`:

```python
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker


class SyncDatabase:
    def __init__(self, url: str) -> None:
        self.engine: Engine = create_engine(
            url,
            pool_pre_ping=True,
            pool_recycle=1800,
        )
        self.session_factory = sessionmaker(
            self.engine,
            expire_on_commit=False,
        )

    def check_connection(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self.session_factory() as session:
            try:
                yield session
            except Exception:
                session.rollback()
                raise

    def close(self) -> None:
        self.engine.dispose()


database = SyncDatabase(os.environ["DATABASE_URL"])
```

Register the database and use it from synchronous handlers:

```python
from hypern import Hypern, Inject
from sqlalchemy import text

from database_sync import SyncDatabase, database


app = Hypern()
app.provide(SyncDatabase, database)


@app.on_startup
def open_database() -> None:
    database.check_connection()


@app.on_shutdown
def close_database() -> None:
    database.close()


@app.get("/health/database")
def database_health(res, db: SyncDatabase = Inject()):
    with db.session() as session:
        session.execute(text("SELECT 1"))
    res.json({"database": "ok"})


if __name__ == "__main__":
    app.start(host="0.0.0.0", port=8000)
```

### Synchronous connection rules

- Use `with engine.connect()` for a direct connection and always close it.
- Use `with sessionmaker() as session` for ORM work and keep the session local
  to one request or unit of work.
- Use `with session.begin()` for writes so successful blocks commit and failed
  blocks roll back.
- Call `engine.dispose()` from `@app.on_shutdown`.
- Do not call synchronous SQLAlchemy APIs from an `async def` handler. They block
  the event loop while waiting for the database. Use the async integration above
  for async handlers, or keep the complete route and database operation
  synchronous according to your deployment's blocking-execution configuration.

The synchronous engine uses SQLAlchemy's normal connection pool. Set
`pool_size` and `max_overflow` when you need explicit capacity limits, and size
the total across all Hypern worker processes:

```python
engine = create_engine(
    os.environ["DATABASE_URL"],
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=1800,
)
```

`pool_pre_ping` checks pooled connections when they are checked out and helps
replace stale connections. It does not retry a statement that fails after a
transaction has already started.

## Using ORM models

Define models with SQLAlchemy's declarative mapping as usual. Keep model and
repository code separate from the Hypern route layer:

```python
from sqlalchemy import select

from models import User


@app.get("/users/:id")
async def get_user(req, res, db: Database = Inject()):
    user_id = int(req.param("id"))
    async with db.session() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

    if user is None:
        res.status(404).json({"error": "User not found"})
        return

    res.json({"id": user.id, "email": user.email})
```

For writes, make the transaction boundary explicit:

```python
async with db.session() as session:
    async with session.begin():
        session.add(User(email="user@example.com"))
```

`session.begin()` commits when the block succeeds and rolls back when the block
raises. Do not keep a session in a module global or attach one to a singleton
service.

## Connection and session management

### Engine lifetime

Create one engine per application process. Register the database object before
calling `app.start()` or `app.listen()`. Hypern freezes application
registration when startup begins, so calling `app.provide()` or registering
lifecycle handlers afterwards raises a registration error.

Always dispose the engine in `@app.on_shutdown`:

```python
@app.on_shutdown
async def close_database() -> None:
    await database.close()
```

`dispose()` closes idle resources owned by the engine. It does not replace the
need to close sessions with an `async with` block.

### Session lifetime

Create a new `AsyncSession` for each request or unit of work:

```python
async with db.session() as session:
    result = await session.execute(statement)
```

An `AsyncSession` is mutable transaction state. It is not safe to share one
session between concurrent asyncio tasks. A singleton database object is safe;
a singleton session is not.

For synchronous SQLAlchemy, apply the same rule with `Session`: the engine and
session factory can be application singletons, but an open `Session` must stay
inside one request or unit of work.

### Why the example uses `NullPool`

Hypern applications can cross event-loop boundaries during startup, serving,
reload, or multi-worker operation. SQLAlchemy's default async pool must not be
shared by an `AsyncEngine` across different event loops. `NullPool` disables
engine-level connection reuse, which makes the engine safe to pass between
loops at the cost of opening a database connection for each checkout.

If your deployment guarantees one event loop per engine and you need pooled
connections, use SQLAlchemy's default async pool instead:

```python
from sqlalchemy.ext.asyncio import create_async_engine

engine = create_async_engine(
    os.environ["DATABASE_URL"],
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=1800,
)
```

Tune `pool_size` and `max_overflow` against the database server's connection
limit and the number of Hypern worker processes. `pool_pre_ping=True` checks a
pooled connection when it is checked out and helps replace stale idle
connections. It does not retry a statement that fails in the middle of a
transaction. `NullPool` does not retain idle connections, so `pool_pre_ping` is
not part of the cross-event-loop example.

## Dependency injection options

The recommended integration injects the `Database` singleton and lets it own
session creation:

```python
app.provide(Database, database)


@app.get("/users")
async def list_users(res, db: Database = Inject()):
    async with db.session() as session:
        ...
```

You can also register a session factory under an explicit key:

```python
app.provide("session_factory", database.session_factory)


@app.get("/users")
async def list_users(
    res,
    session_factory=Inject("session_factory"),
):
    async with session_factory() as session:
        ...
```

Do not inject an already-open `AsyncSession` as a singleton. A `request`-scoped
provider can construct one session per Hypern request, but application code
still needs an explicit close/rollback policy. The context-manager pattern is
preferred because cleanup stays next to the operation that owns the session.

## Error handling

Use the session context manager to roll back failed work, and translate known
database errors at the service boundary:

```python
from sqlalchemy.exc import IntegrityError


async def create_user(db: Database, email: str):
    try:
        async with db.session() as session:
            async with session.begin():
                user = User(email=email)
                session.add(user)
                await session.flush()
                return user
    except IntegrityError as error:
        raise ValueError("A user with this email already exists") from error
```

Do not retry an arbitrary write after a connection failure without an
idempotency strategy. Retrying can duplicate a successful transaction whose
response was lost.

## API reference

### `Hypern.provide(key, provider, *, scope="singleton")`

Registers a value, class, or factory for `Inject()`-based handler binding.

- `key`: a type, string, or other hashable provider key.
- `provider`: an existing value, class, or sync/async factory.
- `scope`: `singleton` (default), `request`, or `transient`.
- Registration must happen before `app.start()` or `app.listen()` freezes the
  application.

For SQLAlchemy, register the `Database` instance as a singleton. Create sessions
inside request handlers or service methods.

### `Hypern.on_startup`

Decorator for a synchronous or asynchronous startup handler. Use it for a
connectivity check, schema verification, or other application startup work.

### `Hypern.on_shutdown`

Decorator for a synchronous or asynchronous shutdown handler. Use it to call
`await engine.dispose()` through your database owner.

## Troubleshooting

### `Task ... got Future attached to a different loop`

The same pooled `AsyncEngine` was used by more than one event loop. Use the
`NullPool` configuration shown above, or create and dispose a separate engine
for each loop/process.

### Connections are exhausted

Check for sessions or connections that are missing an `async with` block. Then
review the total pool capacity across every Hypern worker process and lower
`pool_size` or `max_overflow` if necessary.

### A stale connection fails during checkout

Enable `pool_pre_ping=True` and set `pool_recycle` below the database or network
idle timeout. A transaction that has already started still needs application
level rollback and, when safe, a deliberate retry.

### Startup cannot reach the database

Confirm `DATABASE_URL`, the driver package, DNS/network access, credentials, and
database readiness. The startup check is intentionally allowed to fail fast so
the service does not accept traffic while its database dependency is unavailable.

## Related documentation

- [Dependency Injection](dependency-injection.md)
- [Best Practices](best-practices.md)
- [SQLAlchemy asyncio documentation](https://docs.sqlalchemy.org/en/21/orm/extensions/asyncio.html)
- [SQLAlchemy connection pooling](https://docs.sqlalchemy.org/en/21/core/pooling.html)
