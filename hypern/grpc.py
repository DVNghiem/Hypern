"""gRPC support for Hypern.

Provides a lightweight gRPC endpoint integration backed by Rust (tonic/prost).

Example::

    from hypern.grpc import GrpcRoute, grpc_method, GrpcConfig

    class GreeterService:
        @grpc_method("greet.Greeter", "SayHello")
        async def say_hello(self, request_data: bytes) -> bytes:
            # Decode protobuf request, build response
            return response_bytes

    app.setup_grpc(GrpcConfig(port=50051))
    app.mount_grpc("/greet.Greeter", GreeterService())
"""

from __future__ import annotations

from typing import Callable, Dict

from hypern._hypern import GrpcConfig, GrpcServer


def grpc_method(service: str, method: str) -> Callable:
    """Decorator to mark a method as a gRPC handler.

    Args:
        service: Fully qualified gRPC service name (e.g. ``"greet.Greeter"``).
        method: Method name (e.g. ``"SayHello"``).
    """

    def decorator(func: Callable) -> Callable:
        func._grpc_service = service
        func._grpc_method = method
        return func

    return decorator


class GrpcRoute:
    """A collection of gRPC method handlers for a service.

    Subclass and decorate methods with ``@grpc_method`` to define handlers::

        class Greeter(GrpcRoute):
            @grpc_method("greet.Greeter", "SayHello")
            async def say_hello(self, data: bytes) -> bytes:
                return b"Hello!"
    """

    def get_methods(self) -> Dict[str, Callable]:
        """Return a mapping of ``"service/method"`` to handler callables."""
        methods: Dict[str, Callable] = {}
        for attr_name in dir(self):
            attr = getattr(self, attr_name, None)
            if callable(attr) and hasattr(attr, "_grpc_service"):
                key = f"{attr._grpc_service}/{attr._grpc_method}"
                methods[key] = attr
        return methods


__all__ = [
    "GrpcConfig",
    "GrpcServer",
    "GrpcRoute",
    "grpc_method",
]
