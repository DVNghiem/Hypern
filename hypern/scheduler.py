"""
Extended task scheduling and monitoring for Hypern background tasks.

Builds on top of the core :class:`TaskExecutor` to add:

- **Cron-like scheduling** via :class:`TaskScheduler`.
- **Retry policies** with exponential back-off via :class:`RetryPolicy`.
- **Task monitoring** with metrics via :class:`TaskMonitor`.
- **Periodic (interval) tasks** via :func:`periodic`.

Example:
    from hypern.scheduler import TaskScheduler, RetryPolicy, periodic

    scheduler = TaskScheduler()

    # Run every 30 seconds
    @periodic(seconds=30)
    def health_check():
        print("ping")

    # Cron expression: every day at 3:00 AM
    @scheduler.cron("0 3 * * *")
    def nightly_cleanup():
        ...

    # With retry
    @scheduler.task(retry=RetryPolicy(max_retries=3, backoff=2.0))
    def flaky_task(data):
        ...
"""

from __future__ import annotations

import asyncio
import functools
import logging
import math
import re
import threading
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("hypern.scheduler")


# ============================================================================
# Retry Policy
# ============================================================================


class RetryPolicy:
    """
    Configurable retry policy with exponential back-off.

    Args:
        max_retries: Maximum number of retry attempts.
        backoff: Base delay in seconds between retries.
        backoff_factor: Multiplier applied to the delay on each retry.
        max_delay: Upper bound for the back-off delay.
        retry_on: Optional tuple of exception types to retry on.
                   If ``None``, retries on all exceptions.

    Example:
        policy = RetryPolicy(max_retries=3, backoff=1.0, backoff_factor=2.0)
        # Delays: 1s, 2s, 4s
    """

    def __init__(
        self,
        max_retries: int = 3,
        backoff: float = 1.0,
        backoff_factor: float = 2.0,
        max_delay: float = 60.0,
        retry_on: Optional[Tuple[type, ...]] = None,
    ):
        self.max_retries = max_retries
        self.backoff = backoff
        self.backoff_factor = backoff_factor
        self.max_delay = max_delay
        self.retry_on = retry_on

    def should_retry(self, attempt: int, exc: Exception) -> bool:
        """Return True if the task should be retried."""
        if attempt >= self.max_retries:
            return False
        if self.retry_on is not None:
            return isinstance(exc, self.retry_on)
        return True

    def get_delay(self, attempt: int) -> float:
        """Calculate the delay before the next retry."""
        delay = self.backoff * (self.backoff_factor ** attempt)
        return min(delay, self.max_delay)


# ============================================================================
# Task Monitoring
# ============================================================================


class TaskMetrics:
    """Thread-safe task execution metrics."""

    def __init__(self):
        self._lock = threading.Lock()
        self.total_submitted: int = 0
        self.total_completed: int = 0
        self.total_failed: int = 0
        self.total_retried: int = 0
        self.total_cancelled: int = 0
        self._durations: List[float] = []
        self._failure_counts: Dict[str, int] = {}

    def record_submit(self) -> None:
        with self._lock:
            self.total_submitted += 1

    def record_complete(self, duration: float) -> None:
        with self._lock:
            self.total_completed += 1
            self._durations.append(duration)
            # Keep only last 1000 durations
            if len(self._durations) > 1000:
                self._durations = self._durations[-1000:]

    def record_failure(self, error: str) -> None:
        with self._lock:
            self.total_failed += 1
            self._failure_counts[error] = self._failure_counts.get(error, 0) + 1

    def record_retry(self) -> None:
        with self._lock:
            self.total_retried += 1

    def record_cancel(self) -> None:
        with self._lock:
            self.total_cancelled += 1

    @property
    def avg_duration(self) -> float:
        """Average task duration in seconds."""
        with self._lock:
            if not self._durations:
                return 0.0
            return sum(self._durations) / len(self._durations)

    @property
    def p95_duration(self) -> float:
        """95th percentile task duration."""
        with self._lock:
            if not self._durations:
                return 0.0
            sorted_d = sorted(self._durations)
            idx = int(math.ceil(0.95 * len(sorted_d))) - 1
            return sorted_d[max(0, idx)]

    @property
    def p99_duration(self) -> float:
        """99th percentile task duration."""
        with self._lock:
            if not self._durations:
                return 0.0
            sorted_d = sorted(self._durations)
            idx = int(math.ceil(0.99 * len(sorted_d))) - 1
            return sorted_d[max(0, idx)]

    @property
    def success_rate(self) -> float:
        """Success rate as a percentage."""
        total = self.total_completed + self.total_failed
        if total == 0:
            return 100.0
        return (self.total_completed / total) * 100.0

    @property
    def top_errors(self) -> List[Tuple[str, int]]:
        """Top error types sorted by frequency."""
        with self._lock:
            return sorted(self._failure_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    def snapshot(self) -> Dict[str, Any]:
        """Return a JSON-serialisable snapshot of all metrics."""
        return {
            "total_submitted": self.total_submitted,
            "total_completed": self.total_completed,
            "total_failed": self.total_failed,
            "total_retried": self.total_retried,
            "total_cancelled": self.total_cancelled,
            "avg_duration_ms": round(self.avg_duration * 1000, 2),
            "p95_duration_ms": round(self.p95_duration * 1000, 2),
            "p99_duration_ms": round(self.p99_duration * 1000, 2),
            "success_rate": round(self.success_rate, 2),
            "top_errors": self.top_errors,
        }


class TaskMonitor:
    """
    Central task monitoring facility.

    Attach to the application to track all background task activity.

    Example:
        monitor = TaskMonitor()

        @app.get("/admin/tasks/metrics")
        def metrics(req, res, ctx):
            res.json(monitor.metrics.snapshot())
    """

    def __init__(self):
        self.metrics = TaskMetrics()
        self._hooks_before: List[Callable] = []
        self._hooks_after: List[Callable] = []
        self._hooks_error: List[Callable] = []

    def before_task(self, func: Callable) -> Callable:
        """Register a hook called before each task executes."""
        self._hooks_before.append(func)
        return func

    def after_task(self, func: Callable) -> Callable:
        """Register a hook called after each task completes successfully."""
        self._hooks_after.append(func)
        return func

    def on_error(self, func: Callable) -> Callable:
        """Register a hook called when a task fails."""
        self._hooks_error.append(func)
        return func

    def _fire_before(self, task_name: str, args: tuple) -> None:
        for hook in self._hooks_before:
            try:
                hook(task_name, args)
            except Exception:
                pass

    def _fire_after(self, task_name: str, result: Any, duration: float) -> None:
        for hook in self._hooks_after:
            try:
                hook(task_name, result, duration)
            except Exception:
                pass

    def _fire_error(self, task_name: str, error: Exception, attempt: int) -> None:
        for hook in self._hooks_error:
            try:
                hook(task_name, error, attempt)
            except Exception:
                pass


# ============================================================================
# Scheduled Task State
# ============================================================================


class ScheduledTaskState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


@dataclass
class ScheduledTaskResult:
    """Result of a scheduled task execution."""
    task_id: str
    task_name: str
    state: ScheduledTaskState
    result: Any = None
    error: Optional[str] = None
    attempts: int = 0
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    next_run: Optional[float] = None
    duration_ms: float = 0.0


# ============================================================================
# Cron expression parser (minimal)
# ============================================================================


class CronExpression:
    """
    Minimal cron expression parser supporting five fields::

        ┌──────────── minute (0-59)
        │ ┌────────── hour (0-23)
        │ │ ┌──────── day of month (1-31)
        │ │ │ ┌────── month (1-12)
        │ │ │ │ ┌──── day of week (0-6, 0=Sunday)
        * * * * *

    Supports: ``*``, ``*/n``, ``n``, ``n-m``, ``n,m``.
    """

    def __init__(self, expression: str):
        self.expression = expression.strip()
        parts = self.expression.split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression (need 5 fields): {expression}")
        self._minute = self._parse_field(parts[0], 0, 59)
        self._hour = self._parse_field(parts[1], 0, 23)
        self._dom = self._parse_field(parts[2], 1, 31)
        self._month = self._parse_field(parts[3], 1, 12)
        self._dow = self._parse_field(parts[4], 0, 6)

    @staticmethod
    def _parse_field(field: str, min_val: int, max_val: int) -> set:
        values = set()
        for part in field.split(","):
            part = part.strip()
            if part == "*":
                values.update(range(min_val, max_val + 1))
            elif part.startswith("*/"):
                step = int(part[2:])
                values.update(range(min_val, max_val + 1, step))
            elif "-" in part:
                start, end = part.split("-", 1)
                values.update(range(int(start), int(end) + 1))
            else:
                values.add(int(part))
        return values

    def matches(self, t: time.struct_time) -> bool:
        """Check if the time matches this cron expression."""
        return (
            t.tm_min in self._minute
            and t.tm_hour in self._hour
            and t.tm_mday in self._dom
            and t.tm_mon in self._month
            and t.tm_wday in self._dow  # Python: 0=Monday; adjust below
        )

    def matches_now(self) -> bool:
        """Check if the **current local time** matches."""
        t = time.localtime()
        # Python tm_wday: 0=Mon..6=Sun. Cron: 0=Sun..6=Sat.
        cron_dow = (t.tm_wday + 1) % 7
        return (
            t.tm_min in self._minute
            and t.tm_hour in self._hour
            and t.tm_mday in self._dom
            and t.tm_mon in self._month
            and cron_dow in self._dow
        )


# ============================================================================
# Task Scheduler
# ============================================================================


class TaskScheduler:
    """
    Background task scheduler with cron, interval, retry, and monitoring.

    This complements the core :class:`TaskExecutor` by providing higher-level
    scheduling primitives.

    Args:
        monitor: Optional :class:`TaskMonitor` for metrics.

    Example:
        scheduler = TaskScheduler()

        @scheduler.cron("*/5 * * * *")  # every 5 minutes
        def check_health():
            print("OK")

        @scheduler.interval(seconds=10)
        def ping():
            print("ping")

        scheduler.start()   # starts the scheduler loop in a background thread
        # ...
        scheduler.stop()
    """

    def __init__(self, monitor: Optional[TaskMonitor] = None):
        self.monitor = monitor or TaskMonitor()
        self._cron_tasks: List[Tuple[CronExpression, Callable, RetryPolicy, str]] = []
        self._interval_tasks: List[Tuple[float, Callable, RetryPolicy, str, float]] = []
        self._one_shot_tasks: List[Tuple[float, Callable, tuple, RetryPolicy, str]] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._results: Dict[str, ScheduledTaskResult] = {}
        self._lock = threading.Lock()
        self._task_counter = 0

    def _next_id(self) -> str:
        with self._lock:
            self._task_counter += 1
            return f"sched-{self._task_counter}"

    # ------------------------------------------------------------------
    # Registration decorators
    # ------------------------------------------------------------------

    def cron(self, expression: str, retry: Optional[RetryPolicy] = None, name: Optional[str] = None) -> Callable:
        """
        Decorator to schedule a function on a cron expression.

        Example:
            @scheduler.cron("0 3 * * *")  # daily at 3 AM
            def nightly_job():
                ...
        """
        cron_expr = CronExpression(expression)
        policy = retry or RetryPolicy(max_retries=0)

        def decorator(func: Callable) -> Callable:
            task_name = name or func.__name__
            self._cron_tasks.append((cron_expr, func, policy, task_name))
            return func
        return decorator

    def interval(self, seconds: float, retry: Optional[RetryPolicy] = None, name: Optional[str] = None) -> Callable:
        """
        Decorator to run a function at a fixed interval.

        Example:
            @scheduler.interval(seconds=60)
            def every_minute():
                ...
        """
        policy = retry or RetryPolicy(max_retries=0)

        def decorator(func: Callable) -> Callable:
            task_name = name or func.__name__
            self._interval_tasks.append((seconds, func, policy, task_name, 0.0))
            return func
        return decorator

    def task(self, retry: Optional[RetryPolicy] = None, delay_seconds: float = 0) -> Callable:
        """
        Decorator for a one-shot task submitted to the scheduler.

        Args:
            retry: Retry policy.
            delay_seconds: Delay before first execution.

        Example:
            @scheduler.task(retry=RetryPolicy(max_retries=3))
            def important_job(data):
                ...

            # Later:
            important_job("some data")
        """
        policy = retry or RetryPolicy(max_retries=0)

        def decorator(func: Callable) -> Callable:
            task_name = func.__name__

            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                task_id = self._next_id()
                run_at = time.time() + delay_seconds

                def runner():
                    return func(*args, **kwargs)

                self._one_shot_tasks.append((run_at, runner, args, policy, task_name))
                self._results[task_id] = ScheduledTaskResult(
                    task_id=task_id,
                    task_name=task_name,
                    state=ScheduledTaskState.PENDING,
                    next_run=run_at,
                )
                self.monitor.metrics.record_submit()
                return task_id

            return wrapper
        return decorator

    # ------------------------------------------------------------------
    # Execution helpers
    # ------------------------------------------------------------------

    def _execute_with_retry(self, func: Callable, args: tuple, policy: RetryPolicy, task_name: str) -> ScheduledTaskResult:
        """Execute a function with retry policy and return a result."""
        task_id = self._next_id()
        result = ScheduledTaskResult(
            task_id=task_id,
            task_name=task_name,
            state=ScheduledTaskState.RUNNING,
            started_at=time.time(),
        )

        self.monitor._fire_before(task_name, args)

        for attempt in range(policy.max_retries + 1):
            result.attempts = attempt + 1
            try:
                start = time.perf_counter()
                ret = func(*args) if args else func()
                duration = time.perf_counter() - start
                result.result = ret
                result.state = ScheduledTaskState.COMPLETED
                result.completed_at = time.time()
                result.duration_ms = round(duration * 1000, 6)
                self.monitor.metrics.record_complete(duration)
                self.monitor._fire_after(task_name, ret, duration)
                break
            except Exception as exc:
                error_str = f"{type(exc).__name__}: {exc}"
                result.error = error_str
                self.monitor._fire_error(task_name, exc, attempt)

                if policy.should_retry(attempt, exc):
                    result.state = ScheduledTaskState.RETRYING
                    self.monitor.metrics.record_retry()
                    delay = policy.get_delay(attempt)
                    logger.warning(
                        "Task %s failed (attempt %d/%d), retrying in %.1fs: %s",
                        task_name, attempt + 1, policy.max_retries + 1, delay, error_str,
                    )
                    time.sleep(delay)
                else:
                    result.state = ScheduledTaskState.FAILED
                    result.completed_at = time.time()
                    self.monitor.metrics.record_failure(error_str)
                    logger.error("Task %s failed permanently: %s", task_name, error_str)
                    break

        with self._lock:
            self._results[task_id] = result
        return result

    # ------------------------------------------------------------------
    # Scheduler loop
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the scheduler in a background daemon thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="hypern-scheduler")
        self._thread.start()
        logger.info("TaskScheduler started")

    def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("TaskScheduler stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    def _loop(self) -> None:
        """Main scheduler loop running in a background thread."""
        # Track the last minute we fired cron tasks to avoid double-firing
        last_cron_minute = -1
        # Track last run times for interval tasks
        interval_last_run = [0.0] * len(self._interval_tasks)

        while self._running:
            now = time.time()
            t = time.localtime(now)

            # --- Cron tasks ---
            current_minute = t.tm_min + t.tm_hour * 60
            if current_minute != last_cron_minute:
                last_cron_minute = current_minute
                for cron_expr, func, policy, task_name in self._cron_tasks:
                    if cron_expr.matches_now():
                        try:
                            self._execute_with_retry(func, (), policy, task_name)
                        except Exception:
                            logger.exception("Error running cron task %s", task_name)

            # --- Interval tasks ---
            for i, (interval, func, policy, task_name, _) in enumerate(self._interval_tasks):
                if now - interval_last_run[i] >= interval:
                    interval_last_run[i] = now
                    try:
                        self._execute_with_retry(func, (), policy, task_name)
                    except Exception:
                        logger.exception("Error running interval task %s", task_name)

            # --- One-shot tasks ---
            pending = []
            for run_at, func, args, policy, task_name in self._one_shot_tasks:
                if now >= run_at:
                    try:
                        self._execute_with_retry(func, args, policy, task_name)
                    except Exception:
                        logger.exception("Error running one-shot task %s", task_name)
                else:
                    pending.append((run_at, func, args, policy, task_name))
            self._one_shot_tasks = pending

            # Sleep for ~1 second before checking again
            time.sleep(1.0)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_result(self, task_id: str) -> Optional[ScheduledTaskResult]:
        """Get the result of a scheduled task by ID."""
        with self._lock:
            return self._results.get(task_id)

    def get_all_results(self) -> Dict[str, ScheduledTaskResult]:
        """Get all task results."""
        with self._lock:
            return dict(self._results)

    def get_metrics(self) -> Dict[str, Any]:
        """Get a snapshot of task metrics."""
        return self.monitor.metrics.snapshot()


# ============================================================================
# Convenience decorator
# ============================================================================


def periodic(seconds: float, retry: Optional[RetryPolicy] = None) -> Callable:
    """
    Standalone decorator to mark a function as a periodic task.

    The function will be registered with a :class:`TaskScheduler` when the
    app starts. Use this as a simple alternative to ``@scheduler.interval``.

    Example:
        @periodic(seconds=30)
        def heartbeat():
            print("alive")
    """

    def decorator(func: Callable) -> Callable:
        func._periodic_interval = seconds
        func._periodic_retry = retry
        return func

    return decorator


__all__ = [
    "RetryPolicy",
    "TaskMetrics",
    "TaskMonitor",
    "ScheduledTaskState",
    "ScheduledTaskResult",
    "CronExpression",
    "TaskScheduler",
    "periodic",
]
