# Database Module

The Hypern framework provides a powerful, request-scoped database layer for PostgreSQL with connection pooling, automatic transaction management, multi-database support with aliases, and seamless Python-Rust interop.

## Features

- **Connection Pooling**: Efficient connection reuse with configurable pool sizes
- **Multi-Database Support**: Configure and access multiple databases with aliases
- **Request-Scoped Sessions**: Each HTTP request gets exactly one database connection per alias
- **Automatic Transaction Management**: Auto-commit/rollback at request end
- **Type-Safe Parameter Binding**: Secure parameterized queries with automatic type conversion
- **Full PostgreSQL Type Support**: Integers, floats, decimals, strings, JSON, dates, times, timestamps, booleans, and binary data

## Quick Start

### Configuration

Initialize database pools at application startup. You can configure multiple databases with different aliases:

```python
from hypern import Hypern
from hypern.database import Database, db, finalize_db

app = Hypern()

@app.on_startup
async def startup():
    # Primary database (default alias)
    Database.configure(
        url="postgresql://user:password@localhost:5432/mydb",
        max_size=16,          # Maximum connections in pool
        min_idle=2,           # Minimum idle connections
        connect_timeout_secs=30,
        alias="default"       # Optional: defaults to "default"
    )
    
    # Analytics database
    Database.configure(
        url="postgresql://user:password@localhost:5432/analytics",
        max_size=5,
        alias="analytics"
    )
    
    # Logging database
    Database.configure(
        url="postgresql://user:password@localhost:5432/logs",
        max_size=3,
        alias="logging"
    )
```

### Basic Usage

Use the `db()` function in request handlers to get a database session. Specify an alias to access different databases:

```python
@app.get("/users")
def get_users(req, res, ctx):
    # Default database
    session = db(ctx)  # or db(ctx, alias="default")
    users = session.query("SELECT id, name, email FROM users")
    
    # Analytics database
    analytics_session = db(ctx, alias="analytics")
    stats = analytics_session.query("SELECT COUNT(*) as total FROM user_visits")
    
    res.json({"users": users, "stats": stats})

@app.get("/users/:id")
def get_user(req, res, ctx):
    session = db(ctx)
    user_id = req.params["id"]
    
    # query_one returns single row or raises RuntimeError
    user = session.query_one(
        "SELECT * FROM users WHERE id = $1",
        [user_id]
    )
    
    # Log the access to logging database
    log_session = db(ctx, alias="logging")
    log_session.execute(
        "INSERT INTO access_logs (user_id, action, timestamp) VALUES ($1, $2, $3)",
        [user_id, "view_user", "NOW()"]
    )
    
    res.json(user)

@app.post("/users")
def create_user(req, res, ctx):
    session = db(ctx)
    data = req.json()
    
    # execute returns number of affected rows
    affected = session.execute(
        "INSERT INTO users (name, email) VALUES ($1, $2)",
        [data["name"], data["email"]]
    )
    res.status(201).json({"created": affected})
```

## API Reference

### Database Class

Static configuration class for the database pool.

#### `Database.configure(url, max_size=16, min_idle=None, connect_timeout_secs=30, idle_timeout_secs=None, max_lifetime_secs=None, test_before_acquire=False, keepalive_secs=None, alias="default")`

Initialize a connection pool with an alias.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | `str` | required | PostgreSQL connection URL |
| `max_size` | `int` | 16 | Maximum connections in pool |
| `min_idle` | `int` | None | Minimum idle connections |
| `connect_timeout_secs` | `int` | 30 | Connection timeout in seconds |
| `idle_timeout_secs` | `int` | None | Idle connection timeout |
| `max_lifetime_secs` | `int` | None | Maximum connection lifetime |
| `test_before_acquire` | `bool` | False | Re-ping/verify connections before acquiring |
| `keepalive_secs` | `int` | None | TCP keepalive interval in seconds |
| `alias` | `str` | "default" | Database alias for identification |

```python
# Configure multiple databases
Database.configure(
    url="postgresql://user:pass@localhost:5432/main",
    max_size=20,
    min_idle=5,
    connect_timeout_secs=10,
    test_before_acquire=True,  # Verify connections before use
    alias="default"
)

Database.configure(
    url="postgresql://user:pass@localhost:5432/analytics",
    max_size=5,
    alias="analytics",
    keepalive_secs=60,         # Send TCP keepalive every 60 seconds
)
```

#### `Database.is_configured(alias="default")`

Returns `True` if the database pool with the specified alias is configured and ready.

#### `Database.status(alias="default")`

Returns pool status for the specified alias with `size`, `available`, and `max_size` properties.

```python
# Check default database status
status = Database.status()
print(f"Default pool: {status.available}/{status.size} available")

# Check analytics database status
analytics_status = Database.status(alias="analytics")
print(f"Analytics pool: {analytics_status.available}/{analytics_status.size} available")
```

#### `Database.close(alias=None)`

Close connections and reset the pool(s).

- If `alias` is specified, closes only that database pool
- If `alias` is `None`, closes all database pools

```python
# Close specific database
Database.close(alias="analytics")

# Close all databases
Database.close()
```

### DbSession Class

Request-scoped database session.

#### Query Methods

##### `session.query(sql, params=None)`

Execute a SELECT query and return all rows as a list of dictionaries.

```python
users = session.query(
    "SELECT * FROM users WHERE active = $1",
    [True]
)
for user in users:
    print(user["name"], user["email"])
```

##### `session.query_one(sql, params=None)`

Execute a SELECT query and return exactly one row. Raises `RuntimeError` if no rows found.

```python
user = session.query_one(
    "SELECT * FROM users WHERE id = $1",
    [user_id]
)
```

##### `session.execute(sql, params=None)`

Execute an INSERT, UPDATE, or DELETE query. Returns the number of affected rows.

```python
affected = session.execute(
    "UPDATE users SET status = $1 WHERE id = $2",
    ["active", user_id]
)
print(f"Updated {affected} rows")
```

##### `session.execute_many(sql, params_list)`

Execute a batch of statements efficiently.

```python
affected = session.execute_many(
    "INSERT INTO users (name, email) VALUES ($1, $2)",
    [
        ["Alice", "alice@example.com"],
        ["Bob", "bob@example.com"],
        ["Charlie", "charlie@example.com"],
    ]
)
print(f"Inserted {affected} users")
```

#### Transaction Management

##### `session.begin()`

Start a database transaction. Raises error if transaction already active.

```python
session.begin()
try:
    session.execute("INSERT INTO accounts (name) VALUES ($1)", ["Savings"])
    session.execute("INSERT INTO transactions (amount) VALUES ($1)", [1000])
    session.commit()
except Exception as e:
    session.rollback()
    raise
```

##### `session.commit()`

Commit the current transaction.

##### `session.rollback()`

Rollback the current transaction.

##### `session.transaction()` (Context Manager)

Use transactions with automatic commit/rollback:

```python
with session.transaction():
    session.execute("INSERT INTO orders (total) VALUES ($1)", [99.99])
    session.execute("UPDATE inventory SET stock = stock - 1")
    # Auto-commits if no exception
# Auto-rolls back on exception
```

#### Session State

##### `session.request_id`

Get the request ID associated with this session.

##### `session.state`

Get the current session state: `"idle"`, `"connected"`, `"in_transaction"`, `"committed"`, `"rolled_back"`, or `"closed"`.

##### `session.is_in_transaction`

Returns `True` if a transaction is currently active.

##### `session.set_auto_commit(enabled)`

Enable or disable auto-commit on session finalization (default: enabled).

### Helper Functions

#### `db(ctx_or_request_id, alias="default")`

Get a database session for the current request from the specified database alias.

```python
@app.get("/data")
def get_data(req, res, ctx):
    # Default database
    session = db(ctx)  # Pass context object
    # or 
    session = db(ctx, alias="default")  # Explicit alias
    
    # Analytics database
    analytics = db(ctx, alias="analytics")
    
    # Using string request ID
    session = db("custom-request-id", alias="default")
```

#### `finalize_db(ctx_or_request_id, alias=None)`

Finalize database session(s), committing or rolling back any pending transaction. Usually called automatically at request end.

- If `alias` is specified, finalizes only that database session
- If `alias` is `None` (default), finalizes all database sessions for the request

```python
# Finalize specific database session
finalize_db(ctx, alias="analytics")

# Finalize all database sessions for this request  
finalize_db(ctx)
```

## Multi-Database Usage Patterns

### Cross-Database Operations

```python
@app.post("/analytics")  
def record_analytics(req, res, ctx):
    # Main database transaction
    main_db = db(ctx, alias="default")
    main_db.begin()
    
    user_id = main_db.execute(
        "INSERT INTO users (name) VALUES ($1) RETURNING id",
        ["Alice"]
    )
    
    # Analytics database (separate transaction)
    analytics_db = db(ctx, alias="analytics")
    analytics_db.execute(
        "INSERT INTO user_events (user_id, event) VALUES ($1, $2)",
        [user_id, "user_created"]  
    )
    
    # Both will auto-commit at request end
    res.json({"success": True})
```

### Database-Specific Error Handling

```python
@app.get("/robust-data")
def get_robust_data(req, res, ctx):
    # Primary data from main database
    main_db = db(ctx)
    users = main_db.query("SELECT * FROM users")
    
    # Optional analytics data (graceful degradation)
    try:
        analytics_db = db(ctx, alias="analytics") 
        stats = analytics_db.query("SELECT COUNT(*) as total FROM events")
    except Exception as e:
        print(f"Analytics unavailable: {e}")
        stats = [{"total": 0}]  # Fallback
    
    res.json({"users": users, "stats": stats})
```

## Automatic Session Management

Hypern automatically manages database sessions at the request level, similar to Flask-SQLAlchemy's session scope:

### Auto-Finalization

Database sessions are **automatically finalized** when request handlers complete:

```python
@app.get("/users")
def get_users(req, res, ctx):
    session = db(ctx)
    users = session.query("SELECT * FROM users")
    res.json(users)
    # No need to call finalize_db() - it's automatic!
```

### Error Handling

If an exception occurs during request handling:
1. The session is marked as having an error
2. Any active transaction is automatically rolled back
3. The connection is returned to the pool

```python
@app.post("/transfer")
def transfer_money(req, res, ctx):
    session = db(ctx)
    session.begin()
    session.execute("UPDATE accounts SET balance = balance - 100 WHERE id = 1")
    
    raise ValueError("Oops!")  # Transaction will be rolled back automatically
```

### Transaction Behavior

| Scenario | Behavior |
|----------|----------|
| Handler completes successfully | Auto-commit if transaction active |
| Handler raises exception | Auto-rollback |
| `auto_commit=False` set | Rollback (explicit commit required) |

## Multiprocess Considerations

Hypern uses fork-based multiprocessing for worker processes. The database module handles this correctly:

### Lazy Initialization

Database connections are initialized **lazily** (on first use) in each worker process:

```python
# In main.py
from hypern.database import Database

# Configure stores settings but doesn't connect yet
Database.configure(url="postgresql://...")  # Safe before fork

app = Hypern()

@app.get("/data")
def get_data(req, res, ctx):
    session = db(ctx)  # Connection pool created here (in worker process)
    ...

if __name__ == "__main__":
    app.start(port=8000)  # Workers fork here
```

This ensures each worker process has its own connection pool and tokio runtime.

### Best Practices for Multiprocess

1. **Call `Database.configure()` before `app.start()`** - Configuration is stored and initialization is deferred.

2. **Don't share database sessions across processes** - Each request gets a fresh session in the handling worker.

3. **Set appropriate pool sizes** - Each worker process has its own pool:
   ```python
   # With 4 workers and max_size=20, total connections = 80
   Database.configure(url="...", max_size=20)
   app.start(workers=4)
   ```

## Parameter Binding

Use `$1`, `$2`, etc. for parameter placeholders. This prevents SQL injection and handles type conversion automatically.

### Supported Types

| Python Type | PostgreSQL Type |
|-------------|-----------------|
| `None` | NULL |
| `bool` | BOOLEAN |
| `int` | INT2/INT4/INT8 (auto-sized) |
| `float` | FLOAT4/FLOAT8/NUMERIC |
| `str` | TEXT/VARCHAR |
| `bytes` | BYTEA |
| `datetime.date` | DATE |
| `datetime.time` | TIME |
| `datetime.datetime` | TIMESTAMP |
| `dict` | JSONB |
| `list` | JSONB |

### Examples

```python
# Integers - automatically sized to column type
session.execute("INSERT INTO t (smallint_col, int_col, bigint_col) VALUES ($1, $2, $3)", 
                [100, 50000, 9999999999])

# Decimals/Floats - use Python floats for NUMERIC columns
session.execute("INSERT INTO products (price) VALUES ($1)", [99.99])

# JSON - pass dict or list directly
session.execute("INSERT INTO users (metadata) VALUES ($1)", 
                [{"role": "admin", "permissions": ["read", "write"]}])

# Dates and times
from datetime import date, time, datetime
session.execute("INSERT INTO events (date, time, timestamp) VALUES ($1, $2, $3)",
                [date.today(), time(14, 30), datetime.now()])

# Binary data
session.execute("INSERT INTO files (data) VALUES ($1)", [b"binary content"])
```

## Best Practices

### 1. Use Context Manager for Transactions

```python
with session.transaction():
    session.execute("UPDATE accounts SET balance = balance - $1 WHERE id = $2", [100, from_id])
    session.execute("UPDATE accounts SET balance = balance + $1 WHERE id = $2", [100, to_id])
```

### 2. Always Finalize Sessions

Sessions are automatically finalized at request end, but for non-request contexts:

```python
session = db("batch-job-123")
try:
    session.execute("INSERT INTO logs (message) VALUES ($1)", ["Job started"])
finally:
    finalize_db("batch-job-123")
```

### 3. Use Parameterized Queries

Never concatenate user input into SQL:

```python
# ❌ WRONG - SQL injection risk
session.query(f"SELECT * FROM users WHERE name = '{user_input}'")

# ✅ CORRECT - Safe parameterized query
session.query("SELECT * FROM users WHERE name = $1", [user_input])
```

### 4. Pool Sizing

Configure pool size based on your workload:

```python
# For CPU-bound apps: max_size ≈ 2 * CPU cores
# For I/O-bound apps: max_size ≈ 10 * CPU cores
Database.configure(
    url="postgresql://...",
    max_size=32,
    min_idle=4  # Keep some connections warm
)
```

## Error Handling

Database errors include detailed PostgreSQL error information:

```python
try:
    session.execute("INSERT INTO users (email) VALUES ($1)", ["duplicate@email.com"])
except RuntimeError as e:
    # Error includes SQLSTATE code and details
    # e.g., "PostgreSQL error: duplicate key value violates unique constraint (SQLSTATE 23505)"
    print(f"Database error: {e}")
```

## Low-Level API

For advanced use cases, you can access the underlying Rust types directly:

```python
from hypern._hypern import ConnectionPool, PoolConfig, PoolStatus, DbSession, finalize_db

# Direct pool configuration
config = PoolConfig(
    url="postgresql://...",
    max_size=16,
    min_idle=2,
    connect_timeout_secs=30,
    idle_timeout_secs=600,
    max_lifetime_secs=1800,
)
ConnectionPool.initialize(config)

# Use the high-level db() function from hypern.database
from hypern.database import db

session = db("request-id")
result = session.query("SELECT 1 as num")
finalize_db("request-id")
```

## Complete Example

```python
from hypern import Hypern
from hypern.database import Database, db

app = Hypern()

@app.on_startup
async def startup():
    Database.configure(
        url="postgresql://user:pass@localhost:5432/myapp",
        max_size=20
    )

@app.get("/products")
def list_products(req, res, ctx):
    session = db(ctx)
    products = session.query("""
        SELECT id, name, price, stock
        FROM products
        WHERE active = true
        ORDER BY name
    """)
    res.json(products)

@app.post("/orders")
def create_order(req, res, ctx):
    session = db(ctx)
    data = req.json()
    
    with session.transaction():
        # Create order
        session.execute(
            "INSERT INTO orders (user_id, total) VALUES ($1, $2)",
            [data["user_id"], data["total"]]
        )
        
        # Update inventory
        for item in data["items"]:
            session.execute(
                "UPDATE products SET stock = stock - $1 WHERE id = $2",
                [item["quantity"], item["product_id"]]
            )
    
    res.status(201).json({"success": True})

@app.get("/stats")
def get_stats(req, res, ctx):
    session = db(ctx)
    
    stats = session.query_one("""
        SELECT 
            COUNT(*) as total_orders,
            SUM(total) as revenue,
            AVG(total) as avg_order
        FROM orders
        WHERE created_at > NOW() - INTERVAL '30 days'
    """)
    
    res.json({
        "total_orders": stats["total_orders"],
        "revenue": float(stats["revenue"]) if stats["revenue"] else 0,
        "avg_order": float(stats["avg_order"]) if stats["avg_order"] else 0
    })

if __name__ == "__main__":
    app.run()
```
