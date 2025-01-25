import asyncio
from functools import wraps
from typing import Any, Callable, List, Optional

from hypern.hypern import Request, Response
from hypern.response import JSONResponse


def requires_auth(roles: Optional[List[str]] = None):
    """
    A decorator to enforce authentication and authorization on an endpoint.

    Args:
        roles (Optional[List[str]]): A list of roles that are allowed to access the endpoint. If None, any authenticated user can access.

    Returns:
        Callable: The decorated function with authentication and authorization checks.

    The decorator checks if the request has an 'auth' attribute. If not, it returns a 401 Unauthorized response.
    If roles are specified, it checks if the user's role is in the allowed roles. If not, it returns a 403 Forbidden response.
    If the function being decorated is a coroutine, it awaits the function call.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(self, request: Request, *args: Any, **kwargs: Any) -> Response:
            request.auth = {}
            if not hasattr(request, "auth"):
                return JSONResponse({"error": "Authentication required"}, status_code=401)

            if roles and "role" in request.auth:
                if request.auth["role"] not in roles:
                    return JSONResponse({"error": "Insufficient permissions"}, status_code=403)
            # check function is awaitable
            if asyncio.iscoroutinefunction(func):
                return await func(self, request, *args, **kwargs)
            return func(self, request, *args, **kwargs)

        return wrapper

    return decorator
