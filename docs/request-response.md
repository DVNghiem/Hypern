# Request & Response

## Request Object

### Accessing Request Data

```python
@app.post("/example")
def example(req, res, ctx):
    # Path parameters
    param_value = req.param("name")
    
    # Query string parameters
    query_value = req.query("search")
    all_queries = req.queries()  # Dict of all query params
    
    # Headers
    auth = req.header("Authorization")
    content_type = req.header("Content-Type")
    all_headers = req.headers()
    
    # Body
    json_body = req.json()           # Parse JSON body
    text_body = req.text()           # Raw text body
    bytes_body = req.body()          # Raw bytes
    form_data = req.form()           # Parse form data
    
    # Cookies
    session = req.cookie("session_id")
    
    # Request metadata
    method = req.method              # HTTP method
    path = req.path                  # Request path
    url = req.url                    # Full URL
    
    res.json({"received": True})
```

### JSON Parsing

```python
@app.post("/json")
def handle_json(req, res, ctx):
    # Automatic JSON parsing with SIMD acceleration
    data = req.json()
    
    # Access nested data
    name = data.get("name", "Anonymous")
    items = data.get("items", [])
    
    res.json({"received_items": len(items)})
```

### Form Data

```python
@app.post("/form")
def handle_form(req, res, ctx):
    # Parse URL-encoded form data
    form = req.form()
    
    username = form.get("username")
    password = form.get("password")
    
    res.json({"user": username})
```

## Response Object

### Status Codes

```python
@app.get("/status")
def status_examples(req, res, ctx):
    res.status(200)  # OK
    res.status(201)  # Created
    res.status(204)  # No Content
    res.status(400)  # Bad Request
    res.status(401)  # Unauthorized
    res.status(403)  # Forbidden
    res.status(404)  # Not Found
    res.status(500)  # Internal Server Error
    
    # Chainable
    res.status(200).json({"ok": True})
```

### JSON Response

```python
@app.get("/json")
def json_response(req, res, ctx):
    # Simple object
    res.json({"message": "Hello"})
    
    # Complex nested data
    res.json({
        "user": {"id": 1, "name": "John"},
        "items": [1, 2, 3],
        "metadata": {"count": 3}
    })
```

### HTML Response

```python
@app.get("/page")
def html_response(req, res, ctx):
    html = """
    <!DOCTYPE html>
    <html>
        <head><title>Hello</title></head>
        <body><h1>Welcome!</h1></body>
    </html>
    """
    res.html(html)
```

### Plain Text

```python
@app.get("/text")
def text_response(req, res, ctx):
    res.text("Hello, World!")
```

### Binary Data

```python
@app.get("/binary")
def binary_response(req, res, ctx):
    data = b"\x00\x01\x02\x03"
    res.send(data)
    res.type("application/octet-stream")
```

### File Download

```python
@app.get("/download")
def download_file(req, res, ctx):
    with open("report.pdf", "rb") as f:
        content = f.read()
    
    res.download(content, filename="report.pdf")
```

### Headers

```python
@app.get("/headers")
def custom_headers(req, res, ctx):
    # Single header
    res.header("X-Custom-Header", "value")
    
    # Multiple headers
    res.headers({
        "X-Request-Id": "abc123",
        "X-Rate-Limit": "100"
    })
    
    # Chainable
    res.header("X-One", "1").header("X-Two", "2").json({"ok": True})
```

### Content Type

```python
@app.get("/content-type")
def content_type_examples(req, res, ctx):
    # Using helper
    res.type("application/json")
    
    # Common types
    res.type("text/html")
    res.type("text/plain")
    res.type("application/xml")
    res.type("image/png")
```

### Cookies

```python
@app.get("/set-cookie")
def set_cookie(req, res, ctx):
    res.cookie(
        name="session",
        value="abc123",
        max_age=3600,        # 1 hour
        path="/",
        domain="example.com",
        secure=True,
        http_only=True,
        same_site="Strict"
    )
    res.json({"cookie_set": True})

@app.get("/clear-cookie")
def clear_cookie(req, res, ctx):
    res.clear_cookie("session", path="/")
    res.json({"cookie_cleared": True})
```

### Redirects

```python
@app.get("/redirect")
def redirect_examples(req, res, ctx):
    # Temporary redirect (302)
    res.redirect("/new-location")
    
    # Permanent redirect (301)
    res.redirect("/new-location", status=301)
    
    # Other redirect types
    res.redirect("/temp", status=307)  # Temporary, preserve method
    res.redirect("/perm", status=308)  # Permanent, preserve method
```

### Cache Control

```python
@app.get("/cached")
def cached_response(req, res, ctx):
    res.cache_control(
        max_age=3600,      # 1 hour
        private=False,
        no_cache=False,
        no_store=False
    )
    res.json({"data": "cacheable"})

@app.get("/no-cache")
def no_cache_response(req, res, ctx):
    res.cache_control(no_cache=True, no_store=True)
    res.json({"data": "sensitive"})
```

### ETag

```python
import hashlib

@app.get("/etag")
def etag_response(req, res, ctx):
    data = {"version": 1, "content": "data"}
    
    # Generate ETag from content
    etag = hashlib.md5(str(data).encode()).hexdigest()
    
    # Check if client has current version
    client_etag = req.header("If-None-Match")
    if client_etag == etag:
        res.status(304).send(None)
        return
    
    res.etag(etag)
    res.json(data)
```

## Response Chaining

All response methods are chainable:

```python
@app.get("/chained")
def chained_response(req, res, ctx):
    res.status(200) \
       .header("X-Custom", "value") \
       .type("application/json") \
       .cache_control(max_age=60) \
       .json({"message": "success"})
```

## Ending the Response

```python
@app.get("/end")
def end_response(req, res, ctx):
    # Using specific method (auto-ends)
    res.json({"data": "value"})
    
    # Manual ending
    res.status(204).end()
    
    # With data
    res.end("Response body")
```
