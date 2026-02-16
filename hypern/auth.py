"""
Authentication and Authorization module for Hypern.

Provides JWT authentication, API key authentication, and Role-Based Access Control (RBAC).

Example:
    from hypern.auth import JWTAuth, APIKeyAuth, requires_role, requires_permission

    # JWT Setup
    jwt = JWTAuth(secret="my-secret-key")

    @app.post("/login")
    def login(req, res, ctx):
        token = jwt.encode({"sub": "user123", "roles": ["admin"]})
        res.json({"token": token})

    @app.get("/protected")
    @jwt.required
    def protected(req, res, ctx):
        res.json({"user": ctx.get("auth_user")})

    # API Key Setup
    api_key = APIKeyAuth(keys={"my-api-key": "service-a"})

    @app.get("/api/data")
    @api_key.required
    def api_data(req, res, ctx):
        res.json({"client": ctx.get("api_key_client")})

    # RBAC
    @app.get("/admin")
    @jwt.required
    @requires_role("admin")
    def admin_only(req, res, ctx):
        res.json({"admin": True})
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import inspect
import time
import base64
import json
from typing import Any, Callable, Dict, List, Optional, Set


# ============================================================================
# JWT Authentication
# ============================================================================


class JWTAuth:
    """
    JSON Web Token (JWT) authentication handler.

    Supports HS256 signing with configurable token lifetime, issuer, and audience.
    Validates tokens from the ``Authorization: Bearer <token>`` header.

    Args:
        secret: The HMAC secret key for signing/verifying tokens.
        algorithm: Signing algorithm (currently only ``HS256``).
        expiry_seconds: Token lifetime in seconds (default 3600 = 1 hour).
        issuer: Optional ``iss`` claim value.
        audience: Optional ``aud`` claim value.
        header_name: HTTP header to read the token from.
        header_prefix: Expected prefix before the token (e.g. ``Bearer``).
        auto_error: If ``True``, respond with 401 automatically on failure.

    Example:
        jwt = JWTAuth(secret="super-secret")

        @app.post("/login")
        def login(req, res, ctx):
            token = jwt.encode({"sub": "user-1", "roles": ["admin"]})
            res.json({"token": token})

        @app.get("/me")
        @jwt.required
        def me(req, res, ctx):
            user = ctx.get("auth_user")
            res.json(user)
    """

    def __init__(
        self,
        secret: str,
        algorithm: str = "HS256",
        expiry_seconds: int = 3600,
        issuer: Optional[str] = None,
        audience: Optional[str] = None,
        header_name: str = "Authorization",
        header_prefix: str = "Bearer",
        auto_error: bool = True,
    ):
        self.secret = secret
        self.algorithm = algorithm
        self.expiry_seconds = expiry_seconds
        self.issuer = issuer
        self.audience = audience
        self.header_name = header_name
        self.header_prefix = header_prefix
        self.auto_error = auto_error

        # Token blacklist for revocation
        self._blacklist: Set[str] = set()

    # ------------------------------------------------------------------
    # Encoding helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _b64url_encode(data: bytes) -> str:
        """Base64url encode without padding."""
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    @staticmethod
    def _b64url_decode(s: str) -> bytes:
        """Base64url decode with padding restoration."""
        padding = 4 - len(s) % 4
        if padding != 4:
            s += "=" * padding
        return base64.urlsafe_b64decode(s)

    # ------------------------------------------------------------------
    # Token lifecycle
    # ------------------------------------------------------------------

    def encode(self, payload: Dict[str, Any], expiry_seconds: Optional[int] = None) -> str:
        """
        Create a signed JWT token.

        Args:
            payload: Claims to include in the token.
            expiry_seconds: Override the default expiry.

        Returns:
            The encoded JWT string.

        Example:
            token = jwt.encode({"sub": "user-1", "roles": ["admin"]})
        """
        now = int(time.time())
        exp = expiry_seconds if expiry_seconds is not None else self.expiry_seconds

        claims: Dict[str, Any] = {
            **payload,
            "iat": now,
            "exp": now + exp,
        }

        if self.issuer:
            claims.setdefault("iss", self.issuer)
        if self.audience:
            claims.setdefault("aud", self.audience)

        header = {"alg": self.algorithm, "typ": "JWT"}
        header_b64 = self._b64url_encode(json.dumps(header, separators=(",", ":")).encode())
        payload_b64 = self._b64url_encode(json.dumps(claims, separators=(",", ":")).encode())

        signing_input = f"{header_b64}.{payload_b64}"
        signature = hmac.new(
            self.secret.encode(), signing_input.encode(), hashlib.sha256
        ).digest()
        signature_b64 = self._b64url_encode(signature)

        return f"{signing_input}.{signature_b64}"

    def decode(self, token: str) -> Dict[str, Any]:
        """
        Decode and validate a JWT token.

        Args:
            token: The JWT string.

        Returns:
            The payload claims dictionary.

        Raises:
            JWTError: On any validation failure.

        Example:
            payload = jwt.decode(token)
            print(payload["sub"])
        """
        parts = token.split(".")
        if len(parts) != 3:
            raise JWTError("Invalid token format")

        header_b64, payload_b64, signature_b64 = parts

        # Verify signature
        signing_input = f"{header_b64}.{payload_b64}"
        expected_sig = hmac.new(
            self.secret.encode(), signing_input.encode(), hashlib.sha256
        ).digest()
        actual_sig = self._b64url_decode(signature_b64)

        if not hmac.compare_digest(expected_sig, actual_sig):
            raise JWTError("Invalid signature")

        # Decode payload
        try:
            payload = json.loads(self._b64url_decode(payload_b64))
        except (json.JSONDecodeError, Exception) as e:
            raise JWTError(f"Invalid payload: {e}")

        # Check blacklist
        jti = payload.get("jti", token[:32])
        if jti in self._blacklist:
            raise JWTError("Token has been revoked")

        # Validate expiry
        exp = payload.get("exp")
        if exp is not None and int(time.time()) > exp:
            raise JWTError("Token has expired")

        # Validate issuer
        if self.issuer and payload.get("iss") != self.issuer:
            raise JWTError("Invalid issuer")

        # Validate audience
        if self.audience:
            aud = payload.get("aud")
            if isinstance(aud, list):
                if self.audience not in aud:
                    raise JWTError("Invalid audience")
            elif aud != self.audience:
                raise JWTError("Invalid audience")

        return payload

    def revoke(self, token: str) -> None:
        """
        Revoke a token by adding its JTI (or prefix) to the blacklist.

        Args:
            token: The JWT to revoke.
        """
        try:
            payload = self.decode(token)
            jti = payload.get("jti", token[:32])
        except JWTError:
            jti = token[:32]
        self._blacklist.add(jti)

    def refresh(self, token: str, expiry_seconds: Optional[int] = None) -> str:
        """
        Refresh a token by creating a new one with the same claims.

        Args:
            token: The existing JWT.
            expiry_seconds: New expiry override.

        Returns:
            A new JWT string.
        """
        payload = self.decode(token)
        # Remove time-related claims so they are regenerated
        for key in ("iat", "exp", "nbf"):
            payload.pop(key, None)
        return self.encode(payload, expiry_seconds)

    # ------------------------------------------------------------------
    # Middleware / decorator
    # ------------------------------------------------------------------

    def _extract_token(self, req) -> Optional[str]:
        """Extract the JWT from the request header."""
        auth_header = req.header(self.header_name)
        if not auth_header:
            return None
        if self.header_prefix:
            prefix = f"{self.header_prefix} "
            if not auth_header.startswith(prefix):
                return None
            return auth_header[len(prefix):]
        return auth_header

    def required(self, func: Callable) -> Callable:
        """
        Decorator that enforces JWT authentication.

        On success the decoded payload is stored in ``ctx`` under the key
        ``auth_user`` and the ``ctx.set_auth()`` helper is called.

        Example:
            @app.get("/protected")
            @jwt.required
            def protected(req, res, ctx):
                user = ctx.get("auth_user")
                res.json(user)
        """

        @functools.wraps(func)
        async def async_wrapper(req, res, ctx, *args, **kwargs):
            token = self._extract_token(req)
            if not token:
                if self.auto_error:
                    res.status(401).json({"error": "unauthorized", "message": "Missing authentication token"})
                    return
                return await func(req, res, ctx, *args, **kwargs)

            try:
                payload = self.decode(token)
            except JWTError as e:
                if self.auto_error:
                    res.status(401).json({"error": "unauthorized", "message": str(e)})
                    return
                return await func(req, res, ctx, *args, **kwargs)

            # Populate context
            if ctx is not None:
                ctx.set("auth_user", payload)
                ctx.set("auth_token", token)
                user_id = payload.get("sub", payload.get("user_id"))
                roles = payload.get("roles", [])
                if user_id:
                    ctx.set_auth(str(user_id), roles)

            return await func(req, res, ctx, *args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(req, res, ctx, *args, **kwargs):
            token = self._extract_token(req)
            if not token:
                if self.auto_error:
                    res.status(401).json({"error": "unauthorized", "message": "Missing authentication token"})
                    return
                return func(req, res, ctx, *args, **kwargs)

            try:
                payload = self.decode(token)
            except JWTError as e:
                if self.auto_error:
                    res.status(401).json({"error": "unauthorized", "message": str(e)})
                    return
                return func(req, res, ctx, *args, **kwargs)

            if ctx is not None:
                ctx.set("auth_user", payload)
                ctx.set("auth_token", token)
                user_id = payload.get("sub", payload.get("user_id"))
                roles = payload.get("roles", [])
                if user_id:
                    ctx.set_auth(str(user_id), roles)

            return func(req, res, ctx, *args, **kwargs)

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    def optional(self, func: Callable) -> Callable:
        """
        Decorator that optionally decodes a JWT if present.

        Unlike :meth:`required`, this decorator **never** returns 401.
        If a valid token is present the payload is attached to ``ctx``;
        otherwise the handler runs without authentication context.

        Example:
            @app.get("/public")
            @jwt.optional
            def public_route(req, res, ctx):
                user = ctx.get("auth_user")  # may be None
                res.json({"authenticated": user is not None})
        """
        saved = self.auto_error
        self.auto_error = False

        @functools.wraps(func)
        async def async_wrapper(req, res, ctx, *args, **kwargs):
            token = self._extract_token(req)
            if token:
                try:
                    payload = self.decode(token)
                    if ctx is not None:
                        ctx.set("auth_user", payload)
                        ctx.set("auth_token", token)
                        user_id = payload.get("sub", payload.get("user_id"))
                        roles = payload.get("roles", [])
                        if user_id:
                            ctx.set_auth(str(user_id), roles)
                except JWTError:
                    pass
            return await func(req, res, ctx, *args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(req, res, ctx, *args, **kwargs):
            token = self._extract_token(req)
            if token:
                try:
                    payload = self.decode(token)
                    if ctx is not None:
                        ctx.set("auth_user", payload)
                        ctx.set("auth_token", token)
                        user_id = payload.get("sub", payload.get("user_id"))
                        roles = payload.get("roles", [])
                        if user_id:
                            ctx.set_auth(str(user_id), roles)
                except JWTError:
                    pass
            return func(req, res, ctx, *args, **kwargs)

        self.auto_error = saved

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper


class JWTError(Exception):
    """Raised when JWT validation fails."""

    def __init__(self, message: str = "JWT validation failed"):
        self.message = message
        super().__init__(message)


# ============================================================================
# API Key Authentication
# ============================================================================


class APIKeyAuth:
    """
    API Key authentication handler.

    Validates API keys from a header, query parameter, or cookie.

    Args:
        keys: A mapping of ``{api_key: client_name}``.
        header_name: Header to read the key from.
        query_param: Query parameter name (alternative).
        cookie_name: Cookie name (alternative).
        auto_error: Return 401 automatically on failure.

    Example:
        api_key = APIKeyAuth(keys={"sk-abc123": "service-a"})

        @app.get("/data")
        @api_key.required
        def get_data(req, res, ctx):
            client = ctx.get("api_key_client")
            res.json({"client": client})
    """

    def __init__(
        self,
        keys: Optional[Dict[str, str]] = None,
        header_name: str = "X-API-Key",
        query_param: Optional[str] = None,
        cookie_name: Optional[str] = None,
        auto_error: bool = True,
    ):
        self._keys: Dict[str, str] = keys or {}
        self.header_name = header_name
        self.query_param = query_param
        self.cookie_name = cookie_name
        self.auto_error = auto_error

    def add_key(self, key: str, client_name: str) -> None:
        """Register a new API key."""
        self._keys[key] = client_name

    def remove_key(self, key: str) -> bool:
        """Remove an API key. Returns True if removed."""
        return self._keys.pop(key, None) is not None

    def validate_key(self, key: str) -> Optional[str]:
        """
        Validate an API key and return the associated client name.

        Returns:
            The client name, or ``None`` if invalid.
        """
        return self._keys.get(key)

    def _extract_key(self, req) -> Optional[str]:
        """Extract the API key from the request."""
        # 1. Header
        key = req.header(self.header_name)
        if key:
            return key
        # 2. Query parameter
        if self.query_param:
            key = req.query(self.query_param)
            if key:
                return key
        # 3. Cookie
        if self.cookie_name:
            key = req.cookie(self.cookie_name)
            if key:
                return key
        return None

    def required(self, func: Callable) -> Callable:
        """
        Decorator that enforces API key authentication.

        On success ``ctx`` is populated with ``api_key_client``.

        Example:
            @app.get("/service")
            @api_key.required
            def service_endpoint(req, res, ctx):
                client = ctx.get("api_key_client")
                res.json({"client": client})
        """

        @functools.wraps(func)
        async def async_wrapper(req, res, ctx, *args, **kwargs):
            key = self._extract_key(req)
            if not key:
                if self.auto_error:
                    res.status(401).json({"error": "unauthorized", "message": "Missing API key"})
                    return
                return await func(req, res, ctx, *args, **kwargs)

            client = self.validate_key(key)
            if client is None:
                if self.auto_error:
                    res.status(401).json({"error": "unauthorized", "message": "Invalid API key"})
                    return
                return await func(req, res, ctx, *args, **kwargs)

            if ctx is not None:
                ctx.set("api_key", key)
                ctx.set("api_key_client", client)

            return await func(req, res, ctx, *args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(req, res, ctx, *args, **kwargs):
            key = self._extract_key(req)
            if not key:
                if self.auto_error:
                    res.status(401).json({"error": "unauthorized", "message": "Missing API key"})
                    return
                return func(req, res, ctx, *args, **kwargs)

            client = self.validate_key(key)
            if client is None:
                if self.auto_error:
                    res.status(401).json({"error": "unauthorized", "message": "Invalid API key"})
                    return
                return func(req, res, ctx, *args, **kwargs)

            if ctx is not None:
                ctx.set("api_key", key)
                ctx.set("api_key_client", client)

            return func(req, res, ctx, *args, **kwargs)

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper


# ============================================================================
# Role-Based Access Control (RBAC)
# ============================================================================


class RBACPolicy:
    """
    Role-Based Access Control policy manager.

    Manages roles, permissions, and role-permission mappings.

    Args:
        roles: Initial mapping of ``{role_name: [permission, ...]}``.

    Example:
        rbac = RBACPolicy({
            "admin": ["users:read", "users:write", "users:delete"],
            "editor": ["users:read", "users:write"],
            "viewer": ["users:read"],
        })

        @app.get("/users")
        @jwt.required
        @rbac.requires_role("viewer")
        def list_users(req, res, ctx):
            ...

        @app.delete("/users/:id")
        @jwt.required
        @rbac.requires_permission("users:delete")
        def delete_user(req, res, ctx):
            ...
    """

    def __init__(self, roles: Optional[Dict[str, List[str]]] = None):
        self._roles: Dict[str, Set[str]] = {}
        if roles:
            for role, perms in roles.items():
                self._roles[role] = set(perms)

    def add_role(self, role: str, permissions: Optional[List[str]] = None) -> None:
        """Define a new role with optional permissions."""
        self._roles[role] = set(permissions or [])

    def remove_role(self, role: str) -> bool:
        """Remove a role definition."""
        return self._roles.pop(role, None) is not None

    def grant(self, role: str, *permissions: str) -> None:
        """Grant permissions to a role."""
        if role not in self._roles:
            self._roles[role] = set()
        self._roles[role].update(permissions)

    def revoke(self, role: str, *permissions: str) -> None:
        """Revoke permissions from a role."""
        if role in self._roles:
            self._roles[role] -= set(permissions)

    def get_permissions(self, role: str) -> Set[str]:
        """Get all permissions for a role."""
        return self._roles.get(role, set()).copy()

    def get_all_permissions(self, roles: List[str]) -> Set[str]:
        """Get the union of permissions for multiple roles."""
        perms: Set[str] = set()
        for role in roles:
            perms |= self._roles.get(role, set())
        return perms

    def has_role(self, user_roles: List[str], required_role: str) -> bool:
        """Check if the user has a specific role."""
        return required_role in user_roles

    def has_any_role(self, user_roles: List[str], required_roles: List[str]) -> bool:
        """Check if the user has any of the required roles."""
        return bool(set(user_roles) & set(required_roles))

    def has_all_roles(self, user_roles: List[str], required_roles: List[str]) -> bool:
        """Check if the user has all required roles."""
        return set(required_roles) <= set(user_roles)

    def has_permission(self, user_roles: List[str], permission: str) -> bool:
        """Check if any of the user's roles grant a specific permission."""
        return permission in self.get_all_permissions(user_roles)

    def has_any_permission(self, user_roles: List[str], permissions: List[str]) -> bool:
        """Check if any of the user's roles grant any of the permissions."""
        user_perms = self.get_all_permissions(user_roles)
        return bool(user_perms & set(permissions))

    def has_all_permissions(self, user_roles: List[str], permissions: List[str]) -> bool:
        """Check if the user's roles grant all required permissions."""
        user_perms = self.get_all_permissions(user_roles)
        return set(permissions) <= user_perms

    # ------------------------------------------------------------------
    # Decorators
    # ------------------------------------------------------------------

    def requires_role(self, *roles: str, match_all: bool = False) -> Callable:
        """
        Decorator enforcing that the authenticated user has one (or all) of
        the specified roles.

        Reads roles from ``ctx.get("auth_user")["roles"]``.

        Args:
            roles: Required role(s).
            match_all: If ``True``, all roles must be present.

        Example:
            @rbac.requires_role("admin")
            def admin_endpoint(req, res, ctx):
                ...
        """
        required = list(roles)

        def decorator(func: Callable) -> Callable:
            # Mark for OpenAPI
            func._requires_auth = True
            func._required_roles = required

            @functools.wraps(func)
            async def async_wrapper(req, res, ctx, *args, **kwargs):
                user_roles = self._get_user_roles(ctx)
                if user_roles is None:
                    res.status(401).json({"error": "unauthorized", "message": "Authentication required"})
                    return
                ok = self.has_all_roles(user_roles, required) if match_all else self.has_any_role(user_roles, required)
                if not ok:
                    res.status(403).json({"error": "forbidden", "message": f"Required role(s): {', '.join(required)}"})
                    return
                return await func(req, res, ctx, *args, **kwargs)

            @functools.wraps(func)
            def sync_wrapper(req, res, ctx, *args, **kwargs):
                user_roles = self._get_user_roles(ctx)
                if user_roles is None:
                    res.status(401).json({"error": "unauthorized", "message": "Authentication required"})
                    return
                ok = self.has_all_roles(user_roles, required) if match_all else self.has_any_role(user_roles, required)
                if not ok:
                    res.status(403).json({"error": "forbidden", "message": f"Required role(s): {', '.join(required)}"})
                    return
                return func(req, res, ctx, *args, **kwargs)

            if inspect.iscoroutinefunction(func):
                return async_wrapper
            return sync_wrapper

        return decorator

    def requires_permission(self, *permissions: str, match_all: bool = True) -> Callable:
        """
        Decorator enforcing that the authenticated user has the required
        permission(s) through their roles.

        Args:
            permissions: Required permission(s).
            match_all: If ``True``, all permissions must be present (default).

        Example:
            @rbac.requires_permission("users:write")
            def update_user(req, res, ctx):
                ...
        """
        required = list(permissions)

        def decorator(func: Callable) -> Callable:
            func._requires_auth = True
            func._required_permissions = required

            @functools.wraps(func)
            async def async_wrapper(req, res, ctx, *args, **kwargs):
                user_roles = self._get_user_roles(ctx)
                if user_roles is None:
                    res.status(401).json({"error": "unauthorized", "message": "Authentication required"})
                    return
                ok = self.has_all_permissions(user_roles, required) if match_all else self.has_any_permission(user_roles, required)
                if not ok:
                    res.status(403).json({"error": "forbidden", "message": f"Required permission(s): {', '.join(required)}"})
                    return
                return await func(req, res, ctx, *args, **kwargs)

            @functools.wraps(func)
            def sync_wrapper(req, res, ctx, *args, **kwargs):
                user_roles = self._get_user_roles(ctx)
                if user_roles is None:
                    res.status(401).json({"error": "unauthorized", "message": "Authentication required"})
                    return
                ok = self.has_all_permissions(user_roles, required) if match_all else self.has_any_permission(user_roles, required)
                if not ok:
                    res.status(403).json({"error": "forbidden", "message": f"Required permission(s): {', '.join(required)}"})
                    return
                return func(req, res, ctx, *args, **kwargs)

            if inspect.iscoroutinefunction(func):
                return async_wrapper
            return sync_wrapper

        return decorator

    @staticmethod
    def _get_user_roles(ctx) -> Optional[List[str]]:
        """Extract user roles from the request context."""
        if ctx is None:
            return None
        auth_user = ctx.get("auth_user")
        if auth_user is None:
            return None
        if isinstance(auth_user, dict):
            return auth_user.get("roles", [])
        return getattr(auth_user, "roles", [])


# ============================================================================
# Standalone decorators (convenience)
# ============================================================================


def requires_role(*roles: str, match_all: bool = False) -> Callable:
    """
    Standalone decorator to require role(s) from ``ctx.get("auth_user")["roles"]``.

    This does **not** require an :class:`RBACPolicy` instance.

    Example:
        @jwt.required
        @requires_role("admin")
        def admin_only(req, res, ctx):
            ...
    """

    def decorator(func: Callable) -> Callable:
        func._requires_auth = True
        func._required_roles = list(roles)
        required = list(roles)

        @functools.wraps(func)
        async def async_wrapper(req, res, ctx, *args, **kwargs):
            user_roles = _extract_roles(ctx)
            if user_roles is None:
                res.status(401).json({"error": "unauthorized", "message": "Authentication required"})
                return
            if match_all:
                if not set(required) <= set(user_roles):
                    res.status(403).json({"error": "forbidden", "message": f"Required role(s): {', '.join(required)}"})
                    return
            else:
                if not set(required) & set(user_roles):
                    res.status(403).json({"error": "forbidden", "message": f"Required role(s): {', '.join(required)}"})
                    return
            return await func(req, res, ctx, *args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(req, res, ctx, *args, **kwargs):
            user_roles = _extract_roles(ctx)
            if user_roles is None:
                res.status(401).json({"error": "unauthorized", "message": "Authentication required"})
                return
            if match_all:
                if not set(required) <= set(user_roles):
                    res.status(403).json({"error": "forbidden", "message": f"Required role(s): {', '.join(required)}"})
                    return
            else:
                if not set(required) & set(user_roles):
                    res.status(403).json({"error": "forbidden", "message": f"Required role(s): {', '.join(required)}"})
                    return
            return func(req, res, ctx, *args, **kwargs)

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def requires_permission(*permissions: str, match_all: bool = True) -> Callable:
    """
    Standalone decorator to require permission(s).

    Permissions are looked up from ``ctx.get("auth_user")["permissions"]``.

    Example:
        @jwt.required
        @requires_permission("users:write")
        def write_users(req, res, ctx):
            ...
    """

    def decorator(func: Callable) -> Callable:
        func._requires_auth = True
        func._required_permissions = list(permissions)
        required = set(permissions)

        @functools.wraps(func)
        async def async_wrapper(req, res, ctx, *args, **kwargs):
            user_perms = _extract_permissions(ctx)
            if user_perms is None:
                res.status(401).json({"error": "unauthorized", "message": "Authentication required"})
                return
            if match_all:
                if not required <= user_perms:
                    res.status(403).json({"error": "forbidden", "message": f"Required permission(s): {', '.join(required)}"})
                    return
            else:
                if not required & user_perms:
                    res.status(403).json({"error": "forbidden", "message": f"Required permission(s): {', '.join(required)}"})
                    return
            return await func(req, res, ctx, *args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(req, res, ctx, *args, **kwargs):
            user_perms = _extract_permissions(ctx)
            if user_perms is None:
                res.status(401).json({"error": "unauthorized", "message": "Authentication required"})
                return
            if match_all:
                if not required <= user_perms:
                    res.status(403).json({"error": "forbidden", "message": f"Required permission(s): {', '.join(required)}"})
                    return
            else:
                if not required & user_perms:
                    res.status(403).json({"error": "forbidden", "message": f"Required permission(s): {', '.join(required)}"})
                    return
            return func(req, res, ctx, *args, **kwargs)

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def _extract_roles(ctx) -> Optional[List[str]]:
    """Extract roles from context (auth_user dict or object)."""
    if ctx is None:
        return None
    auth_user = ctx.get("auth_user")
    if auth_user is None:
        return None
    if isinstance(auth_user, dict):
        return auth_user.get("roles", [])
    return getattr(auth_user, "roles", [])


def _extract_permissions(ctx) -> Optional[set]:
    """Extract permissions from context."""
    if ctx is None:
        return None
    auth_user = ctx.get("auth_user")
    if auth_user is None:
        return None
    if isinstance(auth_user, dict):
        perms = auth_user.get("permissions", [])
    else:
        perms = getattr(auth_user, "permissions", [])
    return set(perms)


__all__ = [
    "JWTAuth",
    "JWTError",
    "APIKeyAuth",
    "RBACPolicy",
    "requires_role",
    "requires_permission",
]
