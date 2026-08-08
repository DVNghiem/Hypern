from __future__ import annotations

from collections.abc import Callable
from typing import Any

import msgspec


class ValidationError(msgspec.ValidationError):
    """Request-binding error with a stable JSON response representation."""

    def __init__(
        self,
        message: str,
        field: str | None = None,
        value: Any = None,
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        self.message = message
        self.field = field
        self.value = value
        self.errors = errors or []
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        """Return the public JSON response payload for this error."""
        result: dict[str, Any] = {"message": self.message}
        if self.field:
            result["field"] = self.field
        if self.errors:
            result["errors"] = self.errors
        return result


def _decode_json(decoder: msgspec.json.Decoder, data: bytes) -> Any:
    """Decode request JSON and normalize msgspec failures for HTTP handling."""
    try:
        return decoder.decode(data)
    except msgspec.DecodeError as error:
        error_type = (
            "validation_error"
            if isinstance(error, msgspec.ValidationError)
            else "decode_error"
        )
        raise ValidationError(
            message=str(error),
            errors=[{"type": error_type, "msg": str(error)}],
        ) from error


def _convert_value(converter: Callable[[Any], Any], value: Any) -> Any:
    """Convert one request value and normalize msgspec validation failures."""
    try:
        return converter(value)
    except msgspec.ValidationError as error:
        raise ValidationError(
            message=str(error),
            errors=[{"type": "validation_error", "msg": str(error)}],
        ) from error


__all__ = ["ValidationError"]
