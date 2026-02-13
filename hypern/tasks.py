from __future__ import annotations

import functools
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from hypern._hypern import TaskExecutor, TaskResult

# Global task executor instance (will be set by the Hypern app)
_task_executor: Optional['TaskExecutor'] = None


def set_task_executor(executor: 'TaskExecutor') -> None:
    """
    Set the global task executor.
    
    This is typically called automatically by the Hypern application instance.
    You don't need to call this manually unless you have a custom setup.
    
    Args:
        executor: The TaskExecutor instance to use globally
    """
    global _task_executor
    _task_executor = executor


def get_task_executor() -> Optional['TaskExecutor']:
    """
    Get the global task executor.
    
    Returns:
        The global TaskExecutor instance, or None if not initialized
    """
    return _task_executor


def background(
    delay_seconds: Optional[float] = None
) -> Callable:
    """
    Decorator to run a function as a background task.
    
    This can be used in any module without importing the app instance,
    avoiding circular import issues in large applications.
    
    Args:
        delay_seconds: Optional delay in seconds before executing the task
    
    Example:
        # In services/email_service.py
        from hypern import background
        
        @background()  # Execute immediately
        def send_email(to: str, subject: str, body: str):
            import smtplib
            # Send email logic...
            print(f"Email sent to {to}")
        
        @background(delay_seconds=60)  # Execute after 60 seconds
        def send_reminder(to: str):
            print(f"Reminder sent to {to}")
        
        # In routes/user_routes.py
        from services.email_service import send_email
        
        @router.post("/users")
        def create_user(req, res, ctx):
            user = create_user_in_db(req.json())
            # This will run in background, no circular import!
            send_email(user["email"], "Welcome!", "Thanks for signing up")
            res.status(201).json(user)
    """
    def decorator(handler: Callable) -> Callable:
        @functools.wraps(handler)
        def wrapped(*args, **kwargs):
            executor = get_task_executor()
            if executor is not None:
                # Submit task to the global executor
                return executor.submit(handler, args, delay_seconds)
            else:
                # Fallback: run synchronously if no executor is available
                # This allows functions to still work even if called before app initialization
                return handler(*args, **kwargs)
        return wrapped
    return decorator


def submit_task(
    handler: Callable, 
    args: tuple = (),
    delay_seconds: Optional[float] = None
) -> Optional[str]:
    """
    Submit a background task programmatically.
    
    This can be used in any module without importing the app instance,
    avoiding circular import issues in large applications.
    
    Args:
        handler: The function to run in the background
        args: Arguments to pass to the function
        delay_seconds: Optional delay in seconds before executing the task
    
    Returns:
        task_id: The ID of the submitted task, or None if no executor available
    
    Example:
        # In services/report_service.py
        from hypern import submit_task
        
        def generate_report(user_id: str, report_type: str):
            # Heavy computation
            data = fetch_report_data(report_type)
            pdf = render_to_pdf(data)
            return save_report(pdf, user_id)
        
        # In routes/report_routes.py
        from services.report_service import generate_report
        
        @router.post("/reports")
        def request_report(req, res, ctx):
            data = req.json()
            # Submit task without importing app
            task_id = submit_task(
                generate_report,
                args=(ctx.get("user_id"), data["type"]),
                delay_seconds=300  # Execute after 5 minutes
            )
            res.json({"task_id": task_id})
    """
    executor = get_task_executor()
    if executor is not None:
        return executor.submit(handler, args, delay_seconds)
    return None


def get_task(task_id: str) -> Optional['TaskResult']:
    """
    Get the result of a background task.
    
    This can be used in any module without importing the app instance.
    
    Args:
        task_id: The ID of the task to retrieve
    
    Returns:
        TaskResult object with status and result/error, or None if not found
    
    Example:
        # In any module
        from hypern import get_task
        
        def check_task_status(task_id: str):
            result = get_task(task_id)
            if result:
                if result.is_success():
                    return {"status": "completed", "data": result.result}
                elif result.is_failed():
                    return {"status": "failed", "error": result.error}
                else:
                    return {"status": result.status.name}
            return {"status": "not_found"}
    """
    executor = get_task_executor()
    if executor is not None:
        return executor.get_result(task_id)
    return None


__all__ = [
    'background',
    'submit_task',
    'get_task',
    'get_task_executor',
    'set_task_executor',
]
