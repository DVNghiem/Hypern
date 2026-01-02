# Quick Start Guide

This guide will help you build your first Hypern application in just a few minutes.

## Your First Application

Let's create a simple "Hello World" API to get started with Hypern.

### Step 1: Create Your Project

Create a new directory for your project and navigate into it:

```bash
mkdir my-hypern-app
cd my-hypern-app
```

### Step 2: Create the Main File

Create a file named `main.py` with the following content:

```python
from hypern import Hypern, Request, Response

def hello_handler(request: Request, response: Response):
    response.status(200)
    response.header("Content-Type", "text/plain")
    response.body_str("Hello, World!")
    response.finish()

app = Hypern()
app.add_route("GET", "/hello", hello_handler)

if __name__ == "__main__":
    app.start()
```

### Step 3: Run Your Application

Start the server:

```bash
python main.py
```

You should see output indicating that the server has started. By default, it runs on `http://127.0.0.1:5000`.

### Step 4: Test Your API

Open your browser or use curl to test the endpoint:

```bash
curl http://localhost:5000/hello
```

You should see:

```
Hello, World!
```

Congratulations! 🎉 You've just created your first Hypern application.

## Understanding the Code

Let's break down what each part does:

### 1. Imports

```python
from hypern import Hypern, Request, Response
```

- `Hypern`: The main application class
- `Request`: Contains incoming request data
- `Response`: Builder for constructing HTTP responses

### 2. Handler Function

```python
def hello_handler(request: Request, response: Response):
    response.status(200)
    response.header("Content-Type", "text/plain")
    response.body_str("Hello, World!")
    response.finish()
```

Handler functions receive two parameters:
- `request`: Information about the incoming HTTP request
- `response`: A builder to construct the HTTP response

The response builder uses a fluent API:
- `status(code)`: Set the HTTP status code
- `header(key, value)`: Add response headers
- `body_str(text)`: Set the response body as a string
- `finish()`: Complete and send the response

### 3. Application Setup

```python
app = Hypern()
app.add_route("GET", "/hello", hello_handler)
```

- Create a Hypern application instance
- Register a route that maps GET requests to `/hello` to the handler function

### 4. Start the Server

```python
if __name__ == "__main__":
    app.start()
```

Start the server with default settings.

## JSON Response Example

Let's create a more practical example that returns JSON data:

```python
from hypern import Hypern, Request, Response
import json

def user_handler(request: Request, response: Response):
    data = {
        "id": 1,
        "name": "John Doe",
        "email": "john@example.com"
    }
    
    response.status(200)
    response.header("Content-Type", "application/json")
    response.body_str(json.dumps(data))
    response.finish()

app = Hypern()
app.add_route("GET", "/api/user", user_handler)

if __name__ == "__main__":
    app.start()
```

Test it:

```bash
curl http://localhost:5000/api/user
```

Response:

```json
{
  "id": 1,
  "name": "John Doe",
  "email": "john@example.com"
}
```

## Using Decorators

Hypern also supports a decorator-based routing style:

```python
from hypern import Hypern, Request, Response

app = Hypern()

@app.get("/users")
def get_users(request: Request, response: Response):
    response.status(200)
    response.header("Content-Type", "application/json")
    response.body_str('{"users": []}')
    response.finish()

@app.post("/users")
def create_user(request: Request, response: Response):
    response.status(201)
    response.header("Content-Type", "application/json")
    response.body_str('{"message": "User created"}')
    response.finish()

if __name__ == "__main__":
    app.start()
```

Supported decorator methods:
- `@app.get(path)`
- `@app.post(path)`
- `@app.put(path)`
- `@app.delete(path)`

## Multiple Routes

Here's an example with multiple endpoints:

```python
from hypern import Hypern, Request, Response

app = Hypern()

@app.get("/")
def index(request: Request, response: Response):
    response.status(200)
    response.header("Content-Type", "text/html")
    response.body_str("<h1>Welcome to Hypern!</h1>")
    response.finish()

@app.get("/about")
def about(request: Request, response: Response):
    response.status(200)
    response.header("Content-Type", "text/html")
    response.body_str("<h1>About Us</h1>")
    response.finish()

@app.get("/api/status")
def status(request: Request, response: Response):
    response.status(200)
    response.header("Content-Type", "application/json")
    response.body_str('{"status": "healthy", "version": "1.0.0"}')
    response.finish()

if __name__ == "__main__":
    app.start()
```

## Server Configuration

You can customize the server settings when starting your application:

```python
if __name__ == "__main__":
    app.start(
        host="0.0.0.0",              # Listen on all interfaces
        port=8000,                    # Custom port
        workers=4,                    # Number of worker threads
        max_blocking_threads=32,      # Maximum blocking threads
        max_connections=10000         # Maximum concurrent connections
    )
```

### Configuration Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `host` | str | `"0.0.0.0"` | Host address to bind to |
| `port` | int | `5000` | Port number to listen on |
| `workers` | int | `1` | Number of worker threads |
| `max_blocking_threads` | int | `1` | Maximum blocking threads |
| `max_connections` | int | `10000` | Maximum concurrent connections |

## Accessing Request Data

Access request information through the `request` parameter:

```python
@app.get("/info")
def request_info(request: Request, response: Response):
    # Access request path
    path = request.path
    
    # Access request method
    method = request.method
    
    info = f"Path: {path}, Method: {method}"
    
    response.status(200)
    response.header("Content-Type", "text/plain")
    response.body_str(info)
    response.finish()
```

## Error Handling

Handle errors gracefully:

```python
@app.get("/divide")
def divide(request: Request, response: Response):
    try:
        result = 10 / 0  # This will raise an error
        response.status(200)
        response.body_str(str(result))
    except ZeroDivisionError:
        response.status(500)
        response.header("Content-Type", "application/json")
        response.body_str('{"error": "Division by zero"}')
    finally:
        response.finish()
```

## Built-in API Documentation

Hypern automatically generates API documentation. Access it at:

```
http://localhost:5000/docs
```

This provides an interactive Swagger UI to explore and test your API endpoints.

## Project Structure

For larger applications, organize your code like this:

```
my-hypern-app/
├── main.py           # Application entry point
├── handlers/         # Request handlers
│   ├── __init__.py
│   ├── users.py
│   └── products.py
├── models/           # Data models
│   └── __init__.py
├── middleware/       # Custom middleware
│   └── __init__.py
└── config.py         # Configuration
```

## Next Steps

Now that you understand the basics, explore more advanced features:

- [Basic Concepts](concepts.md) - Understand core Hypern concepts
- [Routing](../guide/routing.md) - Learn about advanced routing features
- [Request & Response](../guide/requests.md) - Deep dive into request/response handling
- [Middleware](../guide/middleware.md) - Add middleware to your application
- [Examples](../examples/basic-api.md) - See real-world examples

## Common Patterns

### Health Check Endpoint

```python
@app.get("/health")
def health_check(request: Request, response: Response):
    response.status(200)
    response.header("Content-Type", "application/json")
    response.body_str('{"status": "ok"}')
    response.finish()
```

### CORS Headers

```python
@app.get("/api/data")
def get_data(request: Request, response: Response):
    response.status(200)
    response.header("Access-Control-Allow-Origin", "*")
    response.header("Content-Type", "application/json")
    response.body_str('{"data": "example"}')
    response.finish()
```

### Custom Status Codes

```python
@app.post("/api/resource")
def create_resource(request: Request, response: Response):
    # Resource created successfully
    response.status(201)
    response.header("Content-Type", "application/json")
    response.body_str('{"id": 123, "created": true}')
    response.finish()
```

## Tips for Success

1. **Always call `response.finish()`** - This sends the response to the client
2. **Set headers before body** - Configure all headers before setting the response body
3. **Use appropriate status codes** - Follow HTTP conventions (200, 201, 400, 404, 500, etc.)
4. **Handle errors gracefully** - Use try-except blocks to catch and handle errors
5. **Test your endpoints** - Use curl, Postman, or the built-in `/docs` interface

## Getting Help

If you encounter issues:

- Check the [User Guide](../guide/application.md) for detailed documentation
- Review [Examples](../examples/basic-api.md) for common use cases
- Visit the [GitHub Issues](https://github.com/martindang/hypern/issues) page
- Read the [API Reference](../api/core/hypern.md)

Happy coding with Hypern! 🚀