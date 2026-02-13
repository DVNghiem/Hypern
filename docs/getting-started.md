# Getting Started

## Installation

```bash
# Install with pip
pip install hypern

# Or build from source with maturin
pip install maturin
maturin develop --release
```

## Your First Application

```python
from hypern import Hypern

app = Hypern()

@app.get("/")
def home(req, res, ctx):
    res.json({"message": "Hello, World!"})

@app.get("/users/:id")
def get_user(req, res, ctx):
    user_id = req.param("id")
    res.json({"user_id": user_id})

if __name__ == "__main__":
    app.start(host="0.0.0.0", port=8000)
```

## Running the Server

```bash
python app.py
# Server running at http://0.0.0.0:8000
```

## Server Configuration

```python
app.start(
    host="0.0.0.0",
    port=8000,
    workers=4,              # Number of worker processes
    worker_threads=2,       # Threads per worker
    backlog=1024,           # Connection backlog
    max_connections=10000,  # Max concurrent connections
    max_request_size=16777216,  # 16MB max request body
)
```

## Development Mode

For development with auto-reload:

```python
if __name__ == "__main__":
    app.start(
        host="0.0.0.0",
        port=8000,
        reload=True,          # Enable auto-reload
        reload_dirs=["./src", "./app"],  # Directories to watch
    )
```

## Project Structure

Recommended project layout:

```
myapp/
├── app/
│   ├── __init__.py
│   ├── main.py           # App entry point
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── users.py
│   │   └── products.py
│   ├── middleware/
│   │   ├── __init__.py
│   │   └── auth.py
│   └── services/
│       ├── __init__.py
│       └── database.py
├── tests/
│   └── test_app.py
├── pyproject.toml
└── README.md
```

## Next Steps

- [Routing](./routing.md) - Learn about route definitions and parameters
- [Request & Response](./request-response.md) - Handle requests and send responses
- [Middleware](./middleware.md) - Add cross-cutting concerns
