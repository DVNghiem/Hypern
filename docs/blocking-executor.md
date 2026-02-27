# Blocking Executor

The **Blocking Executor** provides a high-performance, GIL-releasing thread pool implemented in Rust for running CPU-bound Python code with true parallelism.

## Why use it?

Python's Global Interpreter Lock (GIL) prevents multiple threads from executing Python bytecode simultaneously. This makes `concurrent.futures.ThreadPoolExecutor` ineffective for CPU-bound work — all threads compete for the same GIL.

Hypern's `BlockingExecutor` solves this by:

| Feature | Python ThreadPoolExecutor | Hypern BlockingExecutor |
|---|---|---|
| Thread implementation | Python threads (GIL-bound) | Rust OS threads |
| GIL during wait | Held by caller | **Released** by caller |
| Task dispatch | Python `queue.Queue` (lock-based) | Rust crossbeam channel (lock-free) |
| Thread startup | Created per-task or lazily | **Pre-spawned** for zero latency |
| Memory overhead | Python thread stack (~8MB default) | Rust thread stack (~2MB, configurable) |

The calling Python thread releases the GIL while waiting for results, and worker threads only hold the GIL for the brief moment they execute the Python callable. This means **other Python threads, async tasks, and coroutines can run concurrently**.

## Installation

`BlockingExecutor` is built into Hypern — no extra dependencies needed.

```python
from hypern import BlockingExecutor
# or
from hypern.blocking import BlockingExecutor, blocking_run, blocking_map
```

## Quick Start

### Basic usage

```python
from hypern import BlockingExecutor

# Create an executor with 8 worker threads
executor = BlockingExecutor(max_threads=8)

def heavy_computation(n):
    """Some CPU-intensive work."""
    return sum(i * i for i in range(n))

# Run on a Rust thread — GIL released while waiting
result = executor.run_sync(heavy_computation, 10_000_000)
print(result)

# Clean up
executor.shutdown()
```

### Context manager

```python
with BlockingExecutor(max_threads=4) as executor:
    result = executor.run_sync(process_data, raw_data)
    # Automatically shuts down when exiting the block
```

### Module-level helpers (no manual executor management)

```python
from hypern.blocking import blocking_run, blocking_map

# Single call
result = blocking_run(heavy_computation, 10_000_000)

# Map over a list
items = list(range(1000))
results = blocking_map(lambda x: x ** 2, items)
```

## API Reference

### `BlockingExecutor`

```python
class BlockingExecutor:
    def __init__(self, max_threads: int = 0, queue_size: int = 0) -> None:
        """
        Args:
            max_threads: Number of OS worker threads. 0 = auto-detect CPU count.
            queue_size:  Bounded queue depth. 0 = unbounded.
        """
```

#### `run_sync(callable, *args, **kwargs)`

Execute a single callable on a pool thread. The calling thread releases the GIL while waiting.

```python
result = executor.run_sync(my_function, arg1, arg2, key=value)
```

**Returns:** The return value of `callable(*args, **kwargs)`.

**Raises:** `RuntimeError` if the pool is shut down or the callable raises an exception.

#### `run_parallel(tasks)`

Run multiple callables in parallel. The calling thread releases the GIL and waits for **all** tasks.

```python
results = executor.run_parallel([
    (function_a, (arg1, arg2)),
    (function_b, (arg3,)),
    (function_c, (arg4,), {"key": "value"}),
])
# results[0] = function_a(arg1, arg2)
# results[1] = function_b(arg3)
# results[2] = function_c(arg4, key="value")
```

**Returns:** List of results in the same order as input.

#### `map(callable, items, chunk_size=0)`

Map a function over items in parallel with automatic chunking.

```python
results = executor.map(transform, items, chunk_size=256)
# Equivalent to: [transform(item) for item in items]
# But executed across all pool threads
```

**Args:**
- `callable`: Function taking a single item.
- `items`: List of items to process.
- `chunk_size`: Items per work unit. `0` = auto-tune (recommended).

**Returns:** List of results, same order as `items`.

#### `active_threads()` / `pool_size()` / `pending_tasks()` / `is_running()`

Introspection methods for monitoring pool state.

#### `shutdown(wait=True, timeout_secs=30.0)`

Shut down the executor. If `wait=True`, blocks until pending tasks finish (up to `timeout_secs`).

### Module-level functions

These use a lazily-created default executor (configured via `HYPERN_BLOCKING_THREADS` env var):

```python
from hypern.blocking import blocking_run, blocking_map, blocking_parallel

# Single call
result = blocking_run(fn, *args, **kwargs)

# Parallel map
results = blocking_map(fn, items, chunk_size=128)

# Heterogeneous parallel
results = blocking_parallel([
    (fn_a, (x,)),
    (fn_b, (y,), {"flag": True}),
])
```

### `@blocking` decorator

Automatically offloads a function to a Rust thread whenever it's called:

```python
from hypern.blocking import blocking

@blocking
def process_image(path: str) -> bytes:
    """This runs on a Rust thread every time it's called."""
    with open(path, "rb") as f:
        data = f.read()
    return expensive_transform(data)

# Caller's GIL is released while waiting
result = process_image("/path/to/image.png")
```

With a custom executor:

```python
my_pool = BlockingExecutor(max_threads=16)

@blocking(executor=my_pool)
def heavy_work(data):
    return crunch(data)
```

## Use Cases

### 1. CPU-bound computation in a web handler

```python
from hypern import Hypern, BlockingExecutor
from hypern.blocking import blocking

app = Hypern()
executor = BlockingExecutor(max_threads=8)

@blocking(executor=executor)
def compute_report(data):
    # Heavy number crunching
    return analyze(data)

@app.get("/report")
async def report_handler(request, response):
    data = request.json()
    # GIL released while compute_report runs on Rust thread
    result = compute_report(data)
    return response.json(result)
```

### 2. Parallel data processing

```python
from hypern.blocking import blocking_map

def transform_record(record):
    # CPU-intensive per-record transformation
    return {
        "id": record["id"],
        "score": complex_scoring(record),
        "hash": compute_hash(record["payload"]),
    }

# Process 10,000 records across all CPU cores
records = fetch_records()
results = blocking_map(transform_record, records, chunk_size=500)
```

### 3. Parallel I/O with GIL release

```python
from hypern.blocking import blocking_parallel

def fetch_user(user_id):
    import requests
    return requests.get(f"https://api.example.com/users/{user_id}").json()

# Fetch 3 users in parallel on Rust threads
users = blocking_parallel([
    (fetch_user, (1,)),
    (fetch_user, (2,)),
    (fetch_user, (3,)),
])
```

### 4. Integration with async code

```python
import asyncio
from hypern.blocking import blocking_run

async def async_handler():
    # Run CPU-bound work without blocking the event loop
    # (run_sync releases the GIL, so the event loop continues)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, blocking_run, heavy_fn, data)
    return result
```

## Configuration

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `HYPERN_BLOCKING_THREADS` | `0` (auto = CPU count) | Thread count for the default module-level executor |

### Custom executor setup

```python
from hypern.blocking import set_default_executor, BlockingExecutor

# Set a custom default executor at app startup
set_default_executor(BlockingExecutor(max_threads=16, queue_size=10000))
```

## Performance Tips

1. **Use `chunk_size` wisely with `map()`**: Too small = overhead per chunk; too large = poor load balancing. Start with `0` (auto-tune) and benchmark.

2. **Avoid tiny callables**: Each task has ~1μs dispatch overhead. If your callable runs in <10μs, batch work into larger units.

3. **Mind the data transfer**: Arguments and return values cross the Python↔Rust boundary. For large data, consider passing indices/keys rather than copying large objects.

4. **Pre-create executors**: `BlockingExecutor` pre-spawns threads. Create it once at startup, not per-request.

5. **Bounded queues for backpressure**: Use `queue_size > 0` in production to prevent unbounded memory growth if producers outpace consumers.

## How It Works (Architecture)

```
Python Thread                    Rust Worker Threads
─────────────                    ───────────────────
                                 ┌──────────────────┐
executor.run_sync(fn, args) ──►  │ crossbeam channel│
    │                            │   (lock-free)    │
    │  GIL RELEASED              └────────┬─────────┘
    │  (py.allow_threads)                 │
    │                            Worker picks up task
    │                            Calls Python::attach()
    │                            Acquires GIL briefly
    │                            Runs fn(*args)
    │                            Releases GIL
    │                            Sends result back
    │                                     │
    ◄─────────────────────────────────────┘
    │  GIL RE-ACQUIRED
    │
    returns result
```

Key: The calling thread does **not** hold the GIL while waiting. The worker thread only holds the GIL for the duration of the Python callable execution. This enables true parallelism.
