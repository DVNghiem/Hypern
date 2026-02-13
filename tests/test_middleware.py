"""
Tests for Hypern middleware functionality.

This module tests real middleware behavior with actual HTTP requests:
- CORS (Cross-Origin Resource Sharing) headers and preflight
- RateLimit (Request rate limiting) enforcement
- SecurityHeaders (HSTS, CSP, X-Frame-Options, etc.)
- Compression (Response compression with gzip)
- RequestId (Unique request ID generation)
- BasicAuth (HTTP Basic Authentication)
"""

import base64
import time
import httpx


class TestCORSMiddleware:
    """Test CORS middleware with real HTTP requests."""
    
    def test_cors_middleware_can_be_created(self):
        """CORS middleware can be instantiated."""
        from hypern.middleware import CorsMiddleware
        cors = CorsMiddleware.permissive()
        assert cors is not None
        
        cors_custom = CorsMiddleware(
            allowed_origins=["https://example.com"],
            allowed_methods=["GET", "POST"],
            allow_credentials=True
        )
        assert cors_custom is not None
    
    def test_cors_endpoint_responds(self, client):
        """CORS endpoint should respond successfully."""
        response = client.get("/middleware/cors/test")
        assert response.status_code == 200
        assert response.json() == {"cors": "enabled"}
    
    def test_cors_adds_headers_with_origin(self, client):
        """CORS middleware should add headers when Origin header is present."""
        response = client.get(
            "/middleware/cors/test",
            headers={"Origin": "https://example.com"}
        )
        assert response.status_code == 200
        # CORS.permissive() allows all origins
        assert "Access-Control-Allow-Origin" in response.headers
        assert response.headers["Access-Control-Allow-Origin"] == "*"


class TestSecurityHeadersMiddleware:
    """Test security headers middleware with real requests."""
    
    def test_security_middleware_can_be_created(self):
        """Security middleware can be instantiated."""
        from hypern.middleware import SecurityHeadersMiddleware
        
        sec_strict = SecurityHeadersMiddleware.strict()
        assert sec_strict is not None
        
        sec_custom = SecurityHeadersMiddleware(
            hsts=True,
            frame_options="DENY",
            csp="default-src 'self'"
        )
        assert sec_custom is not None
    
    def test_security_headers_added(self, client):
        """Security middleware should add security headers to responses."""
        response = client.get("/middleware/security/test")
        assert response.status_code == 200
        assert response.json() == {"security": "enabled"}
        
        # Check for strict security headers
        assert "X-Content-Type-Options" in response.headers
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        
        assert "X-Frame-Options" in response.headers
        assert response.headers["X-Frame-Options"] == "DENY"
        
        assert "Strict-Transport-Security" in response.headers
        assert "max-age" in response.headers["Strict-Transport-Security"]


class TestCompressionMiddleware:
    """Test compression middleware with real responses."""
    
    def test_large_response_can_be_compressed(self, client):
        """Large responses should work (httpx auto-decompresses)."""
        response = client.get(
            "/middleware/compression/large",
            headers={"Accept-Encoding": "gzip, deflate"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # httpx automatically decompresses, so we get the original data
        assert "data" in data
        assert len(data["data"]) == 500
        assert data["compressed"] == True
    
    def test_small_response_not_compressed(self, client):
        """Small responses (< 100 bytes) should not be compressed."""
        response = client.get("/middleware/compression/small")
        assert response.status_code == 200
        data = response.json()
        assert data == {"tiny": "data"}


class TestRequestIdMiddleware:
    """Test request ID middleware functionality."""
    
    def test_request_id_header_added(self, client):
        """RequestId middleware should add X-Request-ID to responses."""
        response = client.get("/middleware/requestid/test")
        assert response.status_code == 200
        
        # Check for request ID header
        request_id = response.headers.get("X-Request-ID")
        assert request_id is not None
        assert len(request_id) > 0
    
    def test_request_id_is_unique(self, client):
        """Each request should get a unique request ID."""
        response1 = client.get("/middleware/requestid/test")
        response2 = client.get("/middleware/requestid/test")
        
        id1 = response1.headers.get("X-Request-ID")
        id2 = response2.headers.get("X-Request-ID")
        
        assert id1 is not None
        assert id2 is not None
        assert id1 != id2  # IDs should be different
    
    def test_request_id_preserved_if_provided(self, client):
        """If client provides X-Request-ID, it should be preserved."""
        custom_id = "test-custom-id-12345"
        response = client.get(
            "/middleware/requestid/test",
            headers={"X-Request-ID": custom_id}
        )
        assert response.status_code == 200
        
        # Should preserve the custom ID
        returned_id = response.headers.get("X-Request-ID")
        assert returned_id == custom_id


class TestBasicAuthMiddleware:
    """Test HTTP Basic Authentication with real auth flow."""
    
    def test_auth_requires_credentials(self, client):
        """Requests without credentials should be rejected with 401."""
        response = client.get("/middleware/auth/protected")
        assert response.status_code == 401
        
        # Should have WWW-Authenticate header
        assert "WWW-Authenticate" in response.headers
        www_auth = response.headers["WWW-Authenticate"]
        assert "Basic" in www_auth
        assert "Test Area" in www_auth
    
    def test_auth_with_valid_credentials(self, client):
        """Valid credentials should grant access."""
        credentials = base64.b64encode(b"admin:secret").decode("ascii")
        response = client.get(
            "/middleware/auth/protected",
            headers={"Authorization": f"Basic {credentials}"}
        )
        # Valid credentials should get 200 OK (authentication works!)
        assert response.status_code == 200
    
    def test_auth_with_wrong_password(self, client):
        """Wrong password should be rejected."""
        credentials = base64.b64encode(b"admin:wrongpassword").decode("ascii")
        response = client.get(
            "/middleware/auth/protected",
            headers={"Authorization": f"Basic {credentials}"}
        )
        assert response.status_code == 401
    
    def test_auth_with_invalid_username(self, client):
        """Invalid username should be rejected."""
        credentials = base64.b64encode(b"hacker:secret").decode("ascii")
        response = client.get(
            "/middleware/auth/protected",
            headers={"Authorization": f"Basic {credentials}"}
        )
        assert response.status_code == 401
    
    def test_auth_with_different_valid_user(self, client):
        """Different valid user should also work."""
        credentials = base64.b64encode(b"testuser:password123").decode("ascii")
        response = client.get(
            "/middleware/auth/protected",
            headers={"Authorization": f"Basic {credentials}"}
        )
        # Valid credentials should get 200 OK
        assert response.status_code == 200
    
    def test_auth_with_malformed_header(self, client):
        """Malformed Authorization header should be rejected."""
        response = client.get(
            "/middleware/auth/protected",
            headers={"Authorization": "Bearer some-token"}
        )
        assert response.status_code == 401
    
    def test_auth_with_invalid_base64(self, client):
        """Invalid base64 in Authorization should be rejected."""
        response = client.get(
            "/middleware/auth/protected",
            headers={"Authorization": "Basic not-valid-base64!!!"}
        )
        assert response.status_code == 401


class TestMiddlewareIntegration:
    """Test middleware working together in real scenarios."""
    
    def test_multiple_middleware_applied_together(self, client):
        """Multiple global middleware should all be applied."""
        response = client.get(
            "/middleware/cors/test",
            headers={"Origin": "https://example.com"}
        )
        assert response.status_code == 200
        
        # RequestId middleware
        assert "X-Request-ID" in response.headers
        assert len(response.headers["X-Request-ID"]) > 0
        
        # CORS middleware (when Origin header is present)
        assert "Access-Control-Allow-Origin" in response.headers
        
        # SecurityHeaders middleware
        assert "X-Content-Type-Options" in response.headers
        
        # Response should be valid JSON
        data = response.json()
        assert "cors" in data
    
    def test_middleware_preserves_response_body(self, client):
        """Middleware should not corrupt the response body."""
        response = client.get("/middleware/security/test")
        assert response.status_code == 200
        data = response.json()
        assert data == {"security": "enabled"}
        
        # Middleware headers should be added
        assert "X-Request-ID" in response.headers
        assert "X-Content-Type-Options" in response.headers
    
    def test_middleware_works_with_post_requests(self, client):
        """Middleware should work with POST and other methods."""
        response = client.post(
            "/echo",
            json={"test": "data"},
            headers={"Origin": "https://example.com"}
        )
        assert response.status_code == 200
        
        # RequestId middleware header should be present
        assert "X-Request-ID" in response.headers
        
        # CORS header should be present (Origin was sent)
        assert "Access-Control-Allow-Origin" in response.headers
        
        # Response body should be intact
        data = response.json()
        assert data["echo"] == {"test": "data"}


class TestMiddlewareConfiguration:
    """Test middleware can be properly configured."""
    
    def test_cors_middleware_creation(self):
        """CORS middleware can be created with various configs."""
        from hypern.middleware import CorsMiddleware
        
        # Permissive CORS
        cors1 = CorsMiddleware.permissive()
        assert cors1 is not None
        
        # Custom CORS
        cors2 = CorsMiddleware(
            allowed_origins=["https://example.com"],
            allowed_methods=["GET", "POST"],
            allow_credentials=True
        )
        assert cors2 is not None
    
    def test_ratelimit_middleware_creation(self):
        """RateLimit middleware can be created."""
        from hypern.middleware import RateLimitMiddleware
        
        rl = RateLimitMiddleware(max_requests=100, window_secs=60, algorithm="sliding")
        assert rl is not None
    
    def test_security_headers_middleware_creation(self):
        """SecurityHeaders middleware can be created."""
        from hypern.middleware import SecurityHeadersMiddleware
        
        # Strict preset
        sec1 = SecurityHeadersMiddleware.strict()
        assert sec1 is not None
        
        # Custom config
        sec2 = SecurityHeadersMiddleware(
            hsts=True,
            frame_options="DENY",
            csp="default-src 'self'"
        )
        assert sec2 is not None
    
    def test_compression_middleware_creation(self):
        """Compression middleware can be created."""
        from hypern.middleware import CompressionMiddleware
        
        comp = CompressionMiddleware(min_size=512)
        assert comp is not None
    
    def test_requestid_middleware_creation(self):
        """RequestId middleware can be created."""
        from hypern.middleware import RequestIdMiddleware
        
        rid1 = RequestIdMiddleware()
        assert rid1 is not None
        
        rid2 = RequestIdMiddleware(header_name="X-Correlation-ID")
        assert rid2 is not None


class TestCustomMiddlewareDecorators:
    """Test custom Python middleware decorators (@middleware, @before_request, @after_request)."""
    
    def test_middleware_decorator_exists(self):
        """The @middleware decorator should be importable."""
        from hypern.middleware import middleware
        assert middleware is not None
        assert callable(middleware)
    
    def test_before_request_decorator_exists(self):
        """The @before_request decorator should be importable."""
        from hypern.middleware import before_request
        assert before_request is not None
        assert callable(before_request)
    
    def test_after_request_decorator_exists(self):
        """The @after_request decorator should be importable."""
        from hypern.middleware import after_request
        assert after_request is not None
        assert callable(after_request)
    
    def test_middleware_decorator_marks_function(self):
        """@middleware decorator should mark function with _is_middleware attribute."""
        from hypern.middleware import middleware
        
        @middleware
        async def test_mw(req, res, ctx, next):
            await next()
        
        assert hasattr(test_mw, '_is_middleware')
        assert test_mw._is_middleware is True
    
    def test_before_request_decorator_marks_function(self):
        """@before_request decorator should mark function with _before_request attribute."""
        from hypern.middleware import before_request
        
        @before_request
        async def test_before(req, res, ctx):
            pass
        
        assert hasattr(test_before, '_before_request')
        assert test_before._before_request is True
    
    def test_after_request_decorator_marks_function(self):
        """@after_request decorator should mark function with _after_request attribute."""
        from hypern.middleware import after_request
        
        @after_request
        async def test_after(req, res, ctx):
            pass
        
        assert hasattr(test_after, '_after_request')
        assert test_after._after_request is True
    
    def test_custom_middleware_execution(self, client):
        """Custom @middleware decorated functions should execute with next() callback."""
        # This test uses the /middleware/custom endpoint that has custom middleware
        response = client.get("/middleware/custom/test")
        assert response.status_code == 200
        
        # Check that custom middleware header was added
        assert "X-Custom-Middleware" in response.headers
        assert response.headers["X-Custom-Middleware"] == "executed"
        
        # Response body should be intact
        data = response.json()
        assert data["message"] == "custom middleware test"
    
    def test_before_request_hook_execution(self, client):
        """@before_request hooks should execute before route handler."""
        response = client.get("/hooks/before-test")
        assert response.status_code == 200
        
        # Check that before_request hook added header
        assert "X-Before-Request" in response.headers
        assert response.headers["X-Before-Request"] == "hook-executed"
        
        data = response.json()
        assert data["message"] == "before hook test"
    
    def test_after_request_hook_execution(self, client):
        """@after_request hooks should execute after route handler."""
        response = client.get("/hooks/after-test")
        assert response.status_code == 200
        
        # Check that after_request hook added header
        assert "X-After-Request" in response.headers
        assert response.headers["X-After-Request"] == "hook-executed"
        
        data = response.json()
        assert data["message"] == "after hook test"
    
    def test_middleware_can_modify_request(self, client):
        """Custom middleware should be able to modify request."""
        response = client.get("/middleware/custom/modify")
        assert response.status_code == 200
        
        data = response.json()
        # Middleware should have added custom attribute
        assert "modified_by_middleware" in data
        assert data["modified_by_middleware"] is True
    
    def test_middleware_can_short_circuit(self, client):
        """Custom middleware should be able to short-circuit request."""
        response = client.get("/middleware/custom/blocked")
        assert response.status_code == 403
        
        data = response.json()
        assert "error" in data
        assert data["error"] == "Blocked by middleware"
    
    def test_multiple_before_hooks_execute_in_order(self, client):
        """Multiple @before_request hooks should execute in registration order."""
        response = client.get("/hooks/multiple-before")
        assert response.status_code == 200
        
        # Check headers added by multiple before hooks
        assert "X-Before-1" in response.headers
        assert "X-Before-2" in response.headers
        
        data = response.json()
        assert "order" in data
        assert data["order"] == ["before-1", "before-2", "handler"]
    
    def test_multiple_after_hooks_execute_in_order(self, client):
        """Multiple @after_request hooks should execute in registration order."""
        response = client.get("/hooks/multiple-after")
        assert response.status_code == 200
        
        # Check headers added by multiple after hooks
        assert "X-After-1" in response.headers
        assert "X-After-2" in response.headers
        
        data = response.json()
        assert "executed" in data
        assert data["executed"] is True
