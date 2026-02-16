"""
Tests for Hypern Auth module (JWT, API Key, RBAC).

These are unit tests that do NOT require a running server — they test
the auth module's logic directly.
"""

import time
import json
import pytest
from unittest.mock import MagicMock, PropertyMock

from hypern.auth import (
    JWTAuth,
    JWTError,
    APIKeyAuth,
    RBACPolicy,
    requires_role,
    requires_permission,
)


# Override autouse fixtures from conftest that require the test server
@pytest.fixture(autouse=True)
def reset_database():
    yield


# ============================================================================
# Helpers
# ============================================================================


def make_ctx():
    """Create a mock context with set/get/has/set_auth."""
    ctx = MagicMock()
    _store = {}

    def _set(key, value):
        _store[key] = value

    def _get(key):
        return _store.get(key)

    def _has(key):
        return key in _store

    def _set_auth(uid, roles=None):
        _store["_user_id"] = uid
        _store["_roles"] = roles or []

    ctx.set = MagicMock(side_effect=_set)
    ctx.get = MagicMock(side_effect=_get)
    ctx.has = MagicMock(side_effect=_has)
    ctx.set_auth = MagicMock(side_effect=_set_auth)
    ctx._store = _store
    return ctx


def make_req(headers=None, cookies=None, queries=None):
    """Create a mock request object."""
    _headers = headers or {}
    _cookies = cookies or {}
    _queries = queries or {}

    req = MagicMock()
    req.header = MagicMock(side_effect=lambda k: _headers.get(k))
    req.cookie = MagicMock(side_effect=lambda k: _cookies.get(k))
    req.query = MagicMock(side_effect=lambda k: _queries.get(k))
    return req


def make_res():
    """Create a mock response object with chaining."""
    res = MagicMock()
    res.status = MagicMock(return_value=res)
    res.json = MagicMock(return_value=res)
    res.header = MagicMock(return_value=res)
    return res


# ============================================================================
# JWT Tests
# ============================================================================


class TestJWTAuth:
    """Test JWT encoding, decoding, and validation."""

    def setup_method(self):
        self.jwt = JWTAuth(secret="test-secret-key-123")

    def test_encode_decode_roundtrip(self):
        """Token should encode and decode successfully."""
        payload = {"sub": "user-1", "name": "Alice"}
        token = self.jwt.encode(payload)

        decoded = self.jwt.decode(token)
        assert decoded["sub"] == "user-1"
        assert decoded["name"] == "Alice"
        assert "iat" in decoded
        assert "exp" in decoded

    def test_token_format(self):
        """JWT should have three dot-separated parts."""
        token = self.jwt.encode({"sub": "1"})
        parts = token.split(".")
        assert len(parts) == 3

    def test_expired_token(self):
        """Expired tokens should raise JWTError."""
        token = self.jwt.encode({"sub": "1"}, expiry_seconds=-1)
        with pytest.raises(JWTError, match="expired"):
            self.jwt.decode(token)

    def test_invalid_signature(self):
        """Tampered tokens should fail verification."""
        token = self.jwt.encode({"sub": "1"})
        # Tamper with the signature
        parts = token.split(".")
        parts[2] = parts[2][::-1]  # reverse signature
        tampered = ".".join(parts)

        with pytest.raises(JWTError, match="signature"):
            self.jwt.decode(tampered)

    def test_invalid_format(self):
        """Tokens without three parts should fail."""
        with pytest.raises(JWTError, match="format"):
            self.jwt.decode("not.a.valid.token.at.all")

        with pytest.raises(JWTError, match="format"):
            self.jwt.decode("singlepart")

    def test_different_secrets_fail(self):
        """Token signed with a different secret should fail."""
        other_jwt = JWTAuth(secret="other-secret")
        token = other_jwt.encode({"sub": "1"})

        with pytest.raises(JWTError, match="signature"):
            self.jwt.decode(token)

    def test_custom_expiry(self):
        """Custom expiry should be reflected in the token."""
        token = self.jwt.encode({"sub": "1"}, expiry_seconds=7200)
        decoded = self.jwt.decode(token)
        # exp should be ~2 hours from iat
        assert decoded["exp"] - decoded["iat"] == 7200

    def test_issuer_validation(self):
        """Token with wrong issuer should fail when issuer is configured."""
        jwt_with_iss = JWTAuth(secret="s", issuer="my-app")
        token = jwt_with_iss.encode({"sub": "1"})

        # Valid issuer
        decoded = jwt_with_iss.decode(token)
        assert decoded["iss"] == "my-app"

        # Different issuer requirement
        other_jwt = JWTAuth(secret="s", issuer="other-app")
        with pytest.raises(JWTError, match="issuer"):
            other_jwt.decode(token)

    def test_audience_validation(self):
        """Token with wrong audience should fail."""
        jwt_aud = JWTAuth(secret="s", audience="web-app")
        token = jwt_aud.encode({"sub": "1"})

        decoded = jwt_aud.decode(token)
        assert decoded["aud"] == "web-app"

        other_jwt = JWTAuth(secret="s", audience="mobile-app")
        with pytest.raises(JWTError, match="audience"):
            other_jwt.decode(token)

    def test_revoke_token(self):
        """Revoked tokens should be rejected."""
        token = self.jwt.encode({"sub": "1"})
        # Valid before revocation
        self.jwt.decode(token)
        # Revoke
        self.jwt.revoke(token)
        # Should fail after revocation
        with pytest.raises(JWTError, match="revoked"):
            self.jwt.decode(token)

    def test_refresh_token(self):
        """Refreshed token should have the same claims but new timestamps."""
        original = self.jwt.encode({"sub": "1", "roles": ["admin"]})
        time.sleep(0.01)
        refreshed = self.jwt.refresh(original)

        decoded = self.jwt.decode(refreshed)
        assert decoded["sub"] == "1"
        assert decoded["roles"] == ["admin"]

    def test_encode_with_custom_claims(self):
        """Custom claims should be preserved."""
        payload = {"sub": "1", "custom_field": "value", "nested": {"a": 1}}
        token = self.jwt.encode(payload)
        decoded = self.jwt.decode(token)
        assert decoded["custom_field"] == "value"
        assert decoded["nested"] == {"a": 1}


class TestJWTRequiredDecorator:
    """Test the @jwt.required decorator."""

    def setup_method(self):
        self.jwt = JWTAuth(secret="test-secret")

    def test_missing_token_returns_401(self):
        """Missing token should return 401."""
        req = make_req()
        res = make_res()
        ctx = make_ctx()

        @self.jwt.required
        def handler(req, res, ctx):
            res.json({"ok": True})

        handler(req, res, ctx)
        res.status.assert_called_with(401)

    def test_invalid_token_returns_401(self):
        """Invalid token should return 401."""
        req = make_req(headers={"Authorization": "Bearer invalid.token.here"})
        res = make_res()
        ctx = make_ctx()

        @self.jwt.required
        def handler(req, res, ctx):
            res.json({"ok": True})

        handler(req, res, ctx)
        res.status.assert_called_with(401)

    def test_valid_token_passes(self):
        """Valid token should allow the handler to run."""
        token = self.jwt.encode({"sub": "user-1", "roles": ["admin"]})
        req = make_req(headers={"Authorization": f"Bearer {token}"})
        res = make_res()
        ctx = make_ctx()

        handler_called = False

        @self.jwt.required
        def handler(req, res, ctx):
            nonlocal handler_called
            handler_called = True
            res.json({"user": ctx.get("auth_user")["sub"]})

        handler(req, res, ctx)
        assert handler_called
        # ctx.set should have been called with auth_user
        assert ctx._store.get("auth_user") is not None
        assert ctx._store["auth_user"]["sub"] == "user-1"

    def test_context_sets_auth(self):
        """The decorator should call ctx.set_auth with user_id and roles."""
        token = self.jwt.encode({"sub": "uid-42", "roles": ["editor"]})
        req = make_req(headers={"Authorization": f"Bearer {token}"})
        res = make_res()
        ctx = make_ctx()

        @self.jwt.required
        def handler(req, res, ctx):
            pass

        handler(req, res, ctx)
        ctx.set_auth.assert_called_once_with("uid-42", ["editor"])

    def test_wrong_prefix_returns_401(self):
        """Token with wrong Authorization prefix should fail."""
        token = self.jwt.encode({"sub": "1"})
        req = make_req(headers={"Authorization": f"Token {token}"})
        res = make_res()
        ctx = make_ctx()

        @self.jwt.required
        def handler(req, res, ctx):
            pass

        handler(req, res, ctx)
        res.status.assert_called_with(401)

    def test_expired_token_returns_401(self):
        """Expired token should return 401."""
        token = self.jwt.encode({"sub": "1"}, expiry_seconds=-1)
        req = make_req(headers={"Authorization": f"Bearer {token}"})
        res = make_res()
        ctx = make_ctx()

        @self.jwt.required
        def handler(req, res, ctx):
            pass

        handler(req, res, ctx)
        res.status.assert_called_with(401)


class TestJWTOptionalDecorator:
    """Test the @jwt.optional decorator."""

    def setup_method(self):
        self.jwt = JWTAuth(secret="test-secret")

    def test_no_token_still_runs(self):
        """Handler should run even without a token."""
        req = make_req()
        res = make_res()
        ctx = make_ctx()
        called = False

        @self.jwt.optional
        def handler(req, res, ctx):
            nonlocal called
            called = True

        handler(req, res, ctx)
        assert called

    def test_valid_token_populates_ctx(self):
        """With a valid token, auth_user should be set."""
        token = self.jwt.encode({"sub": "user-1"})
        req = make_req(headers={"Authorization": f"Bearer {token}"})
        res = make_res()
        ctx = make_ctx()

        @self.jwt.optional
        def handler(req, res, ctx):
            pass

        handler(req, res, ctx)
        assert ctx._store.get("auth_user") is not None

    def test_invalid_token_still_runs(self):
        """Invalid token should not block the handler."""
        req = make_req(headers={"Authorization": "Bearer bad.token.here"})
        res = make_res()
        ctx = make_ctx()
        called = False

        @self.jwt.optional
        def handler(req, res, ctx):
            nonlocal called
            called = True

        handler(req, res, ctx)
        assert called
        assert ctx._store.get("auth_user") is None


# ============================================================================
# API Key Tests
# ============================================================================


class TestAPIKeyAuth:
    """Test API key authentication."""

    def setup_method(self):
        self.api_key_auth = APIKeyAuth(keys={
            "sk-abc123": "service-a",
            "sk-def456": "service-b",
        })

    def test_valid_key_from_header(self):
        """Valid API key in header should authenticate."""
        req = make_req(headers={"X-API-Key": "sk-abc123"})
        res = make_res()
        ctx = make_ctx()
        called = False

        @self.api_key_auth.required
        def handler(req, res, ctx):
            nonlocal called
            called = True

        handler(req, res, ctx)
        assert called
        assert ctx._store.get("api_key_client") == "service-a"

    def test_invalid_key_returns_401(self):
        """Invalid API key should return 401."""
        req = make_req(headers={"X-API-Key": "sk-invalid"})
        res = make_res()
        ctx = make_ctx()

        @self.api_key_auth.required
        def handler(req, res, ctx):
            pass

        handler(req, res, ctx)
        res.status.assert_called_with(401)

    def test_missing_key_returns_401(self):
        """Missing API key should return 401."""
        req = make_req()
        res = make_res()
        ctx = make_ctx()

        @self.api_key_auth.required
        def handler(req, res, ctx):
            pass

        handler(req, res, ctx)
        res.status.assert_called_with(401)

    def test_key_from_query_param(self):
        """API key from query parameter should work."""
        api_key = APIKeyAuth(
            keys={"qk-123": "query-client"},
            query_param="api_key",
        )
        req = make_req(queries={"api_key": "qk-123"})
        res = make_res()
        ctx = make_ctx()
        called = False

        @api_key.required
        def handler(req, res, ctx):
            nonlocal called
            called = True

        handler(req, res, ctx)
        assert called
        assert ctx._store.get("api_key_client") == "query-client"

    def test_key_from_cookie(self):
        """API key from cookie should work."""
        api_key = APIKeyAuth(
            keys={"ck-789": "cookie-client"},
            cookie_name="api_key",
        )
        req = make_req(cookies={"api_key": "ck-789"})
        res = make_res()
        ctx = make_ctx()
        called = False

        @api_key.required
        def handler(req, res, ctx):
            nonlocal called
            called = True

        handler(req, res, ctx)
        assert called

    def test_add_and_remove_key(self):
        """Keys can be added and removed dynamically."""
        self.api_key_auth.add_key("sk-new", "new-client")
        assert self.api_key_auth.validate_key("sk-new") == "new-client"

        assert self.api_key_auth.remove_key("sk-new") is True
        assert self.api_key_auth.validate_key("sk-new") is None

    def test_remove_nonexistent_key(self):
        """Removing a nonexistent key returns False."""
        assert self.api_key_auth.remove_key("sk-nope") is False

    def test_custom_header_name(self):
        """Custom header name should work."""
        api_key = APIKeyAuth(
            keys={"key-1": "client-1"},
            header_name="Authorization",
        )
        req = make_req(headers={"Authorization": "key-1"})
        res = make_res()
        ctx = make_ctx()
        called = False

        @api_key.required
        def handler(req, res, ctx):
            nonlocal called
            called = True

        handler(req, res, ctx)
        assert called


# ============================================================================
# RBAC Tests
# ============================================================================


class TestRBACPolicy:
    """Test Role-Based Access Control."""

    def setup_method(self):
        self.rbac = RBACPolicy({
            "admin": ["users:read", "users:write", "users:delete", "system:admin"],
            "editor": ["users:read", "users:write"],
            "viewer": ["users:read"],
        })

    def test_has_role(self):
        assert self.rbac.has_role(["admin", "viewer"], "admin") is True
        assert self.rbac.has_role(["viewer"], "admin") is False

    def test_has_any_role(self):
        assert self.rbac.has_any_role(["viewer"], ["admin", "viewer"]) is True
        assert self.rbac.has_any_role(["viewer"], ["admin", "editor"]) is False

    def test_has_all_roles(self):
        assert self.rbac.has_all_roles(["admin", "editor"], ["admin", "editor"]) is True
        assert self.rbac.has_all_roles(["admin"], ["admin", "editor"]) is False

    def test_get_permissions(self):
        perms = self.rbac.get_permissions("admin")
        assert "users:read" in perms
        assert "users:delete" in perms
        assert "system:admin" in perms

    def test_get_all_permissions_multi_role(self):
        perms = self.rbac.get_all_permissions(["editor", "viewer"])
        assert "users:read" in perms
        assert "users:write" in perms
        assert "users:delete" not in perms

    def test_has_permission(self):
        assert self.rbac.has_permission(["editor"], "users:write") is True
        assert self.rbac.has_permission(["viewer"], "users:write") is False

    def test_has_any_permission(self):
        assert self.rbac.has_any_permission(["viewer"], ["users:read", "users:delete"]) is True
        assert self.rbac.has_any_permission(["viewer"], ["users:write", "users:delete"]) is False

    def test_has_all_permissions(self):
        assert self.rbac.has_all_permissions(["admin"], ["users:read", "users:write"]) is True
        assert self.rbac.has_all_permissions(["viewer"], ["users:read", "users:write"]) is False

    def test_add_role(self):
        self.rbac.add_role("moderator", ["users:read", "comments:delete"])
        assert self.rbac.has_permission(["moderator"], "comments:delete") is True

    def test_remove_role(self):
        self.rbac.add_role("temp")
        assert self.rbac.remove_role("temp") is True
        assert self.rbac.remove_role("temp") is False

    def test_grant_permission(self):
        self.rbac.grant("viewer", "users:write")
        assert self.rbac.has_permission(["viewer"], "users:write") is True

    def test_revoke_permission(self):
        self.rbac.revoke("admin", "system:admin")
        assert self.rbac.has_permission(["admin"], "system:admin") is False


class TestRBACDecorators:
    """Test RBAC decorator enforcement."""

    def setup_method(self):
        self.rbac = RBACPolicy({
            "admin": ["users:read", "users:write", "users:delete"],
            "editor": ["users:read", "users:write"],
            "viewer": ["users:read"],
        })

    def test_requires_role_passes(self):
        """User with the required role should pass."""
        req = make_req()
        res = make_res()
        ctx = make_ctx()
        ctx._store["auth_user"] = {"sub": "1", "roles": ["admin"]}
        called = False

        @self.rbac.requires_role("admin")
        def handler(req, res, ctx):
            nonlocal called
            called = True

        handler(req, res, ctx)
        assert called

    def test_requires_role_fails(self):
        """User without the required role should get 403."""
        req = make_req()
        res = make_res()
        ctx = make_ctx()
        ctx._store["auth_user"] = {"sub": "1", "roles": ["viewer"]}

        @self.rbac.requires_role("admin")
        def handler(req, res, ctx):
            pass

        handler(req, res, ctx)
        res.status.assert_called_with(403)

    def test_requires_role_no_auth(self):
        """No auth_user in context should return 401."""
        req = make_req()
        res = make_res()
        ctx = make_ctx()

        @self.rbac.requires_role("admin")
        def handler(req, res, ctx):
            pass

        handler(req, res, ctx)
        res.status.assert_called_with(401)

    def test_requires_any_role(self):
        """User with any of the required roles should pass."""
        req = make_req()
        res = make_res()
        ctx = make_ctx()
        ctx._store["auth_user"] = {"sub": "1", "roles": ["editor"]}
        called = False

        @self.rbac.requires_role("admin", "editor")
        def handler(req, res, ctx):
            nonlocal called
            called = True

        handler(req, res, ctx)
        assert called

    def test_requires_all_roles(self):
        """match_all=True requires all roles."""
        req = make_req()
        res = make_res()
        ctx = make_ctx()
        ctx._store["auth_user"] = {"sub": "1", "roles": ["admin"]}

        @self.rbac.requires_role("admin", "editor", match_all=True)
        def handler(req, res, ctx):
            pass

        handler(req, res, ctx)
        res.status.assert_called_with(403)

    def test_requires_permission_passes(self):
        """User with the required permission should pass."""
        req = make_req()
        res = make_res()
        ctx = make_ctx()
        ctx._store["auth_user"] = {"sub": "1", "roles": ["editor"]}
        called = False

        @self.rbac.requires_permission("users:write")
        def handler(req, res, ctx):
            nonlocal called
            called = True

        handler(req, res, ctx)
        assert called

    def test_requires_permission_fails(self):
        """User without the required permission should get 403."""
        req = make_req()
        res = make_res()
        ctx = make_ctx()
        ctx._store["auth_user"] = {"sub": "1", "roles": ["viewer"]}

        @self.rbac.requires_permission("users:delete")
        def handler(req, res, ctx):
            pass

        handler(req, res, ctx)
        res.status.assert_called_with(403)


# ============================================================================
# Standalone Decorator Tests
# ============================================================================


class TestStandaloneDecorators:
    """Test the standalone requires_role and requires_permission decorators."""

    def test_standalone_requires_role(self):
        req = make_req()
        res = make_res()
        ctx = make_ctx()
        ctx._store["auth_user"] = {"sub": "1", "roles": ["admin"]}
        called = False

        @requires_role("admin")
        def handler(req, res, ctx):
            nonlocal called
            called = True

        handler(req, res, ctx)
        assert called

    def test_standalone_requires_role_fails(self):
        req = make_req()
        res = make_res()
        ctx = make_ctx()
        ctx._store["auth_user"] = {"sub": "1", "roles": ["viewer"]}

        @requires_role("admin")
        def handler(req, res, ctx):
            pass

        handler(req, res, ctx)
        res.status.assert_called_with(403)

    def test_standalone_requires_permission(self):
        req = make_req()
        res = make_res()
        ctx = make_ctx()
        ctx._store["auth_user"] = {"sub": "1", "permissions": ["users:write"]}
        called = False

        @requires_permission("users:write")
        def handler(req, res, ctx):
            nonlocal called
            called = True

        handler(req, res, ctx)
        assert called

    def test_standalone_requires_permission_fails(self):
        req = make_req()
        res = make_res()
        ctx = make_ctx()
        ctx._store["auth_user"] = {"sub": "1", "permissions": ["users:read"]}

        @requires_permission("users:write")
        def handler(req, res, ctx):
            pass

        handler(req, res, ctx)
        res.status.assert_called_with(403)

    def test_standalone_no_auth_returns_401(self):
        req = make_req()
        res = make_res()
        ctx = make_ctx()

        @requires_role("admin")
        def handler(req, res, ctx):
            pass

        handler(req, res, ctx)
        res.status.assert_called_with(401)
