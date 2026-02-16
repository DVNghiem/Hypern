# Authentication & Authorization

Hypern provides a complete authentication and authorization module with **JWT tokens**, **API key validation**, and **Role-Based Access Control (RBAC)**.

All components are pure Python (no external JWT library needed) and integrate seamlessly with Hypern's request context and OpenAPI generation.

## JWT Authentication

### Setup

```python
from hypern import Hypern, JWTAuth

app = Hypern()
jwt = JWTAuth(
    secret="your-secret-key",
    expiry_seconds=3600,       # 1 hour (default)
    issuer="my-app",           # optional iss claim
    audience="web-app",        # optional aud claim
)
```

### Issuing Tokens

```python
@app.post("/login")
def login(req, res, ctx):
    data = req.json()
    user = authenticate(data["username"], data["password"])
    if not user:
        res.status(401).json({"error": "Invalid credentials"})
        return

    token = jwt.encode({
        "sub": str(user.id),
        "roles": user.roles,
        "name": user.name,
    })
    res.json({"token": token})
```

### Protecting Routes

Use the `@jwt.required` decorator to enforce authentication:

```python
@app.get("/me")
@jwt.required
def get_me(req, res, ctx):
    user = ctx.get("auth_user")   # decoded JWT payload
    res.json({"user_id": user["sub"], "name": user["name"]})
```

On success the decorator stores:

| Context Key   | Value                      |
|---------------|----------------------------|
| `auth_user`   | Full decoded JWT payload   |
| `auth_token`  | Raw token string           |

It also calls `ctx.set_auth(user_id, roles)` for the built-in Rust context.

### Optional Authentication

Use `@jwt.optional` when a route should work for both authenticated and anonymous users:

```python
@app.get("/feed")
@jwt.optional
def feed(req, res, ctx):
    user = ctx.get("auth_user")  # None if not authenticated
    if user:
        res.json({"feed": "personalized", "user": user["sub"]})
    else:
        res.json({"feed": "public"})
```

### Token Lifecycle

```python
# Refresh a token (preserves claims, resets expiry)
new_token = jwt.refresh(old_token)

# Revoke a token (adds to in-memory blacklist)
jwt.revoke(token)

# Custom expiry
short_token = jwt.encode({"sub": "1"}, expiry_seconds=300)  # 5 minutes
```

### Configuration Options

| Parameter        | Default          | Description                          |
|------------------|------------------|--------------------------------------|
| `secret`         | *(required)*     | HMAC-SHA256 signing key              |
| `algorithm`      | `"HS256"`        | Signing algorithm                    |
| `expiry_seconds` | `3600`           | Token lifetime in seconds            |
| `issuer`         | `None`           | Expected `iss` claim                 |
| `audience`       | `None`           | Expected `aud` claim                 |
| `header_name`    | `"Authorization"`| HTTP header to read token from       |
| `header_prefix`  | `"Bearer"`       | Required prefix before the token     |
| `auto_error`     | `True`           | Auto-respond 401 on failure          |

---

## API Key Authentication

### Setup

```python
from hypern import APIKeyAuth

api_key = APIKeyAuth(
    keys={
        "sk-abc123": "service-a",
        "sk-def456": "service-b",
    },
    header_name="X-API-Key",    # default
    query_param="api_key",      # also check query string
    cookie_name="api_key",      # also check cookies
)
```

### Protecting Routes

```python
@app.get("/api/data")
@api_key.required
def get_data(req, res, ctx):
    client = ctx.get("api_key_client")  # e.g. "service-a"
    res.json({"client": client, "data": [1, 2, 3]})
```

### Dynamic Key Management

```python
# Add a new key at runtime
api_key.add_key("sk-new999", "new-service")

# Remove a key
api_key.remove_key("sk-abc123")

# Validate programmatically
client = api_key.validate_key("sk-def456")  # "service-b" or None
```

### Extraction Priority

Keys are looked up in this order:

1. HTTP header (`X-API-Key` by default)
2. Query parameter (if `query_param` is set)
3. Cookie (if `cookie_name` is set)

---

## Role-Based Access Control (RBAC)

### Setup

```python
from hypern import RBACPolicy

rbac = RBACPolicy({
    "admin":  ["users:read", "users:write", "users:delete", "system:admin"],
    "editor": ["users:read", "users:write"],
    "viewer": ["users:read"],
})
```

### Role Enforcement

```python
@app.get("/users")
@jwt.required
@rbac.requires_role("viewer")          # any of these roles
def list_users(req, res, ctx):
    res.json({"users": get_all_users()})

@app.delete("/users/:id")
@jwt.required
@rbac.requires_role("admin")
def delete_user(req, res, ctx):
    delete_by_id(req.param("id"))
    res.status(204)
```

### Permission Enforcement

```python
@app.put("/users/:id")
@jwt.required
@rbac.requires_permission("users:write")
def update_user(req, res, ctx):
    data = req.json()
    res.json(update_by_id(req.param("id"), data))
```

### Multiple Roles / Permissions

```python
# Require ANY of these roles (default)
@rbac.requires_role("admin", "editor")

# Require ALL of these roles
@rbac.requires_role("admin", "editor", match_all=True)

# Require all permissions (default for permissions)
@rbac.requires_permission("users:read", "users:write")

# Require any permission
@rbac.requires_permission("users:read", "users:write", match_all=False)
```

### Dynamic Role Management

```python
# Add a new role
rbac.add_role("moderator", ["comments:delete", "users:read"])

# Grant additional permissions
rbac.grant("editor", "comments:delete")

# Revoke a permission
rbac.revoke("editor", "comments:delete")

# Remove a role entirely
rbac.remove_role("moderator")
```

### Programmatic Checks

```python
rbac.has_role(["admin", "viewer"], "admin")              # True
rbac.has_any_role(["viewer"], ["admin", "viewer"])        # True
rbac.has_all_roles(["admin"], ["admin", "editor"])        # False
rbac.has_permission(["editor"], "users:write")            # True
rbac.get_all_permissions(["editor", "viewer"])            # {"users:read", "users:write"}
```

---

## Standalone Decorators

For simple cases where you don't need a full `RBACPolicy` instance, use the standalone decorators. They read roles/permissions directly from `ctx.get("auth_user")`:

```python
from hypern import requires_role, requires_permission

@app.get("/admin")
@jwt.required
@requires_role("admin")
def admin_only(req, res, ctx):
    res.json({"admin": True})

@app.put("/articles/:id")
@jwt.required
@requires_permission("articles:write")
def update_article(req, res, ctx):
    ...
```

---

## OpenAPI Integration

When you use `@jwt.required`, `@rbac.requires_role(...)`, or `@rbac.requires_permission(...)`, Hypern's OpenAPI generator automatically:

- Marks the endpoint as requiring authentication
- Adds **Required roles** and **Required permissions** to the endpoint description

No additional configuration needed.

---

## Complete Example

```python
from hypern import Hypern, JWTAuth, APIKeyAuth, RBACPolicy, requires_role

app = Hypern()

jwt = JWTAuth(secret="super-secret-key", issuer="my-app")
api_key = APIKeyAuth(keys={"sk-prod-001": "frontend"})
rbac = RBACPolicy({
    "admin": ["users:*"],
    "user":  ["users:read"],
})

@app.post("/login")
def login(req, res, ctx):
    token = jwt.encode({"sub": "user-1", "roles": ["admin"]})
    res.json({"token": token})

@app.get("/profile")
@jwt.required
def profile(req, res, ctx):
    res.json(ctx.get("auth_user"))

@app.get("/admin/dashboard")
@jwt.required
@rbac.requires_role("admin")
def dashboard(req, res, ctx):
    res.json({"stats": "..."})

@app.get("/api/public")
@api_key.required
def public_api(req, res, ctx):
    res.json({"client": ctx.get("api_key_client")})

if __name__ == "__main__":
    app.start(host="0.0.0.0", port=8000)
```
