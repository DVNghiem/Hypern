# Task Scheduling & Monitoring

Hypern extends its background task system with cron-like scheduling, retry policies, and task monitoring.

This builds on top of the core `TaskExecutor` (see [Background Tasks](tasks.md)) to add higher-level scheduling primitives.

## Quick Start

```python
from hypern import Hypern
from hypern.scheduler import TaskScheduler, RetryPolicy

app = Hypern()
scheduler = app.scheduler  # auto-created TaskScheduler

@scheduler.interval(seconds=60)
def healthcheck():
    print("System healthy")

@scheduler.cron("0 3 * * *")  # daily at 3 AM
def nightly_cleanup():
    cleanup_old_records()

if __name__ == "__main__":
    app.start(host="0.0.0.0", port=8000)
    # scheduler starts automatically with the app
```

---

## Interval Tasks

Run a function at a fixed interval:

```python
@scheduler.interval(seconds=30, name="ping")
def ping():
    print("ping")
```

| Parameter  | Type    | Description                        |
|------------|---------|------------------------------------|
| `seconds`  | `float` | Interval between runs              |
| `retry`    | `RetryPolicy` | Optional retry on failure     |
| `name`     | `str`   | Task name (defaults to func name)  |

---

## Cron Tasks

Schedule with Unix cron expressions (5 fields):

```
┌──────────── minute (0-59)
│ ┌────────── hour (0-23)
│ │ ┌──────── day of month (1-31)
│ │ │ ┌────── month (1-12)
│ │ │ │ ┌──── day of week (0-6, 0=Sunday)
* * * * *
```

Supported syntax: `*`, `*/n`, `n`, `n-m`, `n,m,o`

```python
@scheduler.cron("*/5 * * * *")           # every 5 minutes
def check_queue():
    process_pending()

@scheduler.cron("0 9 * * 1-5")          # weekdays at 9 AM
def morning_report():
    generate_report()

@scheduler.cron("0,30 * * * *")         # at :00 and :30
def half_hourly():
    sync_data()
```

---

## One-Shot Tasks

Register a task that runs once (optionally with a delay):

```python
@scheduler.task(retry=RetryPolicy(max_retries=3))
def send_welcome_email(user_id):
    ...

# Call it to submit — returns a task_id
task_id = send_welcome_email("user-42")
```

---

## Retry Policies

Configure automatic retries with exponential backoff:

```python
from hypern.scheduler import RetryPolicy

policy = RetryPolicy(
    max_retries=3,           # maximum retry attempts
    backoff=1.0,             # base delay in seconds
    backoff_factor=2.0,      # multiplier per attempt (1s → 2s → 4s)
    max_delay=60.0,          # cap on delay
    retry_on=(ConnectionError, TimeoutError),  # only retry these
)
```

### Delay Calculation

```
delay = min(backoff × backoff_factor^attempt, max_delay)
```

| Attempt | Delay (backoff=1, factor=2) |
|---------|-----------------------------|
| 0       | 1.0s                        |
| 1       | 2.0s                        |
| 2       | 4.0s                        |
| 3       | 8.0s                        |

### Exception Filtering

By default, retries are triggered on **any** exception. Use `retry_on` to limit:

```python
# Only retry on network errors
policy = RetryPolicy(
    max_retries=3,
    retry_on=(ConnectionError, TimeoutError),
)
# A ValueError will fail immediately (no retry)
```

---

## Task Monitoring

### Metrics

The scheduler tracks execution metrics automatically:

```python
snapshot = scheduler.get_metrics()
```

Returns a dictionary with:

| Key                | Type    | Description                      |
|--------------------|---------|----------------------------------|
| `total_submitted`  | `int`   | Total tasks submitted            |
| `total_completed`  | `int`   | Successfully completed           |
| `total_failed`     | `int`   | Failed after exhausting retries  |
| `total_retried`    | `int`   | Retry attempts                   |
| `total_cancelled`  | `int`   | Cancelled tasks                  |
| `avg_duration_ms`  | `float` | Average execution time           |
| `p95_duration_ms`  | `float` | 95th percentile duration         |
| `p99_duration_ms`  | `float` | 99th percentile duration         |
| `success_rate`     | `float` | Success percentage (0-100)       |
| `top_errors`       | `list`  | Top error types by frequency     |

### Exposing Metrics via API

```python
@app.get("/admin/tasks/metrics")
def task_metrics(req, res, ctx):
    res.json(scheduler.get_metrics())
```

### Monitor Hooks

Attach callbacks for task lifecycle events:

```python
monitor = scheduler.monitor

@monitor.before_task
def on_start(task_name, args):
    print(f"Starting: {task_name}")

@monitor.after_task
def on_complete(task_name, result, duration):
    print(f"Completed: {task_name} in {duration:.2f}s")

@monitor.on_error
def on_fail(task_name, error, attempt):
    print(f"Failed: {task_name} (attempt {attempt}): {error}")
```

---

## Task Results

Query results of scheduled tasks:

```python
result = scheduler.get_result(task_id)

result.task_id       # "sched-1"
result.task_name     # "send_welcome_email"
result.state         # ScheduledTaskState.COMPLETED / FAILED / etc.
result.result        # return value (on success)
result.error         # error string (on failure)
result.attempts      # number of attempts made
result.duration_ms   # execution time in ms
```

### Task States

| State       | Description                           |
|-------------|---------------------------------------|
| `PENDING`   | Waiting to execute                    |
| `RUNNING`   | Currently executing                   |
| `COMPLETED` | Finished successfully                 |
| `FAILED`    | Failed after exhausting retries       |
| `RETRYING`  | Failed, will retry                    |
| `CANCELLED` | Cancelled before completion           |

---

## Standalone `@periodic` Decorator

For simple interval tasks that don't need the full scheduler API:

```python
from hypern.scheduler import periodic

@periodic(seconds=60)
def heartbeat():
    print("alive")
```

Functions decorated with `@periodic` are auto-registered when the app starts.

---

## Complete Example

```python
from hypern import Hypern
from hypern.scheduler import TaskScheduler, RetryPolicy

app = Hypern()

# Interval task
@app.scheduler.interval(seconds=10)
def ping():
    print("ping")

# Cron task
@app.scheduler.cron("0 */6 * * *")  # every 6 hours
def sync_data():
    fetch_and_store()

# One-shot with retry
@app.scheduler.task(retry=RetryPolicy(max_retries=3, backoff=2.0))
def process_order(order_id):
    charge_payment(order_id)

# Monitor
@app.scheduler.monitor.on_error
def alert(task_name, error, attempt):
    send_alert(f"Task {task_name} failed: {error}")

# Metrics endpoint
@app.get("/metrics")
def metrics(req, res, ctx):
    res.json(app.scheduler.get_metrics())

if __name__ == "__main__":
    app.start(host="0.0.0.0", port=8000)
```
