from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Type
import orjson


class HTTPException(Exception):
    """
    Base HTTP exception class.
    
    Example:
        raise HTTPException(404, "User not found")
        raise HTTPException(400, "Invalid input", {"field": "email", "error": "Invalid format"})
    """
    
    def __init__(
        self,
        status_code: int = 500,
        detail: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ):
        self.status_code = status_code
        self.detail = detail or self.get_default_detail(status_code)
        self.data = data or {}
        self.headers = headers or {}
        super().__init__(self.detail)
    
    @staticmethod
    def get_default_detail(status_code: int) -> str:
        """Get default detail message for status code."""
        messages = {
            400: "Bad Request",
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not Found",
            405: "Method Not Allowed",
            406: "Not Acceptable",
            408: "Request Timeout",
            409: "Conflict",
            410: "Gone",
            413: "Payload Too Large",
            415: "Unsupported Media Type",
            422: "Unprocessable Entity",
            429: "Too Many Requests",
            500: "Internal Server Error",
            501: "Not Implemented",
            502: "Bad Gateway",
            503: "Service Unavailable",
            504: "Gateway Timeout",
        }
        return messages.get(status_code, "Error")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for JSON response."""
        result = {
            "error": True,
            "status_code": self.status_code,
            "message": self.detail,
        }
        if self.data:
            result["data"] = self.data
        return result
    
    def to_json(self) -> str:
        """Convert exception to JSON string."""
        return orjson.dumps(self.to_dict())


# Convenience exception classes
class BadRequest(HTTPException):
    """400 Bad Request"""
    def __init__(self, detail: str = "Bad Request", data: Optional[Dict] = None, headers: Optional[Dict] = None):
        super().__init__(400, detail, data, headers)


class Unauthorized(HTTPException):
    """401 Unauthorized"""
    def __init__(self, detail: str = "Unauthorized", data: Optional[Dict] = None, headers: Optional[Dict] = None):
        super().__init__(401, detail, data, headers)


class Forbidden(HTTPException):
    """403 Forbidden"""
    def __init__(self, detail: str = "Forbidden", data: Optional[Dict] = None, headers: Optional[Dict] = None):
        super().__init__(403, detail, data, headers)


class NotFound(HTTPException):
    """404 Not Found"""
    def __init__(self, detail: str = "Not Found", data: Optional[Dict] = None, headers: Optional[Dict] = None):
        super().__init__(404, detail, data, headers)


class MethodNotAllowed(HTTPException):
    """405 Method Not Allowed"""
    def __init__(self, detail: str = "Method Not Allowed", data: Optional[Dict] = None, headers: Optional[Dict] = None):
        super().__init__(405, detail, data, headers)


class Conflict(HTTPException):
    """409 Conflict"""
    def __init__(self, detail: str = "Conflict", data: Optional[Dict] = None, headers: Optional[Dict] = None):
        super().__init__(409, detail, data, headers)


class UnprocessableEntity(HTTPException):
    """422 Unprocessable Entity"""
    def __init__(self, detail: str = "Unprocessable Entity", data: Optional[Dict] = None, headers: Optional[Dict] = None):
        super().__init__(422, detail, data, headers)


class TooManyRequests(HTTPException):
    """429 Too Many Requests"""
    def __init__(self, detail: str = "Too Many Requests", data: Optional[Dict] = None, headers: Optional[Dict] = None):
        super().__init__(429, detail, data, headers)


class InternalServerError(HTTPException):
    """500 Internal Server Error"""
    def __init__(self, detail: str = "Internal Server Error", data: Optional[Dict] = None, headers: Optional[Dict] = None):
        super().__init__(500, detail, data, headers)


class ServiceUnavailable(HTTPException):
    """503 Service Unavailable"""
    def __init__(self, detail: str = "Service Unavailable", data: Optional[Dict] = None, headers: Optional[Dict] = None):
        super().__init__(503, detail, data, headers)


class ExceptionHandler:
    """
    Exception handler registry for the application.
    
    Example:
        handler = ExceptionHandler()
        
        @handler.handle(NotFound)
        def handle_not_found(req, res, exc):
            res.status(404).json({"error": "Resource not found"})
        
        @handler.handle(Exception)
        def handle_all(req, res, exc):
            res.status(500).json({"error": "Something went wrong"})
    """
    
    def __init__(self):
        self._handlers: Dict[Type[Exception], Callable] = {}
        self._default_handler: Optional[Callable] = None
    
    def handle(self, exc_class: Type[Exception]) -> Callable:
        """Decorator to register an exception handler."""
        def decorator(func: Callable) -> Callable:
            self._handlers[exc_class] = func
            return func
        return decorator
    
    def add_handler(self, exc_class: Type[Exception], handler: Callable) -> None:
        """Add an exception handler programmatically."""
        self._handlers[exc_class] = handler
    
    def set_default_handler(self, handler: Callable) -> None:
        """Set the default handler for unhandled exceptions."""
        self._default_handler = handler
    
    def get_handler(self, exc: Exception) -> Optional[Callable]:
        """Get the handler for an exception type."""
        # First, try to find exact match
        exc_type = type(exc)
        if exc_type in self._handlers:
            return self._handlers[exc_type]
        
        # Then, try to find handler for parent classes
        for handler_type, handler in self._handlers.items():
            if isinstance(exc, handler_type):
                return handler
        
        return self._default_handler
    
    async def handle_exception(self, req, res, exc: Exception) -> None:
        """Handle an exception using registered handlers."""
        handler = self.get_handler(exc)
        
        if handler:
            import inspect
            if inspect.iscoroutinefunction(handler):
                await handler(req, res, exc)
            else:
                handler(req, res, exc)
        else:
            # Default behavior for unhandled exceptions
            self._default_exception_response(req, res, exc)
    
    def _default_exception_response(self, req, res, exc: Exception) -> None:
        """Default exception response."""
        if isinstance(exc, HTTPException):
            for key, value in exc.headers.items():
                res.header(key, value)
            res.status(exc.status_code).json(exc.to_dict())
        else:
            # Generic error response
            res.status(500).json({
                "error": True,
                "status_code": 500,
                "message": "Internal Server Error",
                "detail": str(exc) if __debug__ else None
            })


def exception_handler(exc_class: Type[Exception]):
    """
    Decorator to mark a function as an exception handler.
    Used with application's exception handling system.
    
    Example:
        @exception_handler(NotFound)
        def handle_not_found(req, res, exc):
            res.status(404).json({"error": "Not found"})
    """
    def decorator(func: Callable) -> Callable:
        func._exception_class = exc_class
        return func
    return decorator


def error_boundary(handler: Optional[Callable] = None):
    """
    Decorator to wrap a route handler with error handling.
    
    Example:
        @app.get("/users/:id")
        @error_boundary()
        async def get_user(req, res):
            user = await fetch_user(req.param("id"))
            if not user:
                raise NotFound("User not found")
            res.json(user)
    """
    def decorator(func: Callable) -> Callable:
        import functools
        import inspect
        
        @functools.wraps(func)
        async def async_wrapper(req, res, *args, **kwargs):
            try:
                return await func(req, res, *args, **kwargs)
            except HTTPException as e:
                for key, value in e.headers.items():
                    res.header(key, value)
                res.status(e.status_code).json(e.to_dict())
            except Exception as e:
                if handler:
                    if inspect.iscoroutinefunction(handler):
                        await handler(req, res, e)
                    else:
                        handler(req, res, e)
                else:
                    res.status(500).json({
                        "error": True,
                        "message": "Internal Server Error"
                    })
        
        @functools.wraps(func)
        def sync_wrapper(req, res, *args, **kwargs):
            try:
                return func(req, res, *args, **kwargs)
            except HTTPException as e:
                for key, value in e.headers.items():
                    res.header(key, value)
                res.status(e.status_code).json(e.to_dict())
            except Exception as e:
                if handler:
                    handler(req, res, e)
                else:
                    res.status(500).json({
                        "error": True,
                        "message": "Internal Server Error"
                    })
        
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


__all__ = [
    'HTTPException',
    'BadRequest',
    'Unauthorized',
    'Forbidden',
    'NotFound',
    'MethodNotAllowed',
    'Conflict',
    'UnprocessableEntity',
    'TooManyRequests',
    'InternalServerError',
    'ServiceUnavailable',
    'ExceptionHandler',
    'exception_handler',
    'error_boundary',
]
