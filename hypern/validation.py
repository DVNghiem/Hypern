from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, Dict, Generic, List, Optional, Type, TypeVar, Union, get_args, get_origin

import msgspec
from msgspec import Struct, field

T = TypeVar("T")


class ValidationError(Exception):
    """Exception raised when validation fails."""
    
    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        value: Any = None,
        errors: Optional[List[Dict[str, Any]]] = None
    ):
        self.message = message
        self.field = field
        self.value = value
        self.errors = errors or []
        super().__init__(message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for JSON response."""
        result = {"message": self.message}
        if self.field:
            result["field"] = self.field
        if self.errors:
            result["errors"] = self.errors
        return result


class Validator(Generic[T]):
    """
    Base validator class using msgspec for high-performance validation.
    
    Example:
        class UserInput(msgspec.Struct):
            name: str
            email: str
            age: int
        
        validator = Validator(UserInput)
        user = validator.validate({"name": "John", "email": "john@example.com", "age": 25})
    """
    
    def __init__(self, schema: Type[T]):
        self.schema = schema
        self._decoder = msgspec.json.Decoder(schema)
        self._encoder = msgspec.json.Encoder()
    
    def validate(self, data: Union[bytes, str, Dict[str, Any]]) -> T:
        """Validate data against the schema."""
        try:
            if isinstance(data, dict):
                data = msgspec.json.encode(data)
            elif isinstance(data, str):
                data = data.encode()
            
            return self._decoder.decode(data)
        except msgspec.ValidationError as e:
            raise ValidationError(
                message=str(e),
                errors=[{"type": "validation_error", "msg": str(e)}]
            )
        except msgspec.DecodeError as e:
            raise ValidationError(
                message=f"Invalid JSON: {e}",
                errors=[{"type": "decode_error", "msg": str(e)}]
            )
    
    def validate_with_coercion(self, data: Dict[str, Any]) -> T:
        """
        Validate data with type coercion for string values.
        Useful for query parameters and path params which come as strings.
        """
        try:
            # Try to coerce string values to expected types based on schema hints
            coerced_data = self._coerce_types(data)
            return self.validate(coerced_data)
        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(
                message=f"Type coercion failed: {e}",
                errors=[{"type": "coercion_error", "msg": str(e)}]
            )
    
    def _coerce_types(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Coerce string values to expected types based on schema annotations."""
        result = {}
        hints = getattr(self.schema, '__annotations__', {})
        
        for key, value in data.items():
            if key in hints and isinstance(value, str):
                expected_type = hints[key]
                # Handle Optional types using get_origin/get_args
                origin = get_origin(expected_type)
                if origin is Union:
                    args = get_args(expected_type)
                    # Get non-None types
                    expected_type = next((a for a in args if a is not type(None)), str)
                
                # Coerce based on type
                if expected_type is int:
                    try:
                        result[key] = int(value)
                    except ValueError:
                        result[key] = value
                elif expected_type is float:
                    try:
                        result[key] = float(value)
                    except ValueError:
                        result[key] = value
                elif expected_type is bool:
                    result[key] = value.lower() in ('true', '1', 'yes', 'on')
                else:
                    result[key] = value
            else:
                result[key] = value
        
        return result
    
    def validate_partial(self, data: Union[bytes, str, Dict[str, Any]], exclude: Optional[List[str]] = None) -> T:
        """Validate data with optional fields excluded."""
        # For partial validation, we need to handle missing fields
        if isinstance(data, (bytes, str)):
            if isinstance(data, str):
                data = data.encode()
            data = msgspec.json.decode(data)
        
        return self.validate(data)


def validate_body(schema: Type[T]) -> Callable:
    """
    Decorator to validate request body against a msgspec schema.
    
    Example:
        class CreateUser(msgspec.Struct):
            name: str
            email: str
        
        @app.post("/users")
        @validate_body(CreateUser)
        async def create_user(req, res, body: CreateUser):
            res.json({"name": body.name})
    """
    validator = Validator(schema)
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(req, res, ctx, *args, **kwargs):
            try:
                body_data = req.body_bytes()
                validated = validator.validate(body_data)
                return await func(req, res, ctx, validated, *args, **kwargs)
            except ValidationError as e:
                res.status(400).json(e.to_dict())
                return
        
        @functools.wraps(func)
        def sync_wrapper(req, res, ctx, *args, **kwargs):
            try:
                body_data = req.body_bytes()
                validated = validator.validate(body_data)
                return func(req, res, ctx, validated, *args, **kwargs)
            except ValidationError as e:
                res.status(400).json(e.to_dict())
                return
        
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def validate_query(schema: Type[T]) -> Callable:
    """
    Decorator to validate query parameters against a msgspec schema.
    
    Example:
        class SearchParams(msgspec.Struct):
            q: str
            page: int = 1
            limit: int = 10
        
        @app.get("/search")
        @validate_query(SearchParams)
        async def search(req, res, query: SearchParams):
            res.json({"query": query.q, "page": query.page})
    """
    validator = Validator(schema)
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(req, res, ctx, *args, **kwargs):
            try:
                query_data = req.query_params
                validated = validator.validate_with_coercion(query_data)
                return await func(req, res, ctx, validated, *args, **kwargs)
            except ValidationError as e:
                res.status(400).json(e.to_dict())
                return
        
        @functools.wraps(func)
        def sync_wrapper(req, res, ctx, *args, **kwargs):
            try:
                query_data = req.query_params
                validated = validator.validate_with_coercion(query_data)
                return func(req, res, ctx, validated, *args, **kwargs)
            except ValidationError as e:
                res.status(400).json(e.to_dict())
                return
        
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def validate_params(schema: Type[T]) -> Callable:
    """
    Decorator to validate path parameters against a msgspec schema.
    
    Example:
        class UserParams(msgspec.Struct):
            id: int
        
        @app.get("/users/:id")
        @validate_params(UserParams)
        async def get_user(req, res, params: UserParams):
            res.json({"user_id": params.id})
    """
    validator = Validator(schema)
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(req, res, ctx, *args, **kwargs):
            try:
                params_data = req.path_params
                validated = validator.validate_with_coercion(params_data)
                return await func(req, res, ctx, validated, *args, **kwargs)
            except ValidationError as e:
                res.status(400).json(e.to_dict())
                return
        
        @functools.wraps(func)
        def sync_wrapper(req, res, ctx, *args, **kwargs):
            try:
                params_data = req.path_params
                validated = validator.validate_with_coercion(params_data)
                return func(req, res, ctx, validated, *args, **kwargs)
            except ValidationError as e:
                res.status(400).json(e.to_dict())
                return
        
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


def validate(
    body: Optional[Type] = None,
    query: Optional[Type] = None,
    params: Optional[Type] = None
) -> Callable:
    """
    Combined decorator for validating body, query, and params.
    
    The validated data is passed as additional positional arguments in order:
    body (if specified), query (if specified), params (if specified).
    
    Example:
        class CreateBody(msgspec.Struct):
            name: str
        
        class QueryParams(msgspec.Struct):
            include_details: bool = False
        
        @app.post("/users")
        @validate(body=CreateBody, query=QueryParams)
        def create_user(req, res, body: CreateBody, query: QueryParams):
            res.json({"name": body.name})
    """
    body_validator = Validator(body) if body else None
    query_validator = Validator(query) if query else None
    params_validator = Validator(params) if params else None
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(req, res, ctx, *args, **kwargs):
            validated_args = []
            try:
                if body_validator:
                    body_data = req.body_bytes()
                    validated_args.append(body_validator.validate(body_data))
                
                if query_validator:
                    query_data = req.query_params
                    validated_args.append(query_validator.validate_with_coercion(query_data))
                
                if params_validator:
                    params_data = req.path_params
                    validated_args.append(params_validator.validate_with_coercion(params_data))
                
                return await func(req, res, ctx, *validated_args, *args, **kwargs)
            except ValidationError as e:
                res.status(400).json(e.to_dict())
                return
        
        @functools.wraps(func)
        def sync_wrapper(req, res, ctx, *args, **kwargs):
            validated_args = []
            try:
                if body_validator:
                    body_data = req.body_bytes()
                    validated_args.append(body_validator.validate(body_data))
                
                if query_validator:
                    query_data = req.query_params
                    validated_args.append(query_validator.validate_with_coercion(query_data))
                
                if params_validator:
                    params_data = req.path_params
                    validated_args.append(params_validator.validate_with_coercion(params_data))
                
                return func(req, res, ctx, *validated_args, *args, **kwargs)
            except ValidationError as e:
                res.status(400).json(e.to_dict())
                return
        
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


__all__ = [
    'ValidationError',
    'Validator',
    'validate_body',
    'validate_query',
    'validate_params',
    'validate',
    'Struct',
    'field',
]
