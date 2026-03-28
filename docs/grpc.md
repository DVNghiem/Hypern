# gRPC

Hypern provides gRPC support backed by Rust (`tonic` / `prost`) for high-performance protobuf-based microservice communication.

## Quick Start

```python
from hypern.grpc import GrpcConfig, GrpcServer, GrpcRoute, grpc_method

class GreeterService(GrpcRoute):
    @grpc_method("greet.Greeter", "SayHello")
    async def say_hello(self, data: bytes) -> bytes:
        # Decode protobuf request, process, return protobuf response
        return response_bytes

server = GrpcServer(GrpcConfig(host="0.0.0.0", port=50051))
```

## API Reference

### GrpcConfig

```python
GrpcConfig(host="0.0.0.0", port=50051)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `host` | `str` | `"0.0.0.0"` | Host to bind |
| `port` | `int` | `50051` | Port to listen on |

### GrpcServer

```python
GrpcServer(config=None)
```

| Method | Description |
|--------|-------------|
| `address()` | Get the configured address string |
| `is_running()` | Check if the server is running |

### GrpcRoute

Base class for gRPC service implementations. Decorate methods with `@grpc_method` to register them as handlers.

```python
class MyService(GrpcRoute):
    @grpc_method("package.Service", "MethodName")
    async def handler(self, data: bytes) -> bytes:
        ...
```

### grpc_method decorator

```python
@grpc_method(service, method)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `service` | `str` | Fully qualified gRPC service name |
| `method` | `str` | Method name |

## Architecture

The gRPC server runs alongside your HTTP server on a separate port:

- **HTTP server**: `:3000` (default) — REST, GraphQL, WebSocket
- **gRPC server**: `:50051` (default) — Protobuf/gRPC

This allows you to serve both HTTP and gRPC clients from the same application.
