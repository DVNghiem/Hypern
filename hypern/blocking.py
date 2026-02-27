"""
High-performance blocking executor — run Python callables on Rust threads.

This module provides :class:`BlockingExecutor`, a Rust-backed thread-pool
executor that **releases the GIL** while the calling thread waits for results.
This enables true CPU parallelism for Python code without the overhead of
multiprocessing or the GIL contention of ``concurrent.futures.ThreadPoolExecutor``.

Quick start::

    from hypern.blocking import BlockingExecutor, blocking_run, blocking_map

    # --- Option 1: Use the class directly ---
    executor = BlockingExecutor(max_threads=8)
    result = executor.run_sync(heavy_fn, arg1, arg2)
    results = executor.map(transform, items, chunk_size=256)
    executor.shutdown()

    # --- Option 2: Use the module-level helpers ---
    result = blocking_run(cpu_intensive_fn, x, y)
    results = blocking_map(transform, big_list)

    # --- Option 3: Use the decorator ---
    from hypern.blocking import blocking

    @blocking
    def my_heavy_function(data):
        # This will run on a Rust thread, GIL released while caller waits
        return expensive_computation(data)

    result = my_heavy_function(data)
"""

from __future__ import annotations

import functools
import os
from typing import Any, Callable, List, Optional, TypeVar

from hypern._hypern import BlockingExecutor

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Module-level default executor (lazy-initialised)
# ---------------------------------------------------------------------------

_default_executor: Optional[BlockingExecutor] = None


def _get_default_executor() -> BlockingExecutor:
    """Return (and lazily create) the module-level default executor."""
    global _default_executor
    if _default_executor is None or not _default_executor.is_running():
        max_threads = int(os.environ.get("HYPERN_BLOCKING_THREADS", "0"))
        _default_executor = BlockingExecutor(max_threads=max_threads)
    return _default_executor


def set_default_executor(executor: BlockingExecutor) -> None:
    """
    Replace the module-level default executor.

    Call this early in your application startup if you need custom pool sizing.

    Args:
        executor: A :class:`BlockingExecutor` instance.
    """
    global _default_executor
    _default_executor = executor


def get_default_executor() -> BlockingExecutor:
    """
    Return the current module-level default executor, creating one if needed.

    The auto-created executor uses ``HYPERN_BLOCKING_THREADS`` env-var
    (default: CPU count) for pool size.
    """
    return _get_default_executor()


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------


def blocking_run(callable: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """
    Run *callable* on a Rust thread with the GIL released while waiting.

    This is a shortcut for ``get_default_executor().run_sync(callable, ...)``.

    Args:
        callable: Any Python callable.
        *args:    Positional arguments forwarded to *callable*.
        **kwargs: Keyword arguments forwarded to *callable*.

    Returns:
        The return value of ``callable(*args, **kwargs)``.
    """
    return _get_default_executor().run_sync(callable, *args, **kwargs)


def blocking_map(
    callable: Callable[[Any], T],
    items: List[Any],
    *,
    chunk_size: int = 0,
    executor: Optional[BlockingExecutor] = None,
) -> List[T]:
    """
    Map *callable* over *items* in parallel on Rust threads.

    This is a shortcut for ``executor.map(callable, items, chunk_size)``.

    Args:
        callable:   Function taking a single item.
        items:      List of items.
        chunk_size: Items per work unit. 0 = auto-tune.
        executor:   Optional executor; uses the default if omitted.

    Returns:
        List of results, same order as *items*.
    """
    ex = executor or _get_default_executor()
    return ex.map(callable, items, chunk_size)


def blocking_parallel(
    tasks: List[tuple],
    *,
    executor: Optional[BlockingExecutor] = None,
) -> List[Any]:
    """
    Run heterogeneous tasks in parallel on Rust threads.

    Each element is ``(callable, args)`` or ``(callable, args, kwargs_dict)``.

    Args:
        tasks:    List of task tuples.
        executor: Optional executor; uses the default if omitted.

    Returns:
        List of results, same order as input.
    """
    ex = executor or _get_default_executor()
    return ex.run_parallel(tasks)


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def blocking(fn: Optional[Callable] = None, *, executor: Optional[BlockingExecutor] = None):
    """
    Decorator that offloads a function to a Rust blocking thread.

    The decorated function, when called, will execute on a Rust OS thread
    with the calling thread's GIL released. The caller blocks (GIL-free)
    until the result is available.

    Can be used with or without arguments::

        @blocking
        def heavy(x):
            return x ** 2

        @blocking(executor=my_pool)
        def heavy(x):
            return x ** 2

    Args:
        fn:       The function to wrap (when used without parentheses).
        executor: Optional :class:`BlockingExecutor`; uses the default if omitted.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            ex = executor or _get_default_executor()
            return ex.run_sync(func, *args, **kwargs)

        # Attach metadata so introspection tools can detect it.
        wrapper.__blocking__ = True  # type: ignore[attr-defined]
        wrapper.__wrapped_executor__ = executor  # type: ignore[attr-defined]
        return wrapper

    if fn is not None:
        # Used as @blocking without parentheses.
        return decorator(fn)
    # Used as @blocking(...) with parentheses.
    return decorator


__all__ = [
    "BlockingExecutor",
    "blocking",
    "blocking_map",
    "blocking_parallel",
    "blocking_run",
    "get_default_executor",
    "set_default_executor",
]
