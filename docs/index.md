# Hypern

<div align="center">
  <h2>⚡ A Versatile Python and Rust Framework</h2>
  <p>Build high-performance web applications with the simplicity of Python and the speed of Rust</p>
</div>

---

## Overview

**Hypern** is a flexible, open-source framework built on [Rust](https://github.com/rust-lang/rust), designed to jumpstart your high-performance web development endeavors. By providing a pre-configured structure and essential components, Hypern empowers you to rapidly develop custom web applications that leverage the combined power of Python and Rust.

With Hypern, you can seamlessly integrate asynchronous features and build scalable solutions for RESTful APIs and dynamic web applications. Its intuitive design and robust tooling allow developers to focus on creating high-quality code while maximizing performance.

## 🚀 Quick Start

```python
# main.py
from hypern import Hypern, Request, Response

def hello_handler(request: Request, response: Response):
    response.status(200)
    response.header("Content-Type", "application/json")
    response.body_str('{"message": "Hello, World!"}')
    response.finish()

app = Hypern()
app.add_route("GET", "/hello", hello_handler)

if __name__ == "__main__":
    app.start()
```

Run your application:

```bash
python main.py
```

Visit `http://localhost:5000/hello` to see your API in action!

## 💡 Key Features

### ⚡ High Performance
- **Rust-powered core** with Python flexibility
- **Multi-process architecture** for optimal CPU utilization
- **Async/await support** for non-blocking operations
- Built on production-ready Rust language

### 🛠 Developer Experience
- Type hints and full IDE support
- Built-in Swagger/OpenAPI documentation at `/docs`
- Hot reload during development
- Comprehensive error handling and logging

### 🔌 Integration & Extensions
- Easy dependency injection
- Middleware support (before/after request hooks)
- WebSocket support
- Background task scheduling
- File upload handling

### 🔒 Security
- Built-in authentication/authorization (Coming soon)
- CORS configuration
- Rate limiting
- Request validation

## 📦 Installation

Install Hypern using pip:

```bash
pip install hypern
```

For development, see our [Installation Guide](getting-started/installation.md).

## 🎯 Why Hypern?

| Feature | Hypern | Traditional Python Frameworks |
|---------|--------|-------------------------------|
| **Performance** | Rust-powered, highly optimized | Pure Python, slower |
| **Concurrency** | Multi-process + async/await | Limited by GIL |
| **Memory Usage** | Efficient memory management | Higher overhead |
| **Type Safety** | Full type hints support | Optional |
| **Learning Curve** | Familiar Python API | Varies |

## 📚 Documentation Structure

- **[Getting Started](getting-started/installation.md)** - Installation, setup, and basic concepts
- **[User Guide](guide/application.md)** - Comprehensive guides for building applications
- **[Advanced Topics](advanced/performance.md)** - Performance tuning, WebSockets, and more
- **[API Reference](api/core/hypern.md)** - Complete API documentation
- **[Architecture](architecture/overview.md)** - Deep dive into Hypern's design
- **[Examples](examples/basic-api.md)** - Real-world examples and use cases

## 🌟 Community & Support

- **GitHub**: [github.com/martindang/hypern](https://github.com/martindang/hypern)
- **PyPI**: [pypi.org/project/hypern](https://pypi.org/project/hypern/)
- **Issues**: Report bugs and request features on [GitHub Issues](https://github.com/martindang/hypern/issues)

## 🤝 Contributing

We welcome contributions! See our [Contributing Guide](contributing/guidelines.md) to get started.

## 📄 License

Hypern is released under the MIT License. See the [LICENSE](https://github.com/martindang/hypern/blob/main/LICENSE) file for details.

---

<div align="center">
  <p>Built with ❤️ by the Hypern community</p>
</div>