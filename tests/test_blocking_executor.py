"""
Tests for the BlockingExecutor — Rust-backed GIL-releasing thread pool.

These tests verify:
- Basic run_sync execution
- Parallel execution via run_parallel
- Parallel map
- Error propagation
- Context manager protocol
- Shutdown behaviour
- Module-level helpers and decorator
"""

import time
import pytest

# Import from the Python wrapper layer (doesn't need a built native module for
# the test structure, but will need the compiled extension at runtime).
from hypern.blocking import (
    BlockingExecutor,
    blocking,
    blocking_map,
    blocking_parallel,
    blocking_run,
    get_default_executor,
    set_default_executor,
)


# ============================================================================
# Helpers
# ============================================================================

def cpu_work(n: int) -> int:
    """Simulate CPU-bound work."""
    return sum(i * i for i in range(n))


def identity(x):
    return x


def square(x):
    return x * x


def add(a, b):
    return a + b


def raises_error():
    raise ValueError("intentional error")


def slow_fn(secs: float) -> str:
    time.sleep(secs)
    return "done"


def greet(name, greeting="Hello"):
    return f"{greeting}, {name}!"


# ============================================================================
# Test: BlockingExecutor — run_sync
# ============================================================================

class TestRunSync:
    """Tests for BlockingExecutor.run_sync()."""

    def test_basic_call(self):
        with BlockingExecutor(max_threads=2) as executor:
            result = executor.run_sync(cpu_work, 1000)
            assert result == sum(i * i for i in range(1000))

    def test_with_kwargs(self):
        with BlockingExecutor(max_threads=2) as executor:
            result = executor.run_sync(greet, "World", greeting="Hi")
            assert result == "Hi, World!"

    def test_returns_none(self):
        with BlockingExecutor(max_threads=1) as executor:
            result = executor.run_sync(lambda: None)
            assert result is None

    def test_large_return_value(self):
        def make_list():
            return list(range(100_000))

        with BlockingExecutor(max_threads=2) as executor:
            result = executor.run_sync(make_list)
            assert len(result) == 100_000
            assert result[0] == 0
            assert result[-1] == 99_999

    def test_error_propagation(self):
        with BlockingExecutor(max_threads=1) as executor:
            with pytest.raises(RuntimeError, match="intentional error"):
                executor.run_sync(raises_error)

    def test_multiple_sequential_calls(self):
        with BlockingExecutor(max_threads=2) as executor:
            results = []
            for i in range(10):
                results.append(executor.run_sync(square, i))
            assert results == [i * i for i in range(10)]


# ============================================================================
# Test: BlockingExecutor — run_parallel
# ============================================================================

class TestRunParallel:
    """Tests for BlockingExecutor.run_parallel()."""

    def test_basic_parallel(self):
        with BlockingExecutor(max_threads=4) as executor:
            tasks = [
                (square, (2,)),
                (square, (3,)),
                (square, (4,)),
            ]
            results = executor.run_parallel(tasks)
            assert results == [4, 9, 16]

    def test_parallel_with_kwargs(self):
        with BlockingExecutor(max_threads=2) as executor:
            tasks = [
                (greet, ("Alice",), {"greeting": "Hey"}),
                (greet, ("Bob",), None),
            ]
            results = executor.run_parallel(tasks)
            assert results == ["Hey, Alice!", "Hello, Bob!"]

    def test_parallel_speedup(self):
        """Verify that parallel execution is faster than sequential."""
        n = 4
        sleep_time = 0.1

        with BlockingExecutor(max_threads=n) as executor:
            tasks = [(slow_fn, (sleep_time,)) for _ in range(n)]

            start = time.monotonic()
            results = executor.run_parallel(tasks)
            elapsed = time.monotonic() - start

            assert all(r == "done" for r in results)
            # Should complete in ~1x sleep_time, not n*sleep_time
            assert elapsed < sleep_time * n * 0.8

    def test_error_in_parallel_task(self):
        with BlockingExecutor(max_threads=2) as executor:
            tasks = [
                (square, (5,)),
                (raises_error, ()),
            ]
            with pytest.raises(RuntimeError, match="intentional error"):
                executor.run_parallel(tasks)


# ============================================================================
# Test: BlockingExecutor — map
# ============================================================================

class TestMap:
    """Tests for BlockingExecutor.map()."""

    def test_basic_map(self):
        items = list(range(100))
        with BlockingExecutor(max_threads=4) as executor:
            results = executor.map(square, items)
            assert results == [x * x for x in items]

    def test_empty_list(self):
        with BlockingExecutor(max_threads=2) as executor:
            results = executor.map(square, [])
            assert results == []

    def test_single_item(self):
        with BlockingExecutor(max_threads=2) as executor:
            results = executor.map(square, [42])
            assert results == [1764]

    def test_custom_chunk_size(self):
        items = list(range(50))
        with BlockingExecutor(max_threads=2) as executor:
            results = executor.map(square, items, chunk_size=10)
            assert results == [x * x for x in items]

    def test_preserves_order(self):
        """Results must be in the same order as input items."""
        items = list(range(200))
        with BlockingExecutor(max_threads=8) as executor:
            results = executor.map(identity, items)
            assert results == items

    def test_map_error_propagation(self):
        def fail_on_three(x):
            if x == 3:
                raise ValueError("no threes!")
            return x

        with BlockingExecutor(max_threads=2) as executor:
            with pytest.raises(RuntimeError, match="no threes"):
                executor.map(fail_on_three, list(range(10)))


# ============================================================================
# Test: Lifecycle / Context Manager
# ============================================================================

class TestLifecycle:
    """Tests for executor lifecycle management."""

    def test_context_manager(self):
        with BlockingExecutor(max_threads=2) as executor:
            assert executor.is_running()
            result = executor.run_sync(identity, 42)
            assert result == 42
        # After exiting context, shutdown has been called
        assert not executor.is_running()

    def test_introspection(self):
        executor = BlockingExecutor(max_threads=4)
        assert executor.pool_size() == 4
        assert executor.active_threads() > 0
        assert executor.pending_tasks() == 0
        assert executor.is_running()
        executor.shutdown()

    def test_repr(self):
        executor = BlockingExecutor(max_threads=2)
        r = repr(executor)
        assert "BlockingExecutor" in r
        assert "max_threads=2" in r
        executor.shutdown()

    def test_shutdown_with_wait(self):
        executor = BlockingExecutor(max_threads=2)
        executor.shutdown(wait=True, timeout_secs=5.0)
        assert not executor.is_running()

    def test_run_after_shutdown_raises(self):
        executor = BlockingExecutor(max_threads=1)
        executor.shutdown()
        with pytest.raises(RuntimeError, match="shut down"):
            executor.run_sync(identity, 1)


# ============================================================================
# Test: Module-level helpers
# ============================================================================

class TestModuleHelpers:
    """Tests for module-level convenience functions."""

    def test_blocking_run(self):
        result = blocking_run(square, 7)
        assert result == 49

    def test_blocking_map(self):
        results = blocking_map(square, [1, 2, 3, 4, 5])
        assert results == [1, 4, 9, 16, 25]

    def test_blocking_parallel(self):
        tasks = [
            (add, (1, 2)),
            (add, (3, 4)),
        ]
        results = blocking_parallel(tasks)
        assert results == [3, 7]

    def test_get_default_executor(self):
        ex = get_default_executor()
        assert isinstance(ex, BlockingExecutor)
        assert ex.is_running()

    def test_set_default_executor(self):
        custom = BlockingExecutor(max_threads=2)
        set_default_executor(custom)
        assert get_default_executor() is custom
        custom.shutdown()


# ============================================================================
# Test: @blocking decorator
# ============================================================================

class TestBlockingDecorator:
    """Tests for the @blocking decorator."""

    def test_decorator_no_args(self):
        @blocking
        def my_fn(x):
            return x * 2

        assert my_fn(21) == 42
        assert my_fn.__blocking__ is True

    def test_decorator_with_executor(self):
        pool = BlockingExecutor(max_threads=2)

        @blocking(executor=pool)
        def my_fn(x):
            return x + 1

        assert my_fn(10) == 11
        pool.shutdown()

    def test_decorator_preserves_name(self):
        @blocking
        def named_function():
            pass

        assert named_function.__name__ == "named_function"
