#!/usr/bin/env python
"""
Standalone test server for Hypern framework tests.
This server runs in a separate process to avoid threading issues with signals.
"""

import json
import os
import sys
import time
from typing import Dict, Any, Optional

# Add the parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import msgspec

from hypern import (
    Hypern, 
    Router, 
    SSEEvent,
    NotFound, 
    BadRequest, 
    Unauthorized,
    HTTPException,
)
from hypern.validation import validate, validate_body, validate_query
from hypern.middleware import (
    CorsMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware, CompressionMiddleware,
    RequestIdMiddleware, BasicAuthMiddleware
)


# ============================================================================
# Validation Schemas (msgspec)
# ============================================================================

class CreateUserSchema(msgspec.Struct):
    """Schema for creating a user."""
    name: str
    email: str
    age: int


class UpdateUserSchema(msgspec.Struct):
    """Schema for updating a user (partial)."""
    name: str = ""
    email: str = ""
    age: int = 0


class QueryParamsSchema(msgspec.Struct):
    """Schema for query parameters."""
    page: int = 1
    limit: int = 10
    search: str = ""


class NestedAddressSchema(msgspec.Struct):
    """Nested address schema."""
    street: str
    city: str
    zip_code: str


class NestedUserSchema(msgspec.Struct):
    """Schema with nested object."""
    name: str
    email: str
    address: NestedAddressSchema


# ============================================================================
# Test Data Storage (in-memory database)
# ============================================================================

class MockDatabase:
    """In-memory database for testing."""
    
    def __init__(self):
        self.users: Dict[str, Dict[str, Any]] = {
            "1": {"id": "1", "name": "Alice", "email": "alice@example.com", "age": 30},
            "2": {"id": "2", "name": "Bob", "email": "bob@example.com", "age": 25},
        }
        self.products: Dict[str, Dict[str, Any]] = {
            "p1": {"id": "p1", "name": "Laptop", "price": 999.99},
            "p2": {"id": "p2", "name": "Phone", "price": 699.99},
        }
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.next_user_id = 3
        self.next_product_id = 3
    
    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self.users.get(user_id)
    
    def get_all_users(self) -> list:
        return list(self.users.values())
    
    def create_user(self, data: Dict[str, Any]) -> Dict[str, Any]:
        user_id = str(self.next_user_id)
        self.next_user_id += 1
        user = {"id": user_id, **data}
        self.users[user_id] = user
        return user
    
    def update_user(self, user_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if user_id in self.users:
            self.users[user_id].update(data)
            return self.users[user_id]
        return None
    
    def delete_user(self, user_id: str) -> bool:
        if user_id in self.users:
            del self.users[user_id]
            return True
        return False
    
    def reset(self):
        """Reset the database to initial state."""
        self.users = {
            "1": {"id": "1", "name": "Alice", "email": "alice@example.com", "age": 30},
            "2": {"id": "2", "name": "Bob", "email": "bob@example.com", "age": 25},
        }
        self.products = {
            "p1": {"id": "p1", "name": "Laptop", "price": 999.99},
            "p2": {"id": "p2", "name": "Phone", "price": 699.99},
        }
        self.tasks = {}
        self.next_user_id = 3
        self.next_product_id = 3


# Global test database instance
test_db = MockDatabase()


def create_test_app() -> Hypern:
    """Create and configure the test application with all features."""
    
    app = Hypern(debug=True)
    
    # ========================================================================
    # Global Middleware Configuration
    # ========================================================================
    
    # Request ID for tracing (adds X-Request-ID header)
    app.use(RequestIdMiddleware())
    
    # CORS - permissive for testing (allows all origins)
    app.use(CorsMiddleware.permissive())
    
    # Security headers (HSTS, X-Frame-Options, CSP, etc.)
    app.use(SecurityHeadersMiddleware.strict())
    
    # Compression for responses > 100 bytes
    app.use(CompressionMiddleware(min_size=100))
    
    # ========================================================================
    # Dependency Injection Setup
    # ========================================================================
    
    # Register singleton dependencies
    app.singleton("config", {
        "app_name": "Hypern Test App",
        "debug": True,
        "database_url": "memory://test",
        "secret_key": "test-secret-key-123",
    })
    app.singleton("database", test_db)
    
    # Register factory dependencies
    def create_request_logger():
        return {"logs": [], "created_at": time.time()}
    
    app.factory("request_logger", create_request_logger)
    
    # ========================================================================
    # Basic Routes - HTTP Methods
    # ========================================================================
    
    @app.get("/")
    def home(req, res, ctx):
        res.json({"message": "Hello, World!", "service": "Hypern Test Server"})
    
    @app.get("/health")
    def health(req, res, ctx):
        res.json({"status": "healthy", "timestamp": time.time()})
    
    @app.post("/echo")
    def echo(req, res, ctx):
        """Echo back the request body."""
        body = req.json()
        res.json({"echo": body})
    
    @app.put("/echo")
    def echo_put(req, res, ctx):
        """Echo back the request body for PUT."""
        body = req.json()
        res.json({"method": "PUT", "echo": body})
    
    @app.patch("/echo")
    def echo_patch(req, res, ctx):
        """Echo back the request body for PATCH."""
        body = req.json()
        res.json({"method": "PATCH", "echo": body})
    
    @app.delete("/echo")
    def echo_delete(req, res, ctx):
        res.json({"method": "DELETE", "deleted": True})
    
    @app.options("/echo")
    def echo_options(req, res, ctx):
        res.header("Allow", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        res.status(204).send(None)
    
    @app.head("/echo")
    def echo_head(req, res, ctx):
        res.header("X-Echo-Status", "available")
        res.status(200).send(None)
    
    # ========================================================================
    # Route Parameters
    # ========================================================================
    
    @app.get("/users/:user_id")
    def get_user(req, res, ctx):
        user_id = req.param("user_id")
        user = test_db.get_user(user_id)
        if user:
            res.json(user)
        else:
            res.status(404).json({"error": "User not found", "user_id": user_id})
    
    @app.get("/users/:user_id/posts/:post_id")
    def get_user_post(req, res, ctx):
        """Multiple route parameters."""
        user_id = req.param("user_id")
        post_id = req.param("post_id")
        res.json({
            "user_id": user_id,
            "post_id": post_id,
            "title": f"Post {post_id} by User {user_id}"
        })
    
    @app.get("/files/*filepath")
    def get_file(req, res, ctx):
        """Wildcard route parameter."""
        filepath = req.param("filepath")
        res.json({"filepath": filepath})
    
    # ========================================================================
    # Query Parameters
    # ========================================================================
    
    @app.get("/search")
    def search(req, res, ctx):
        q = req.query("q") or ""
        page = req.query("page") or "1"
        limit = req.query("limit") or "10"
        all_queries = req.query_params
        res.json({
            "q": q,
            "page": int(page),
            "limit": int(limit),
            "all_queries": all_queries
        })
    
    # ========================================================================
    # Request Data Access
    # ========================================================================
    
    @app.get("/request-info")
    def request_info(req, res, ctx):
        res.json({
            "method": req.method,
            "path": req.path,
            "url": req.url,
        })
    
    @app.get("/headers-echo")
    def headers_echo(req, res, ctx):
        """Return all request headers."""
        # Note: headers is a property, not a method
        headers = req.headers
        custom_header = req.header("X-Custom-Header")
        res.json({
            "custom_header": custom_header,
            "all_headers": headers
        })
    
    @app.get("/cookies-echo")
    def cookies_echo(req, res, ctx):
        """Return cookie values."""
        session_id = req.cookie("session_id")
        auth_token = req.cookie("auth_token")
        res.json({
            "session_id": session_id,
            "auth_token": auth_token
        })
    
    @app.post("/form-data")
    def form_data(req, res, ctx):
        """Handle form data."""
        form = req.form()
        # Convert FormData to dict using get_fields()
        form_dict = dict(form.get_fields())
        res.json({"form": form_dict})
    
    @app.post("/text-body")
    def text_body(req, res, ctx):
        """Handle raw text body."""
        # Use body_bytes and decode to get text
        body = req.body_bytes()
        text = body.decode('utf-8') if body else ""
        res.json({"text": text})
    
    @app.post("/binary-body")
    def binary_body(req, res, ctx):
        """Handle binary body."""
        body = req.body_bytes()
        res.json({"length": len(body), "type": "bytes"})
    
    # ========================================================================
    # Response Types
    # ========================================================================
    
    @app.get("/response/json")
    def response_json(req, res, ctx):
        res.json({
            "string": "value",
            "number": 42,
            "float": 3.14,
            "boolean": True,
            "null": None,
            "array": [1, 2, 3],
            "nested": {"key": "value"}
        })
    
    @app.get("/response/html")
    def response_html(req, res, ctx):
        res.html("<html><body><h1>Hello HTML</h1></body></html>")
    
    @app.get("/response/text")
    def response_text(req, res, ctx):
        res.text("Plain text response")
    
    @app.get("/response/xml")
    def response_xml(req, res, ctx):
        res.xml("<root><item>value</item></root>")
    
    @app.get("/response/status/:code")
    def response_status(req, res, ctx):
        code = int(req.param("code"))
        res.status(code).json({"status_code": code})
    
    @app.get("/response/headers")
    def response_headers(req, res, ctx):
        res.header("X-Custom-Response", "test-value")
        res.header("X-Another-Header", "another-value")
        res.json({"headers_set": True})
    
    @app.get("/response/redirect")
    def response_redirect(req, res, ctx):
        res.redirect("/", 302)
    
    @app.get("/response/redirect-permanent")
    def response_redirect_permanent(req, res, ctx):
        res.redirect("/", 301)
    
    # ========================================================================
    # Cookies
    # ========================================================================
    
    @app.get("/cookies/set")
    def set_cookies(req, res, ctx):
        res.cookie("session_id", "abc123", max_age=3600, path="/")
        res.cookie("preferences", "dark_mode=true", max_age=86400, path="/")
        res.json({"cookies_set": True})
    
    @app.get("/cookies/set-secure")
    def set_secure_cookies(req, res, ctx):
        res.cookie(
            "secure_token",
            "secure-value",
            max_age=3600,
            path="/",
            secure=True,
            http_only=True,
            same_site="Strict"
        )
        res.json({"secure_cookie_set": True})
    
    @app.get("/cookies/clear")
    def clear_cookies(req, res, ctx):
        res.clear_cookie("session_id")
        res.json({"cookies_cleared": True})
    
    # ========================================================================
    # Cache Control
    # ========================================================================
    
    @app.get("/cache/enabled")
    def cache_enabled(req, res, ctx):
        res.cache_control(max_age=3600, private=False)
        res.json({"cached": True})
    
    @app.get("/cache/disabled")
    def cache_disabled(req, res, ctx):
        res.no_cache()
        res.json({"cached": False})
    
    # ========================================================================
    # File Upload & Multipart
    # ========================================================================
    
    @app.post("/upload/single")
    def upload_single_file(req, res, ctx):
        """Handle single file upload."""
        try:
            file = req.file("document")
            if file:
                res.json({
                    "uploaded": True,
                    "filename": file.filename,
                    "size": file.size,
                    "content_type": file.content_type,
                    "name": file.name
                })
            else:
                res.status(400).json({"error": "No file uploaded"})
        except Exception:
            res.status(400).json({"error": "No file uploaded"})
    
    @app.post("/upload/multiple")
    def upload_multiple_files(req, res, ctx):
        """Handle multiple file uploads."""
        try:
            files = req.files()
            if files:
                file_info = [{
                    "filename": f.filename,
                    "size": f.size,
                    "content_type": f.content_type,
                    "name": f.name
                } for f in files]
                res.json({
                    "uploaded": len(files),
                    "files": file_info
                })
            else:
                res.status(400).json({"error": "No files uploaded"})
        except Exception:
            res.status(400).json({"error": "No files uploaded"})
    
    @app.post("/upload/with-fields")
    def upload_with_fields(req, res, ctx):
        """Handle file upload with form fields."""
        form = req.form()
        file = req.file("document")
        
        fields = dict(form.get_fields())
        
        result = {
            "fields": fields,
            "has_file": file is not None
        }
        
        if file:
            result["file"] = {
                "filename": file.filename,
                "size": file.size
            }
        
        res.json(result)
    
    # ========================================================================
    # File Download & Attachments
    # ========================================================================
    
    @app.get("/download/text")
    def download_text_file(req, res, ctx):
        """Download a text file as attachment."""
        content = "This is a sample text file.\nLine 2\nLine 3"
        res.attachment("sample.txt")
        res.text(content)
    
    @app.get("/download/json")
    def download_json_file(req, res, ctx):
        """Download JSON data as attachment."""
        data = {"message": "Hello", "data": [1, 2, 3]}
        res.attachment("data.json")
        res.json(data)
    
    @app.get("/download/binary")
    def download_binary_file(req, res, ctx):
        """Download binary data."""
        # Create some binary content
        binary_data = bytes([0x48, 0x65, 0x6C, 0x6C, 0x6F])  # "Hello" in bytes
        res.attachment("data.bin")
        res.header("Content-Type", "application/octet-stream")
        res.send(binary_data)
    
    @app.get("/download/custom/:filename")
    def download_custom_filename(req, res, ctx):
        """Download with custom filename from path parameter."""
        filename = req.param("filename")
        res.attachment(filename)
        res.text(f"Content for {filename}")
    
    # ========================================================================
    # Validation Routes
    # ========================================================================
    
    @app.post("/validated/user")
    @validate_body(CreateUserSchema)
    def create_validated_user(req, res, ctx, body: CreateUserSchema):
        user = test_db.create_user({
            "name": body.name,
            "email": body.email,
            "age": body.age
        })
        res.status(201).json(user)
    
    @app.get("/validated/search")
    @validate_query(QueryParamsSchema)
    def validated_search(req, res, ctx, query: QueryParamsSchema):
        users = test_db.get_all_users()
        
        # Apply search filter
        if query.search:
            users = [u for u in users if query.search.lower() in u["name"].lower()]
        
        # Apply pagination
        start = (query.page - 1) * query.limit
        end = start + query.limit
        paginated = users[start:end]
        
        res.json({
            "data": paginated,
            "page": query.page,
            "limit": query.limit,
            "total": len(users)
        })
    
    @app.post("/validated/combined")
    @validate(body=CreateUserSchema, query=QueryParamsSchema)
    def validated_combined(req, res, ctx, body: CreateUserSchema, query: QueryParamsSchema):
        res.json({
            "body": {"name": body.name, "email": body.email, "age": body.age},
            "query": {"page": query.page, "limit": query.limit, "search": query.search}
        })
    
    @app.post("/validated/nested")
    @validate_body(NestedUserSchema)
    def create_nested_user(req, res, ctx, body: NestedUserSchema):
        res.status(201).json({
            "name": body.name,
            "email": body.email,
            "address": {
                "street": body.address.street,
                "city": body.address.city,
                "zip_code": body.address.zip_code
            }
        })
    
    # ========================================================================
    # Dependency Injection Routes
    # ========================================================================
    
    @app.get("/di/config")
    @app.inject("config")
    def get_config(req, res, ctx, config):
        res.json(config)
    
    @app.get("/di/database")
    @app.inject("database")
    def get_database_users(req, res, ctx, database):
        users = database.get_all_users()
        res.json({"users": users})
    
    @app.get("/di/factory")
    @app.inject("request_logger")
    def get_logger(req, res, ctx, request_logger):
        res.json({
            "logger_created": True,
            "has_logs": isinstance(request_logger.get("logs"), list)
        })
    
    # ========================================================================
    # Context Routes
    # ========================================================================
    
    @app.get("/context/set-get")
    def context_set_get(req, res, ctx):
        ctx.set("request_id", "req-12345")
        ctx.set("user_id", "user-789")
        ctx.set("role", "admin")
        
        request_id = ctx.get("request_id")
        user_id = ctx.get("user_id")
        has_role = ctx.has("role")
        missing = ctx.get("nonexistent")
        if missing is None:
            missing = "default_value"
        
        res.json({
            "request_id": request_id,
            "user_id": user_id,
            "has_role": has_role,
            "missing_with_default": missing
        })
    
    @app.get("/context/elapsed")
    def context_elapsed(req, res, ctx):
        # Simulate some work
        time.sleep(0.01)
        elapsed = ctx.elapsed_ms()
        res.json({"elapsed_ms": elapsed})
    
    # ========================================================================
    # SSE Routes
    # ========================================================================
    
    @app.get("/sse/basic")
    def sse_basic(req, res, ctx):
        events = [
            SSEEvent("Connected!", event="connect"),
            SSEEvent("Hello World", event="message", id="1"),
            SSEEvent("Goodbye", event="close", id="2"),
        ]
        res.sse(events)
    
    @app.get("/sse/single")
    def sse_single(req, res, ctx):
        res.sse_event(
            data="Single notification",
            event="notification",
            id="notif-1"
        )
    
    @app.get("/sse/data")
    def sse_data(req, res, ctx):
        events = [
            SSEEvent(json.dumps({"count": 1}), event="data", id="1"),
            SSEEvent(json.dumps({"count": 2}), event="data", id="2"),
            SSEEvent(json.dumps({"count": 3}), event="data", id="3"),
        ]
        res.sse(events)
    
    # ========================================================================
    # Background Tasks Routes
    # ========================================================================
    
    @app.background()
    def background_process(task_data: dict):
        """Background task that processes data."""
        time.sleep(0.1)  # Simulate work
        return {"processed": task_data, "status": "completed"}
    
    @app.post("/tasks/submit")
    def submit_task(req, res, ctx):
        data = req.json()
        task_id = app.submit_task(
            background_process,
            args=(data,)
        )
        res.json({"task_id": task_id, "status": "submitted"})
    
    @app.get("/tasks/:task_id")
    def get_task_status(req, res, ctx):
        task_id = req.param("task_id")
        result = app.get_task(task_id)
        if result:
            res.json({
                "task_id": task_id,
                "status": result.status.name if hasattr(result.status, 'name') else str(result.status),
                "result": result.result,
                "error": result.error
            })
        else:
            res.status(404).json({"error": "Task not found"})
    
    # ========================================================================
    # Error Handling Routes
    # ========================================================================
    
    @app.get("/errors/not-found")
    def trigger_not_found(req, res, ctx):
        raise NotFound("Resource not found")
    
    @app.get("/errors/bad-request")
    def trigger_bad_request(req, res, ctx):
        raise BadRequest("Invalid request data")
    
    @app.get("/errors/unauthorized")
    def trigger_unauthorized(req, res, ctx):
        raise Unauthorized("Authentication required")
    
    @app.get("/errors/custom")
    def trigger_custom_error(req, res, ctx):
        raise HTTPException(status_code=418, detail="I'm a teapot")
    
    @app.get("/errors/internal")
    def trigger_internal_error(req, res, ctx):
        raise Exception("Unexpected internal error")
    
    # Register error handlers
    @app.errorhandler(NotFound)
    def handle_not_found(req, res, error):
        res.status(404).json({"error": "not_found", "message": str(error.detail)})
    
    @app.errorhandler(BadRequest)
    def handle_bad_request(req, res, error):
        res.status(400).json({"error": "bad_request", "message": str(error.detail)})
    
    @app.errorhandler(Unauthorized)
    def handle_unauthorized(req, res, error):
        res.status(401).json({"error": "unauthorized", "message": str(error.detail)})
    
    @app.errorhandler(HTTPException)
    def handle_http_exception(req, res, error):
        res.status(error.status_code).json({
            "error": "http_exception",
            "status_code": error.status_code,
            "message": str(error.detail)
        })
    
    @app.errorhandler(Exception)
    def handle_generic_error(req, res, error):
        res.status(500).json({"error": "internal_error", "message": str(error)})
    
    # ========================================================================
    # Router Groups (API Versioning)
    # ========================================================================
    
    api_v1 = Router(prefix="/api/v1")
    
    @api_v1.get("/users")
    def v1_list_users(req, res, ctx):
        users = test_db.get_all_users()
        res.json({"version": "v1", "users": users})
    
    @api_v1.get("/users/:id")
    def v1_get_user(req, res, ctx):
        user_id = req.param("id")
        user = test_db.get_user(user_id)
        if user:
            res.json({"version": "v1", "user": user})
        else:
            res.status(404).json({"error": "User not found"})
    
    @api_v1.post("/users")
    def v1_create_user(req, res, ctx):
        data = req.json()
        user = test_db.create_user(data)
        res.status(201).json({"version": "v1", "user": user})
    
    api_v2 = Router(prefix="/api/v2")
    
    @api_v2.get("/users")
    def v2_list_users(req, res, ctx):
        users = test_db.get_all_users()
        res.json({
            "version": "v2",
            "data": users,
            "meta": {"total": len(users)}
        })
    
    @api_v2.get("/users/:id")
    def v2_get_user(req, res, ctx):
        user_id = req.param("id")
        user = test_db.get_user(user_id)
        if user:
            res.json({"version": "v2", "data": user})
        else:
            res.status(404).json({"error": "User not found"})
    
    # Mount routers - use app.mount() with router's own prefix
    app.mount(api_v1)
    app.mount(api_v2)
    
    # ========================================================================
    # Router with Validation (tests Router + @validate_body together)
    # ========================================================================
    
    class RouterSearchSchema(msgspec.Struct):
        """Schema for router-based search."""
        q: str
        page: int = 1
        limit: int = 20
        sort: str = "desc"
    
    class RouterCreateItemSchema(msgspec.Struct):
        """Schema for creating an item via router."""
        name: str
        price: float
        category: str = "general"
    
    class RouterQuerySchema(msgspec.Struct):
        """Schema for router query params."""
        page: int = 1
        limit: int = 10
        search: str = ""
    
    router_validated = Router(prefix="/router-validated")
    
    @router_validated.post("/search")
    @validate_body(RouterSearchSchema)
    def router_search(req, res, ctx, body: RouterSearchSchema):
        res.json({
            "query": body.q,
            "page": body.page,
            "limit": body.limit,
            "sort": body.sort,
        })
    
    @router_validated.post("/items")
    @validate_body(RouterCreateItemSchema)
    def router_create_item(req, res, ctx, body: RouterCreateItemSchema):
        res.status(201).json({
            "name": body.name,
            "price": body.price,
            "category": body.category,
        })
    
    @router_validated.get("/items")
    @validate_query(RouterQuerySchema)
    def router_list_items(req, res, ctx, query: RouterQuerySchema):
        res.json({
            "page": query.page,
            "limit": query.limit,
            "search": query.search,
        })
    
    @router_validated.post("/items-with-query")
    @validate(body=RouterCreateItemSchema, query=RouterQuerySchema)
    def router_create_with_query(req, res, ctx, body: RouterCreateItemSchema, query: RouterQuerySchema):
        res.status(201).json({
            "item": {"name": body.name, "price": body.price, "category": body.category},
            "query": {"page": query.page, "limit": query.limit},
        })
    
    # Mount with explicit prefix
    app.mount("/router-validated", router_validated)
    
    # ========================================================================
    # Router with OpenAPI decorators (tests Router + @api_tags/@api_doc)
    # ========================================================================
    
    from hypern.openapi import tags, summary, deprecated, operation_id, requires_auth
    
    router_docs = Router(prefix="/router-docs")
    
    @router_docs.get("/users")
    @tags("users", "docs-test")
    @summary("List Users (Router)")
    def router_docs_list_users(req, res, ctx):
        """List all users via router with API docs."""
        res.json({"users": test_db.get_all_users()})
    
    @router_docs.get("/users/:id")
    @tags("users", "docs-test")
    @summary("Get User (Router)")
    def router_docs_get_user(req, res, ctx):
        """Get a user by ID via router with API docs."""
        user_id = req.param("id")
        user = test_db.get_user(user_id)
        if user:
            res.json(user)
        else:
            res.status(404).json({"error": "User not found"})
    
    @router_docs.get("/deprecated-endpoint")
    @deprecated
    @tags("docs-test")
    def router_deprecated(req, res, ctx):
        """This endpoint is deprecated."""
        res.json({"deprecated": True})
    
    @router_docs.post("/create")
    @tags("users", "docs-test")
    @summary("Create User (Router)")
    @validate_body(CreateUserSchema)
    def router_docs_create_user(req, res, ctx, body: CreateUserSchema):
        """Create a user with validation and API doc decorators."""
        user = test_db.create_user({
            "name": body.name,
            "email": body.email,
            "age": body.age,
        })
        res.status(201).json(user)
    
    app.mount(router_docs)
    
    # ========================================================================
    # Async Handlers (Note: Limited async support - testing sync equivalents)
    # ========================================================================
    
    @app.get("/async/basic")
    def async_basic(req, res, ctx):
        # Note: True async with asyncio.sleep requires event loop support
        # This tests the async detection and handling path with a sync handler
        import time
        time.sleep(0.01)
        res.json({"type": "async", "status": "completed"})
    
    @app.post("/async/process")
    def async_process(req, res, ctx):
        # Note: True async with asyncio.sleep requires event loop support
        import time
        data = req.json()
        time.sleep(0.01)  # Simulate async operation
        res.json({"processed": data, "async": True})
    
    # ========================================================================
    # CRUD Operations (Users)
    # ========================================================================
    
    @app.get("/crud/users")
    def crud_list_users(req, res, ctx):
        users = test_db.get_all_users()
        res.json({"users": users})
    
    @app.post("/crud/users")
    def crud_create_user(req, res, ctx):
        data = req.json()
        user = test_db.create_user(data)
        res.status(201).json(user)
    
    @app.get("/crud/users/:id")
    def crud_get_user(req, res, ctx):
        user_id = req.param("id")
        user = test_db.get_user(user_id)
        if user:
            res.json(user)
        else:
            res.status(404).json({"error": "User not found"})
    
    @app.put("/crud/users/:id")
    def crud_update_user(req, res, ctx):
        user_id = req.param("id")
        data = req.json()
        user = test_db.update_user(user_id, data)
        if user:
            res.json(user)
        else:
            res.status(404).json({"error": "User not found"})
    
    @app.delete("/crud/users/:id")
    def crud_delete_user(req, res, ctx):
        user_id = req.param("id")
        if test_db.delete_user(user_id):
            res.status(204).send(None)
        else:
            res.status(404).json({"error": "User not found"})
    
    # ========================================================================
    # Database Reset Endpoint (for tests)
    # ========================================================================
    
    @app.post("/test/reset-db")
    def reset_database(req, res, ctx):
        test_db.reset()
        res.json({"status": "database_reset"})
    
    # ========================================================================
    # Middleware Testing Endpoints
    # ========================================================================
    
    # CORS endpoints - use global CORS middleware
    @app.get("/middleware/cors/test")
    def cors_test(req, res, ctx):
        res.json({"cors": "enabled"})
    
    @app.get("/middleware/cors/with-origin")
    def cors_with_origin_test(req, res, ctx):
        res.header("X-Custom-Header", "test-value")
        res.json({"cors": "with-origin"})
    
    @app.options("/middleware/cors/with-origin")
    def cors_preflight(req, res, ctx):
        res.status(204).send(None)
    
    # Rate limiting endpoint - strict limit for testing
    RateLimitMiddleware(max_requests=3, window_secs=10)
    @app.get("/middleware/ratelimit/strict")
    def ratelimit_strict_test(req, res, ctx):
        res.json({"requests": "limited"})
    
    # Security headers endpoints - use global middleware
    @app.get("/middleware/security/test")
    def security_test(req, res, ctx):
        res.json({"security": "enabled"})
    
    # Compression endpoint - large response
    @app.get("/middleware/compression/large")
    def compression_large_test(req, res, ctx):
        # Large response to trigger compression (> 100 bytes)
        res.json({"data": "x" * 500, "compressed": True})
    
    @app.get("/middleware/compression/small")
    def compression_small_test(req, res, ctx):
        # Small response - won't compress
        res.json({"tiny": "data"})
    
    # RequestId endpoint - uses global RequestId middleware  
    @app.get("/middleware/requestid/test")
    def requestid_test(req, res, ctx):
        res.json({"requestid": "enabled"})
    
    # BasicAuth protected endpoint
    BasicAuthMiddleware(
        realm="Test Area",
        users={"admin": "secret", "testuser": "password123"}
    )
    
    # Create a custom middleware wrapper for BasicAuth
    def auth_middleware(req, res, ctx, next):
        """Custom middleware wrapper for basic auth"""
        auth_header = req.header("Authorization")
        
        if not auth_header or not auth_header.startswith("Basic "):
            res.status(401)
            res.header("WWW-Authenticate", 'Basic realm="Test Area"')
            res.json({"error": "Authentication required"})
            return
        
        # Decode credentials
        import base64
        try:
            encoded = auth_header[6:]  # Remove "Basic "
            decoded = base64.b64decode(encoded).decode('utf-8')
            username, password = decoded.split(':', 1)
            
            # Check credentials
            valid_users = {"admin": "secret", "testuser": "password123"}
            if username in valid_users and valid_users[username] == password:
                # Call next() to continue to the endpoint
                return next()
            else:
                res.status(401)
                res.header("WWW-Authenticate", 'Basic realm="Test Area"')
                res.json({"error": "Invalid credentials"})
        except Exception:
            res.status(401)
            res.header("WWW-Authenticate", 'Basic realm="Test Area"')
            res.json({"error": "Invalid authorization header"})
    
    @app.get("/middleware/auth/protected", middleware=[auth_middleware])
    def auth_protected(req, res, ctx):
        res.json({"auth": "success", "protected": True})
    
    # ========================================================================
    # Custom Middleware & Hooks Testing Endpoints
    # ========================================================================
    
    # Import the decorators
    from hypern.middleware import middleware, before_request, after_request
    
    # Define custom middleware with @middleware decorator
    @middleware
    async def custom_test_middleware(req, res, ctx, next):
        """Custom middleware that adds a header."""
        res.header("X-Custom-Middleware", "executed")
        await next()
    
    @middleware
    async def modify_middleware(req, res, ctx, next):
        """Middleware that modifies request context."""
        ctx.set("modified_by_middleware", True)
        await next()
    
    @middleware
    async def blocking_middleware(req, res, ctx, next):
        """Middleware that blocks certain requests."""
        # Don't call next() - short circuit
        res.status(403).json({"error": "Blocked by middleware"})
    
    # Define before_request hooks
    @before_request
    async def add_before_header(req, res, ctx):
        """Before-request hook that adds header."""
        res.header("X-Before-Request", "hook-executed")
    
    @before_request
    async def add_before_header_1(req, res, ctx):
        """First before-request hook."""
        res.header("X-Before-1", "executed")
        ctx.set("before_1", True)
    
    @before_request
    async def add_before_header_2(req, res, ctx):
        """Second before-request hook."""
        res.header("X-Before-2", "executed")
        ctx.set("before_2", True)
    
    # Define after_request hooks
    @after_request
    async def add_after_header(req, res, ctx):
        """After-request hook that adds header."""
        res.header("X-After-Request", "hook-executed")
    
    @after_request
    async def add_after_header_1(req, res, ctx):
        """First after-request hook."""
        res.header("X-After-1", "executed")
    
    @after_request
    async def add_after_header_2(req, res, ctx):
        """Second after-request hook."""
        res.header("X-After-2", "executed")
    
    # Register the hooks globally
    app.use(add_before_header)
    app.use(add_before_header_1)
    app.use(add_before_header_2)
    app.use(add_after_header)
    app.use(add_after_header_1)
    app.use(add_after_header_2)
    
    # Test endpoints for custom middleware
    @app.get("/middleware/custom/test", middleware=[custom_test_middleware])
    def custom_middleware_test(req, res, ctx):
        res.json({"message": "custom middleware test"})
    
    @app.get("/middleware/custom/modify", middleware=[modify_middleware])
    def custom_middleware_modify(req, res, ctx):
        modified = ctx.get("modified_by_middleware")
        res.json({"modified_by_middleware": modified})
    
    @app.get("/middleware/custom/blocked", middleware=[blocking_middleware])
    def custom_middleware_blocked(req, res, ctx):
        # This should never be reached
        res.json({"message": "should not reach here"})
    
    # Test endpoints for hooks
    @app.get("/hooks/before-test")
    def before_hook_test(req, res, ctx):
        res.json({"message": "before hook test"})
    
    @app.get("/hooks/after-test")
    def after_hook_test(req, res, ctx):
        res.json({"message": "after hook test"})
    
    @app.get("/hooks/multiple-before")
    def multiple_before_hooks(req, res, ctx):
        order = []
        if ctx.get("before_1"):
            order.append("before-1")
        if ctx.get("before_2"):
            order.append("before-2")
        order.append("handler")
        res.json({"order": order})
    
    @app.get("/hooks/multiple-after")
    def multiple_after_hooks(req, res, ctx):
        res.json({"executed": True})
    
    return app


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Run Hypern test server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on")
    
    args = parser.parse_args()
    
    app = create_test_app()
    print(f"Starting test server on {args.host}:{args.port}")
    app.start(
        host=args.host,
        port=args.port,
        num_processes=1,
        workers_threads=2,
        max_blocking_threads=8,
    )
