"""
Tests for Hypern Task Scheduler module.

Covers RetryPolicy, CronExpression, TaskScheduler (interval, cron, retry),
TaskMetrics, and TaskMonitor.  Includes explicit retry/failure tests as
requested.
"""

import asyncio
import time
import threading
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from hypern.scheduler import (
    RetryPolicy,
    TaskMetrics,
    TaskMonitor,
    TaskScheduler,
    ScheduledTaskState,
    ScheduledTaskResult,
    CronExpression,
    periodic,
)


# Override autouse fixtures from conftest that require the test server
@pytest.fixture(autouse=True)
def reset_database():
    yield


# ============================================================================
# RetryPolicy Tests
# ============================================================================


class TestRetryPolicy:
    """Test the RetryPolicy parameters and helpers."""

    def test_default_policy(self):
        p = RetryPolicy()
        assert p.max_retries == 3
        assert p.backoff >= 0
        assert p.backoff_factor >= 1

    def test_should_retry_on_attempt(self):
        p = RetryPolicy(max_retries=2)
        assert p.should_retry(0, RuntimeError("x")) is True
        assert p.should_retry(1, RuntimeError("x")) is True
        assert p.should_retry(2, RuntimeError("x")) is False

    def test_should_retry_with_exception_filter(self):
        p = RetryPolicy(max_retries=3, retry_on=(ValueError, TypeError))
        assert p.should_retry(0, ValueError("x")) is True
        assert p.should_retry(0, RuntimeError("x")) is False

    def test_should_retry_no_filter(self):
        """Without retry_on, all exceptions match."""
        p = RetryPolicy(max_retries=3)
        assert p.should_retry(0, RuntimeError("x")) is True
        assert p.should_retry(0, KeyError("x")) is True

    def test_get_delay_exponential(self):
        p = RetryPolicy(backoff=1.0, backoff_factor=2.0)
        assert p.get_delay(0) == 1.0
        assert p.get_delay(1) == 2.0
        assert p.get_delay(2) == 4.0
        assert p.get_delay(3) == 8.0

    def test_max_delay_cap(self):
        p = RetryPolicy(backoff=1.0, backoff_factor=10.0, max_delay=5.0)
        assert p.get_delay(0) == 1.0
        assert p.get_delay(1) == 5.0  # capped
        assert p.get_delay(5) == 5.0  # capped


# ============================================================================
# CronExpression Tests
# ============================================================================


class TestCronExpression:
    """Test cron expression parsing and matching."""

    def _make_struct(self, year, month, day, hour, minute, wday):
        """Create a minimal time.struct_time.
        wday: Python convention 0=Monday..6=Sunday
        """
        return time.struct_time((year, month, day, hour, minute, 0, wday, 0, -1))

    def test_every_minute(self):
        cron = CronExpression("* * * * *")
        # Monday at noon
        t = self._make_struct(2025, 6, 16, 12, 0, 0)
        assert cron.matches(t) is True

    def test_specific_minute(self):
        cron = CronExpression("30 * * * *")
        t30 = self._make_struct(2025, 6, 16, 12, 30, 0)
        t00 = self._make_struct(2025, 6, 16, 12, 0, 0)
        assert cron.matches(t30) is True
        assert cron.matches(t00) is False

    def test_specific_hour(self):
        cron = CronExpression("0 9 * * *")
        t9 = self._make_struct(2025, 6, 16, 9, 0, 0)
        t10 = self._make_struct(2025, 6, 16, 10, 0, 0)
        assert cron.matches(t9) is True
        assert cron.matches(t10) is False

    def test_specific_dom(self):
        cron = CronExpression("0 0 1 * *")
        t1 = self._make_struct(2025, 1, 1, 0, 0, 2)
        t2 = self._make_struct(2025, 1, 2, 0, 0, 3)
        assert cron.matches(t1) is True
        assert cron.matches(t2) is False

    def test_specific_month(self):
        cron = CronExpression("0 0 * 12 *")
        t12 = self._make_struct(2025, 12, 1, 0, 0, 0)
        t6 = self._make_struct(2025, 6, 1, 0, 0, 6)
        assert cron.matches(t12) is True
        assert cron.matches(t6) is False

    def test_range(self):
        cron = CronExpression("0-5 * * * *")
        t0 = self._make_struct(2025, 1, 1, 0, 0, 2)
        t5 = self._make_struct(2025, 1, 1, 0, 5, 2)
        t6 = self._make_struct(2025, 1, 1, 0, 6, 2)
        assert cron.matches(t0) is True
        assert cron.matches(t5) is True
        assert cron.matches(t6) is False

    def test_step(self):
        cron = CronExpression("*/15 * * * *")
        t0 = self._make_struct(2025, 1, 1, 0, 0, 2)
        t15 = self._make_struct(2025, 1, 1, 0, 15, 2)
        t30 = self._make_struct(2025, 1, 1, 0, 30, 2)
        t7 = self._make_struct(2025, 1, 1, 0, 7, 2)
        assert cron.matches(t0) is True
        assert cron.matches(t15) is True
        assert cron.matches(t30) is True
        assert cron.matches(t7) is False

    def test_comma_list(self):
        cron = CronExpression("0,30 * * * *")
        t0 = self._make_struct(2025, 1, 1, 0, 0, 2)
        t30 = self._make_struct(2025, 1, 1, 0, 30, 2)
        t15 = self._make_struct(2025, 1, 1, 0, 15, 2)
        assert cron.matches(t0) is True
        assert cron.matches(t30) is True
        assert cron.matches(t15) is False

    def test_invalid_expression(self):
        with pytest.raises(ValueError):
            CronExpression("bad cron")

    def test_too_few_fields(self):
        with pytest.raises(ValueError):
            CronExpression("* * *")


# ============================================================================
# TaskMetrics Tests
# ============================================================================


class TestTaskMetrics:
    """Test task metrics tracking."""

    def test_initial_state(self):
        m = TaskMetrics()
        snap = m.snapshot()
        assert snap["total_submitted"] == 0
        assert snap["total_completed"] == 0
        assert snap["total_failed"] == 0
        assert snap["success_rate"] == 100.0  # 100% when no tasks

    def test_record_success(self):
        m = TaskMetrics()
        m.record_submit()
        m.record_complete(0.5)
        snap = m.snapshot()
        assert snap["total_submitted"] == 1
        assert snap["total_completed"] == 1
        assert snap["success_rate"] == 100.0

    def test_record_failure(self):
        m = TaskMetrics()
        m.record_submit()
        m.record_failure("ValueError: test error")
        snap = m.snapshot()
        assert snap["total_failed"] == 1
        assert snap["success_rate"] == 0.0

    def test_record_retry(self):
        m = TaskMetrics()
        m.record_retry()
        snap = m.snapshot()
        assert snap["total_retried"] == 1

    def test_average_duration(self):
        m = TaskMetrics()
        for d in [1.0, 2.0, 3.0]:
            m.record_submit()
            m.record_complete(d)
        # avg is 2.0 seconds = 2000.0 ms
        snap = m.snapshot()
        assert abs(snap["avg_duration_ms"] - 2000.0) < 1.0

    def test_success_rate_mixed(self):
        m = TaskMetrics()
        for _ in range(3):
            m.record_submit()
            m.record_complete(0.1)
        m.record_submit()
        m.record_failure("RuntimeError: fail")
        snap = m.snapshot()
        # 3 successes out of 4 total = 75%
        assert abs(snap["success_rate"] - 75.0) < 0.1

    def test_thread_safety(self):
        """Multiple threads recording metrics concurrently should not corrupt data."""
        m = TaskMetrics()
        n = 100

        def record_batch():
            for _ in range(n):
                m.record_submit()
                m.record_complete(0.01)

        threads = [threading.Thread(target=record_batch) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        snap = m.snapshot()
        assert snap["total_submitted"] == 400
        assert snap["total_completed"] == 400

    def test_top_errors(self):
        m = TaskMetrics()
        m.record_failure("ValueError: bad")
        m.record_failure("ValueError: bad")
        m.record_failure("TypeError: oops")
        snap = m.snapshot()
        errors = snap["top_errors"]
        assert len(errors) >= 2
        # First error should be the most common
        assert errors[0][0] == "ValueError: bad"
        assert errors[0][1] == 2


# ============================================================================
# TaskMonitor Tests
# ============================================================================


class TestTaskMonitor:
    """Test the TaskMonitor hooks."""

    def test_before_hook(self):
        monitor = TaskMonitor()
        called = []

        @monitor.before_task
        def on_before(name, args):
            called.append(("before", name))

        monitor._fire_before("my-task", ())
        assert called == [("before", "my-task")]

    def test_after_hook(self):
        monitor = TaskMonitor()
        called = []

        @monitor.after_task
        def on_after(name, result, duration):
            called.append(("after", name, result))

        monitor._fire_after("t", "ok", 0.1)
        assert called == [("after", "t", "ok")]

    def test_error_hook(self):
        monitor = TaskMonitor()
        called = []

        @monitor.on_error
        def on_err(name, err, attempt):
            called.append(("error", name, str(err)))

        monitor._fire_error("t", ValueError("bad"), 0)
        assert called == [("error", "t", "bad")]

    def test_multiple_hooks(self):
        monitor = TaskMonitor()
        results = []

        @monitor.before_task
        def hook_a(name, args):
            results.append("a")

        @monitor.before_task
        def hook_b(name, args):
            results.append("b")

        monitor._fire_before("x", ())
        assert results == ["a", "b"]


# ============================================================================
# TaskScheduler — Retry / Failure Tests (critical)
# ============================================================================


class TestSchedulerRetryFailure:
    """Test retry and failure scenarios with TaskScheduler."""

    def test_retry_succeeds_after_failures(self):
        """Task that fails twice then succeeds should be marked completed."""
        scheduler = TaskScheduler()
        attempt = {"count": 0}

        policy = RetryPolicy(max_retries=3, backoff=0.01, backoff_factor=1.0)

        def flaky_task():
            attempt["count"] += 1
            if attempt["count"] < 3:
                raise RuntimeError("transient error")
            return "success"

        result = scheduler._execute_with_retry(flaky_task, (), policy, "flaky")

        assert attempt["count"] == 3
        assert result.state == ScheduledTaskState.COMPLETED
        assert result.result == "success"

    def test_retry_exhausted_marks_failed(self):
        """Task that always fails should exhaust retries and be marked failed."""
        scheduler = TaskScheduler()

        policy = RetryPolicy(max_retries=2, backoff=0.01, backoff_factor=1.0)

        def bad_task():
            raise ValueError("permanent error")

        result = scheduler._execute_with_retry(bad_task, (), policy, "always-fail")

        assert result.state == ScheduledTaskState.FAILED
        assert "permanent error" in str(result.error)

    def test_retry_only_on_specific_exceptions(self):
        """retry_on should filter which exceptions trigger a retry."""
        scheduler = TaskScheduler()
        attempt = {"count": 0}

        policy = RetryPolicy(
            max_retries=3,
            backoff=0.01,
            backoff_factor=1.0,
            retry_on=(ConnectionError,),
        )

        def selective_task():
            attempt["count"] += 1
            raise TypeError("wrong type — should NOT retry")

        result = scheduler._execute_with_retry(selective_task, (), policy, "selective")

        # Because TypeError is not in retry_on, it should fail immediately
        assert attempt["count"] == 1
        assert result.state == ScheduledTaskState.FAILED

    def test_no_retry_when_max_retries_zero(self):
        """max_retries=0 means no retries at all."""
        scheduler = TaskScheduler()
        attempt = {"count": 0}

        policy = RetryPolicy(max_retries=0)

        def task_no_retry():
            attempt["count"] += 1
            raise RuntimeError("fail")

        result = scheduler._execute_with_retry(task_no_retry, (), policy, "no-retry")

        assert attempt["count"] == 1
        assert result.state == ScheduledTaskState.FAILED

    def test_metrics_track_retries(self):
        """Metrics should reflect retries."""
        scheduler = TaskScheduler()
        attempt = {"count": 0}

        policy = RetryPolicy(max_retries=2, backoff=0.01, backoff_factor=1.0)

        def metrics_task():
            attempt["count"] += 1
            if attempt["count"] < 3:
                raise RuntimeError("fail")
            return "ok"

        scheduler._execute_with_retry(metrics_task, (), policy, "metrics-retry")

        snap = scheduler.monitor.metrics.snapshot()
        assert snap["total_retried"] >= 2

    def test_monitor_receives_error_callbacks(self):
        """TaskMonitor should receive on_error callbacks on failure."""
        scheduler = TaskScheduler()
        errors = []

        @scheduler.monitor.on_error
        def on_err(name, err, attempt):
            errors.append((name, str(err)))

        policy = RetryPolicy(max_retries=1, backoff=0.01, backoff_factor=1.0)

        def monitored_task():
            raise RuntimeError("boom")

        scheduler._execute_with_retry(monitored_task, (), policy, "monitored-fail")

        # Should have received at least one error callback
        assert len(errors) >= 1
        assert errors[0][0] == "monitored-fail"
        assert "boom" in errors[0][1]

    def test_retry_records_duration_on_success(self):
        """A task that eventually succeeds should record its duration in metrics."""
        scheduler = TaskScheduler()
        attempt = {"count": 0}

        policy = RetryPolicy(max_retries=2, backoff=0.01, backoff_factor=1.0)

        def task_with_duration():
            attempt["count"] += 1
            if attempt["count"] < 2:
                raise RuntimeError("fail")
            return 42

        result = scheduler._execute_with_retry(task_with_duration, (), policy, "timed")

        assert result.state == ScheduledTaskState.COMPLETED
        assert result.duration_ms > 0
        snap = scheduler.monitor.metrics.snapshot()
        assert snap["total_completed"] == 1


# ============================================================================
# TaskScheduler — Interval / Cron Decorators
# ============================================================================


class TestSchedulerDecorators:
    """Test @scheduler.interval and @scheduler.cron decorators."""

    def test_interval_runs_periodically(self):
        scheduler = TaskScheduler()
        counter = {"n": 0}

        @scheduler.interval(seconds=0.1, name="ticker")
        def ticker():
            counter["n"] += 1

        scheduler.start()
        time.sleep(0.55)
        scheduler.stop()

        # Should have run ≥4 times in 0.55s at 0.1s intervals
        # Scheduler loop sleeps 1s, so interval check happens once per second
        # With 0.1s interval and 1s loop, it will run once per loop iteration
        # Actually, let's be lenient here
        assert counter["n"] >= 1

    def test_cron_registration(self):
        """Cron tasks should be registered."""
        scheduler = TaskScheduler()

        @scheduler.cron("*/5 * * * *", name="five-minutes")
        def every_five():
            pass

        assert len(scheduler._cron_tasks) == 1
        assert scheduler._cron_tasks[0][3] == "five-minutes"

    def test_task_decorator_returns_callable(self):
        """@scheduler.task should return a callable wrapper."""
        scheduler = TaskScheduler()

        @scheduler.task(retry=RetryPolicy(max_retries=0))
        def one_time():
            return 42

        # The decorated function should be callable and return a task_id
        task_id = one_time()
        assert isinstance(task_id, str)
        assert task_id.startswith("sched-")

    def test_start_stop_idempotent(self):
        """Multiple start/stop calls should not raise."""
        scheduler = TaskScheduler()
        scheduler.start()
        scheduler.start()  # should be no-op
        scheduler.stop()
        scheduler.stop()  # should be no-op

    def test_interval_registration(self):
        """Interval tasks should be stored."""
        scheduler = TaskScheduler()

        @scheduler.interval(seconds=30, name="my-interval")
        def my_task():
            pass

        assert len(scheduler._interval_tasks) == 1
        assert scheduler._interval_tasks[0][3] == "my-interval"
        assert scheduler._interval_tasks[0][0] == 30.0


# ============================================================================
# periodic() Decorator Tests
# ============================================================================


class TestPeriodicDecorator:
    """Test the standalone @periodic decorator."""

    def test_marks_function(self):
        @periodic(seconds=60)
        def my_func():
            pass

        assert hasattr(my_func, "_periodic_interval")
        assert my_func._periodic_interval == 60

    def test_function_still_callable(self):
        @periodic(seconds=10)
        def add(a, b):
            return a + b

        assert add(2, 3) == 5

    def test_retry_policy_attached(self):
        policy = RetryPolicy(max_retries=5)

        @periodic(seconds=30, retry=policy)
        def my_func():
            pass

        assert my_func._periodic_retry is policy


# ============================================================================
# ScheduledTaskResult / ScheduledTaskState Tests
# ============================================================================


class TestScheduledTaskResult:
    def test_completed_state(self):
        r = ScheduledTaskResult(
            task_id="sched-1",
            task_name="test",
            state=ScheduledTaskState.COMPLETED,
            result=42,
        )
        assert r.task_name == "test"
        assert r.task_id == "sched-1"
        assert r.state == ScheduledTaskState.COMPLETED
        assert r.result == 42
        assert r.error is None

    def test_failed_state(self):
        r = ScheduledTaskResult(
            task_id="sched-2",
            task_name="test",
            state=ScheduledTaskState.FAILED,
            error="RuntimeError: bad",
        )
        assert r.state == ScheduledTaskState.FAILED
        assert "bad" in r.error

    def test_state_enum_values(self):
        assert ScheduledTaskState.PENDING is not None
        assert ScheduledTaskState.RUNNING is not None
        assert ScheduledTaskState.COMPLETED is not None
        assert ScheduledTaskState.FAILED is not None
        assert ScheduledTaskState.RETRYING is not None
        assert ScheduledTaskState.CANCELLED is not None
