# Hypern Documentation

Welcome to the Hypern documentation! Hypern is an Express.js-style Python web framework powered by Rust (Axum/Tokio) for maximum performance.

## Quick Start

```python
from hypern import Hypern

app = Hypern()

@app.get("/")
def home(req, res, ctx):
    res.json({"message": "Hello, World!"})

if __name__ == "__main__":
    app.start(host="0.0.0.0", port=8000)
```

## Documentation

| Topic | Description |
|-------|-------------|
| [Getting Started](getting-started.md) | Installation and basic setup |
| [Routing](routing.md) | Route definitions, parameters, and router groups |
| [Request & Response](request-response.md) | Request handling and response methods |
| [Middleware](middleware.md) | Built-in and custom middleware |
| [SSE & Streaming](sse.md) | Server-Sent Events and streaming responses |
| [Validation](validation.md) | Request validation and schema definition |
| [Dependency Injection](dependency-injection.md) | DI container and service registration |
| [Background Tasks](tasks.md) | Background job processing |
| [Error Handling](error-handling.md) | Exception handling and error responses |
| [File Uploads](file-uploads.md) | Multipart file handling |
| [Database](database.md) | Database operations and connection pooling |
| [Best Practices](best-practices.md) | Performance tips and patterns |
| [User Guide](user-guide.md) | Comprehensive user guide |

## Performance Features

Hypern achieves high performance through:

- **Rust Core**: The HTTP server, routing, and middleware chain are implemented in Rust using Axum/Tokio
- **Pure Rust JSON**: JSON serialization/deserialization using SIMD-optimized parsers
- **Zero-Copy Parsing**: Request parsing with minimal memory allocations
- **Thread-Local Arenas**: Memory arena allocation for request-scoped allocations
- **Rust Middleware**: High-performance middleware (CORS, Rate Limiting, etc.) in pure Rust

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Python Application                        │
│  (Route handlers, Business logic, Middleware callbacks)      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    PyO3 Bindings                             │
│  (Request/Response objects, Context, SSE, Tasks)             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Rust Core (Axum/Tokio)                    │
│  - HTTP Server       - Middleware Chain    - JSON Parser     │
│  - Radix Router      - Memory Pools        - SSE Streaming   │
│  - Connection Pool   - Arena Allocator     - Task Executor   │
└─────────────────────────────────────────────────────────────┘
```

## License

MIT License
