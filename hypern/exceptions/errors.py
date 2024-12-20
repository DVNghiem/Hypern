from .base import HypernError


class ErrorDefinitions:
    """Standard error definitions"""

    BAD_REQUEST = HypernError(message="Bad request", code="BAD_REQUEST")
    UNAUTHORIZED = HypernError(message="Unauthorized access", code="UNAUTHORIZED")
    FORBIDDEN = HypernError(message="Access forbidden", code="FORBIDDEN")
    NOT_FOUND = HypernError(message="Resource not found", code="NOT_FOUND")
    METHOD_NOT_ALLOWED = HypernError(message="Method not allowed", code="METHOD_NOT_ALLOWED")
    VALIDATION_ERROR = HypernError(message="Validation error", code="VALIDATION_ERROR")
    INTERNAL_ERROR = HypernError(message="Internal server error", code="INTERNAL_SERVER_ERROR")
    CONFLICT = HypernError(message="Resource conflict", code="CONFLICT")
    TOO_MANY_REQUESTS = HypernError(message="Too many requests", code="TOO_MANY_REQUESTS")
