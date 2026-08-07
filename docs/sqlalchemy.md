# SQLAlchemy Integration

SQLAlchemy is the recommended ORM for production Hypern applications. This guide covers wiring SQLAlchemy's `Session` and `AsyncSession` into Hypern's request lifecycle.

## Why SQLAlchemy over raw sqlx

| | Hypern `db()` | SQLAlchemy ORM |
|---|---|---|
| Query style | Raw SQL strings | Python model objects |
| Schema migration | Manual SQL | Alembic auto-migrate |
| Relationships | JOIN by hand | `relationship()` / `selectinload` |
| Type safety | `$1` placeholders | ORM column expressions |
| Best for | Simple CRUD, analytics | Complex domain models |

Use `db()` when queries are simple or performance-critical. Use SQLAlchemy when your domain has rich models, migrations, and relationship traversal.

---

## Sync Session (SQLAlchemy 1.4 / 2.0 style)

### Install

```bash
pip install sqlalchemy alembic
```

### Setup

```python
# app/db.py
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from hypern.database import Database

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, server_default="now()")


engine = None
SessionLocal = None


def init_db():
    global engine, SessionLocal
    Database.configure(url="postgresql://user:pass@localhost:5432/mydb")
    engine = create_engine(
        Database._databases["default"]["url"],
        pool_size=16,
        pool_pre_ping=True,
    )
    SessionLocal = sessionmaker(bind=engine)


def get_session() -> Session:
    """Create a new Session. Caller is responsible for closing."""
    return Session(bind=engine)
```

> **Note:** `create_engine` uses Hypern's connection URL directly. Because Hypern manages its own pool, set `pool_size` on `create_engine` to match or slightly exceed Hypern's pool size to avoid over-provisioning.

### Per-Request Session Middleware

Inject a session into every request context and finalize it on the way out. Middleware must call `await next_fn()` to continue the chain — cleanup runs after it returns. Use `contextvars.ContextVar` for per-request session isolation:

```python
# app/middleware.py
from contextvars import ContextVar
from hypern._hypern import Request, Response
from app.db import get_session

# Per-request session stored in context var — safe under concurrent requests
_session_var: ContextVar[object] = ContextVar("session", default=None)


class SQLAlchemyMiddleware:
    """Attaches an SQLAlchemy Session to each request and closes it on exit."""

    async def __call__(self, req: Request, res: Response, ctx, next_fn):
        """Async middleware — session lifecycle is tied to the request."""
        session = get_session()
        token = _session_var.set(session)
        try:
            await next_fn()       # run handler + downstream middleware
            session.commit()      # commit only if no exception propagated
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()        # always close, even on success
            _session_var.reset(token)


def current_session():
    """Get the SQLAlchemy Session for the current request."""
    return _session_var.get()


# Register globally — applies to all routes
app.use(SQLAlchemyMiddleware())
```

> **Why not `yield`?** Hypern calls `await mw(req, res, ctx, next_fn)`. The `yield` pattern (generator-based middleware) is not supported — Hypern awaits the middleware's return value or relies on `await next_fn()` in an async function. `yield` in a sync function returns a generator object that is never iterated, so cleanup code after `yield` never runs. Sessions leak and transactions never commit.

### Usage in Handlers

```python
from app.db import User
from app.middleware import current_session


@app.get("/users")
def list_users(req, res, ctx):
    session = current_session()
    users = session.query(User).filter_by(active=True).all()
    res.json([{"id": u.id, "name": u.name, "email": u.email} for u in users])


@app.get("/users/:id")
def get_user(req, res, ctx):
    session = current_session()
    user = session.get(User, req.param("id"))
    if user is None:
        res.status(404).json({"error": "not found"})
        return
    res.json({"id": user.id, "name": user.name, "email": user.email})


@app.post("/users")
def create_user(req, res, ctx):
    session = current_session()
    data = req.json()
    user = User(name=data["name"], email=data["email"])
    session.add(user)
    session.flush()  # get user.id before commit
    res.status(201).json({"id": user.id, "name": user.name})
```

---

## Async Session (SQLAlchemy 2.0 + asyncio)

### Install

```bash
pip install sqlalchemy[asyncio] asyncpg  # asyncpg for PostgreSQL
```

### Setup

```python
# app/db_async.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession, async_object_session
from sqlalchemy.orm import declarative_base
from hypern.database import Database

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True)


_engine = None
AsyncSessionLocal = None


def init_async_db():
    global _engine, AsyncSessionLocal
    url = Database._databases["default"]["url"]
    # Convert postgresql:// to postgresql+asyncpg://
    async_url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    _engine = create_async_engine(async_url, pool_size=16, pool_pre_ping=True)
    AsyncSessionLocal = async_sessionmaker(bind=_engine, class_=AsyncSession, expire_on_commit=False)
```

### Async Middleware

```python
from contextvars import ContextVar
from hypern._hypern import Request, Response
from app.db_async import AsyncSessionLocal, AsyncSession

# Per-request session stored in context var
_async_session_var: ContextVar[AsyncSession] = ContextVar(
    "async_session", default=None
)


class AsyncSQLAlchemyMiddleware:
    """Async-compatible middleware — runs a session per request."""

    async def __call__(self, req: Request, res: Response, ctx, next_fn):
        """Async middleware — await next_fn(), then commit/rollback/close."""
        session = AsyncSessionLocal()
        token = _async_session_var.set(session)
        try:
            await next_fn()
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
            _async_session_var.reset(token)


async def get_async_session() -> AsyncSession:
    """Get the AsyncSession for the current request."""
    return _async_session_var.get()
```

---

## Migrations with Alembic

Alembic is the standard migration tool for SQLAlchemy.

```bash
pip install alembic
alembic init migrations
```

### `alembic.ini`

```ini
sqlalchemy.url = postgresql://user:pass@localhost:5432/mydb
```

### `migrations/env.py`

```python
from app.db import Base, engine  # your models + sync engine

target_metadata = Base.metadata

# For async:
# from app.db_async import Base, _engine
# async def run_migrations():
#     async with _engine.begin() as conn:
#         await conn.run_sync(target_metadata.reflect)
```

### Workflow

```bash
# Generate a migration after model changes
alembic revision --autogenerate -m "add users table"

# Apply migrations
alembic upgrade head

# Roll back one step
alembic downgrade -1
```

---

## Mixing `db()` and SQLAlchemy

Both can coexist. Use `db()` for raw queries and SQLAlchemy for ORM operations:

```python
from hypern.database import db
from app.db import User
from app.middleware import current_session


@app.get("/reports/summary")
def summary(req, res, ctx):
    # Raw query for aggregation
    raw_session = db(ctx)
    revenue = raw_session.query_one(
        "SELECT SUM(amount) as total FROM orders WHERE created_at > NOW() - INTERVAL '30 days'",
        [],
    )

    # ORM for entity access
    orm_session = current_session()
    user_count = orm_session.query(User).count()

    res.json({
        "revenue": float(revenue["total"] or 0),
        "user_count": user_count,
    })
```

---

## Common Patterns

### Eager Loading Relationships

Avoid N+1 queries with `selectinload` or `joinedload`:

```python
from sqlalchemy.orm import selectinload


@app.get("/posts/:id")
def get_post(req, res, ctx):
    session = current_session()
    post = session.query(Post).options(
        selectinload(Post.author),
        selectinload(Post.comments),
    ).get(req.param("id"))
    # session.close() handled by middleware
    res.json({
        "id": post.id,
        "title": post.title,
        "author": {"id": post.author.id, "name": post.author.name},
        "comments": [{"id": c.id, "text": c.text} for c in post.comments],
    })
```

### Bulk Operations

```python
@app.post("/users/bulk")
def bulk_create(req, res, ctx):
    session = current_session()
    data = req.json()

    users = [User(name=d["name"], email=d["email"]) for d in data["users"]]
    session.bulk_save_objects(users)  # fast, bypasses ORM events
    session.flush()  # get generated IDs

    res.status(201).json({"created": len(users)})
```

### Raw SQL with Result Mapping

Use `db()` for complex raw queries and map results to ORM objects:

```python
@app.get("/users/search")
def search_users(req, res, ctx):
    session = db(ctx)
    query = req.query("q") or ""

    # Raw SQL for full-text search
    rows = session.query(
        "SELECT id, name FROM users WHERE name ILIKE $1 LIMIT 20",
        [f"%{query}%"],
    )
    if not rows:
        res.json([])
        return

    # Fetch ORM objects by IDs
    orm_session = current_session()
    ids = [r["id"] for r in rows]
    users = orm_session.query(User).filter(User.id.in_(ids)).all()

    res.json([{"id": u.id, "name": u.name} for u in users])
```

---

## Complete Example

```python
# main.py
from hypern import Hypern
from hypern.database import Database
from app.db import init_db, User
from app.middleware import SQLAlchemyMiddleware

app = Hypern()
app.use(SQLAlchemyMiddleware())


@app.on_startup
async def startup():
    Database.configure(url="postgresql://user:pass@localhost:5432/mydb")
    init_db()


@app.get("/users")
def list_users(req, res, ctx):
    from app.middleware import current_session
    session = current_session()
    users = session.query(User).order_by(User.name).all()
    res.json([{"id": u.id, "name": u.name, "email": u.email} for u in users])


@app.post("/users")
def create_user(req, res, ctx):
    from app.middleware import current_session
    session = current_session()
    data = req.json()
    user = User(name=data["name"], email=data["email"])
    session.add(user)
    res.status(201).json({"id": user.id})


if __name__ == "__main__":
    app.start(port=8000)
```

---

## Performance Notes

- **Pool size**: Set `pool_size` on `create_engine` to match Hypern's `max_size`. Each Hypern worker gets its own process pool; each process pool has its own SQLAlchemy engine.
- **Pool pre-ping**: Enable `pool_pre_ping=True` to test connections before use — avoids errors after DB restarts.
- **Expiry on commit**: Disable `expire_on_commit=False` on `sessionmaker` if you access ORM objects after the session closes (default is to expire them, which requires a refresh query).
- **Async over sync for high concurrency**: If your app handles many concurrent requests, prefer `AsyncSession` with `asyncpg` — it releases the GIL during I/O waits.
