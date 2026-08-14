"""Regression tests for background task invocation."""

import time

from hypern import Hypern
from hypern._hypern import TaskResult


def _wait_for_task(app: Hypern, task_id: str) -> TaskResult | None:
    for _ in range(100):
        task = app.get_task(task_id)
        if task is not None and not task.is_pending():
            return task
        time.sleep(0.01)
    return app.get_task(task_id)


def test_background_preserves_positional_and_keyword_arguments():
    """The decorator passes calls through without nesting or dropping values."""
    app = Hypern(task_workers=1)

    @app.background()
    def format_message(prefix: str, message: str, *, suffix: str) -> str:
        return f"{prefix}: {message}{suffix}"

    task_id = format_message("status", "ready", suffix="!")
    task = _wait_for_task(app, task_id)

    assert task is not None
    assert task.is_success()
    assert task.result == "status: ready!"


def test_background_delay_is_measured_in_seconds():
    """The decorator does not run a delayed task before its seconds deadline."""
    app = Hypern(task_workers=1)

    @app.background(delay_seconds=0.2)
    def finish() -> str:
        return "done"

    task_id = finish()
    time.sleep(0.05)
    task = app.get_task(task_id)

    assert task is not None
    assert task.is_pending()
