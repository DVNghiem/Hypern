# Performance Tuning

Hypern pairs a Rust runtime (Tokio + Axum) with a Python handler layer. Every
request crosses the PyO3 boundary, so the framework exposes a handful of
knobs that trade memory, CPU, and latency. Pick the smallest set that meets
your latency and throughput goals, then measure before adding more.

## Worker Model at a Glance

```text
            ┌──────────────┐
            │  Axum/Tokio  │  ← Rust runtime, N IO event loops
            └──────┬───────┘
                   │ PyO3 bridge (GIL acquired per request)
            ┌──────┴───────┐
            │ Python route │  ← your handler
            └──────┬───────┘
                   │ blocking call?
            ┌──────┴───────────────┐
            │ BlockingExecutor pool│  ← Rust threads, GIL released
            └──────────────────────┘
```

`Hypern.start()` takes three knobs:

| Knob | Meaning | Default | When to raise it |
| --- | --- | --- | --- |
| `num_processes` | OS processes | `1` | CPU-bound or noisy-neighbour isolation |
| `workers_threads` | Tokio worker threads per process | `1` | Many concurrent slow requests |
| `max_blocking_threads` | Pool size for synchronous IO inside Rust | `512` | High number of sync DB drivers |
| `max_connections` | Soft cap on concurrent connections | unbounded | Protect the box from runaway clients |

```python
from hypern import Hypern

app = Hypern()
app.start(
    host="0.0.0.0",
    port=8000,
    num_processes=4,           # 4 OS processes
    workers_threads=2,         # 2 Tokio worker threads each (8 total)
    max_blocking_threads=512,
    max_connections=10_000,
)
```

Rule of thumb: start at `num_processes = CPU cores`, `workers_threads = 1`.
Double `workers_threads` only after you see Tokio backpressure in metrics,
never preemptively.

## Choosing `num_processes` vs `workers_threads`

- **More processes** — better for CPU-bound Python code (NumPy, image work),
  isolates memory leaks across requests, and gives you a coarse crash boundary.
- **More threads** — better for many concurrent slow IO calls (database,
  external HTTP). Cheaper than processes; they share the GIL, so only one
  Python instruction runs at a time.

Avoid combining high values of both unless you have measured the bottleneck.

## Offload Sync Work to `BlockingExecutor`

Any blocking call inside an `async def` handler stalls the Tokio worker thread.
Wrap CPU-bound or sync-IO work in `blocking_run`, `blocking_map`, or
`@blocking` to release the GIL and run on a dedicated Rust thread pool.

```python
from hypern import blocking_run, blocking_map, blocking

def heavy_transform(x: int) -> int:
    # Pure-Python CPU work that does not need the event loop
    return sum(i * i for i in range(10_000))

@app.get("/hash")
async def hash_many(req, res, ctx):
    items = list(range(500))
    # Releases the GIL while the workers churn through items
    results = blocking_map(heavy_transform, items, chunk_size=64)
    res.json({"count": len(results)})

@app.post("/report")
async def report(req, res, ctx):
    payload = req.json()
    pdf_bytes = blocking_run(render_pdf, payload["template"], payload["data"])
    res.header("Content-Type", "application/pdf").body(pdf_bytes)

@blocking
def render_pdf(template: str, data: dict) -> bytes:
    # CPU-heavy rendering — runs on a Rust thread
    ...
```

The default executor is lazily created. Tune its size once via the
environment, or pass your own:

```python
import os
os.environ["HYPERN_BLOCKING_THREADS"] = "32"
```

```python
from hypern.blocking import BlockingExecutor, set_default_executor

pool = BlockingExecutor(max_threads=32, queue_size=4096)
set_default_executor(pool)
```

### When Not to Use `BlockingExecutor`

- Inside an `async def` handler that is already doing async work — wrap the
  sync slice only, not the whole body.
- For HTTP calls — use a real async client (`httpx.AsyncClient`) instead.
- For trivial work — crossing the PyO3 boundary has its own cost. Profile
  first if a `blocking_run` for a 50-microsecond operation makes things worse.

## Hot Path: Keep Handlers Short

Every handler call pays:

1. Tokio → PyO3 bridge (acquire GIL).
2. Function-call dispatch into Python.
3. Route-argument binding.
4. PyO3 → Tokio bridge (release GIL, write response).

Reduce per-request cost by:

- Avoiding `inspect`, `getattr`, or `hasattr` chains in the hot path.
- Returning small JSON envelopes (`orjson` is already wired).
- Reusing module-level objects rather than rebuilding them per request.
- Using `ctx.request_id` (set once by `RequestIdMiddleware`) instead of
  generating a new one in Python.

## Async vs Sync Handlers

```python
@app.get("/sync")
def sync_handler(req, res, ctx):           # sync def is fine
    res.json({"ok": True})

@app.get("/async")
async def async_handler(req, res, ctx):   # needed only for awaitable IO
    data = await fetch_remote()
    res.json(data)
```

Pick `async def` only when you actually call `await`. If you do all sync work
inside an `async def`, the handler still blocks the Tokio thread.

## Static File Serving

`StaticFileHandler` (Rust) bypasses Python entirely for assets. Use it for
CSS/JS/images rather than a Python route that opens and reads the file:

```python
from hypern import StaticFileHandler

app = StaticFileHandler(directory="./public", prefix="/static")
```

For large files, combine with `StreamingResponse` to avoid buffering the
whole payload in memory.

## Metrics-Driven Tuning

`MetricsRegistry` exposes counters, gauges, and histograms for requests,
latency, and background tasks. Watch these before changing knobs:

```python
from hypern import MetricsRegistry

metrics = MetricsRegistry()
metrics.counter_inc("requests_total", labels={"method": "GET", "status": "200"})
metrics.histogram_observe("request_duration_ms", elapsed_ms())

# Render Prometheus exposition format
exposition = metrics.render()
```

Track:

- `request_duration_ms` — p95/p99 latency per route.
- `in_flight_requests` — gauge; rising values signal thread starvation.
- Background-task queue depth — `pending_count()` on `TaskExecutor`.

## Database Pool Sizing

For an async SQLAlchemy integration with `NullPool` (see `sqlalchemy.md`),
each checkout opens a connection. For pooled engines, set
`pool_size * num_processes` below the database server's connection limit:

```python
engine = create_async_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
)
# Total connections = num_processes * (pool_size + max_overflow)
```

For sync SQLAlchemy, every request still needs one pooled connection from
the synchronous pool — same rule applies across worker processes.

## Background Tasks vs BlockingExecutor

| Concern | `@background` | `@blocking` |
| --- | --- | --- |
| Lifecycle | Fire-and-forget, task ID returned | Inline return value |
| Failures | Recorded in `TaskResult` | Propagated as Python exception |
| Scheduling | Delayed execution, retries via scheduler | None |
| Concurrency | Bounded by `TaskExecutor.num_workers` | Bounded by `BlockingExecutor.max_threads` |

Use `@background` for fire-and-forget work (emails, exports). Use
`@blocking` to offload a synchronous slice of an async handler.

## Zero-Downtime Reload Cost

`setup_reload` keeps the new worker process warm before sending `SIGUSR1`
to the old one. The warm-up time is your grace period — long enough to
finish in-flight requests, short enough to roll back fast. See
`zero-downtime.md` for signals and `HealthCheck` integration.

## Benchmarking

Reproducible benchmarks beat anecdotal numbers. Use `pytest-benchmark` or
`wrk` against a frozen handler. Capture:

- Steady-state latency at 10/100/1000 RPS.
- p99 latency under saturation (raise load until p99 doubles).
- Memory RSS per process after 10 minutes of traffic.
- GIL contention — `vmstat 1` and watch `%st` and `%sy`.

Re-run after every change to `num_processes`, `workers_threads`, or the
database pool.