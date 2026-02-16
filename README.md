
# Hypern

Hypern: A Versatile Python and Rust Framework

Hypern is a flexible, open-source framework built on the [Rust](https://github.com/rust-lang/rust), designed to jumpstart your high-performance web development endeavors. By providing a pre-configured structure and essential components, Hypern empowers you to rapidly develop custom web applications that leverage the combined power of Python and Rust.

With Hypern, you can seamlessly integrate asynchronous features and build scalable solutions for RESTful APIs and dynamic web applications. Its intuitive design and robust tooling allow developers to focus on creating high-quality code while maximizing performance. Embrace the synergy of Python and Rust to elevate your web development experience.


### 🏁 Get started

### ⚙️ To Develop Locally

- Setup a virtual environment:
```
python3 -m venv venv
source venv/bin/activate
```
- Install required packages

```
pip install pre-commit poetry maturin
```
- Install development dependencies
```
poetry install --with dev --with test
```
- Install pre-commit git hooks
```
pre-commit install
```
- Build & install Rust package
```
maturin develop
```

## 🤔 Usage

### 🏃 Run your code

You will then have access to a server on the `localhost:5005`,
```python
# main.py
from hypern import Hypern
from hypern.routing import Route, HTTPEndpoint

class MyEndpoint(HTTPEndpoint):
    
    async def get(self, request):
        return {"data": "Hello World"}

routing = [
    Route("/hello", MyEndpoint)
]

app = Hypern(routing)

if __name__ == "__main__":
    app.start()
```

```
$ python3 main.py
```
You can open swagger UI at path `/docs` 

## CLI

    - host (str): The host address to bind to. Defaults to '127.0.0.1'.
    - port (int): The port number to bind to. Defaults to 5000.
    - processes (int): The number of processes to use. Defaults to 1.
    - workers (int): The number of worker threads to use. Defaults to 1.
    - max_blocking_threads (int): The maximum number of blocking threads. Defaults to 32.
    - reload (bool): If True, the server will restart on file changes.
    - auto_workers (bool): If True, sets the number of workers and max-blocking-threads automatically.


## 💡 Features

### ⚡ High Performance
- Rust-powered core with Python flexibility
- Multi-process architecture for optimal CPU utilization
- Async/await support for non-blocking operations
- Built on top of production-ready Rust language

### 🛠 Development Experience
- Type hints and IDE support
- Built-in Swagger/OpenAPI documentation
- Hot reload during development
- Comprehensive error handling and logging

### 🔌 Integration & Extensions
- Easy dependency injection
- Middleware support (before/after request hooks)
- WebSocket support
- Background task scheduling
- File upload handling

### 🔒 Security
- Built-in authentication/authorization (JWT, API keys, RBAC)
- CORS configuration
- Rate limiting
- Request validation


