"""
Test cases for error handling in Hypern framework.

Tests cover:
- NotFound exception (404)
- BadRequest exception (400)
- Unauthorized exception (401)
- Custom HTTP exceptions
- Internal server errors (500)
- Error handler registration
"""

import httpx
import pytest


class TestNotFoundError:
    """Test NotFound exception handling."""
    
    def test_not_found_exception(self, client: httpx.Client):
        """Test NotFound exception returns 404."""
        response = client.get("/errors/not-found")
        assert response.status_code == 404
        data = response.json()
        
        assert data["error"] == "not_found"
        assert "message" in data
    
    def test_not_found_message(self, client: httpx.Client):
        """Test NotFound includes error message."""
        response = client.get("/errors/not-found")
        assert response.status_code == 404
        data = response.json()
        
        assert "Resource not found" in data["message"]


class TestBadRequestError:
    """Test BadRequest exception handling."""
    
    def test_bad_request_exception(self, client: httpx.Client):
        """Test BadRequest exception returns 400."""
        response = client.get("/errors/bad-request")
        assert response.status_code == 400
        data = response.json()
        
        assert data["error"] == "bad_request"
        assert "message" in data
    
    def test_bad_request_message(self, client: httpx.Client):
        """Test BadRequest includes error message."""
        response = client.get("/errors/bad-request")
        assert response.status_code == 400
        data = response.json()
        
        assert "Invalid request data" in data["message"]


class TestUnauthorizedError:
    """Test Unauthorized exception handling."""
    
    def test_unauthorized_exception(self, client: httpx.Client):
        """Test Unauthorized exception returns 401."""
        response = client.get("/errors/unauthorized")
        assert response.status_code == 401
        data = response.json()
        
        assert data["error"] == "unauthorized"
        assert "message" in data
    
    def test_unauthorized_message(self, client: httpx.Client):
        """Test Unauthorized includes error message."""
        response = client.get("/errors/unauthorized")
        assert response.status_code == 401
        data = response.json()
        
        assert "Authentication required" in data["message"]


class TestCustomHTTPException:
    """Test custom HTTP exception handling."""
    
    def test_custom_status_code(self, client: httpx.Client):
        """Test custom HTTP exception with specific status code."""
        response = client.get("/errors/custom")
        assert response.status_code == 418  # I'm a teapot
        data = response.json()
        
        assert data["error"] == "http_exception"
        assert data["status_code"] == 418
    
    def test_custom_message(self, client: httpx.Client):
        """Test custom HTTP exception message."""
        response = client.get("/errors/custom")
        assert response.status_code == 418
        data = response.json()
        
        assert "teapot" in data["message"].lower()


class TestInternalServerError:
    """Test internal server error handling."""
    
    def test_internal_error(self, client: httpx.Client):
        """Test unhandled exception returns 500."""
        response = client.get("/errors/internal")
        assert response.status_code == 500
        data = response.json()
        
        assert data["error"] == "internal_error"
        assert "message" in data
    
    def test_internal_error_message(self, client: httpx.Client):
        """Test internal error includes message."""
        response = client.get("/errors/internal")
        assert response.status_code == 500
        data = response.json()
        
        assert "Unexpected internal error" in data["message"]


class TestErrorResponseFormat:
    """Test error response format consistency."""
    
    def test_error_response_is_json(self, client: httpx.Client):
        """Test all error responses are JSON."""
        error_endpoints = [
            "/errors/not-found",
            "/errors/bad-request",
            "/errors/unauthorized",
            "/errors/custom",
            "/errors/internal"
        ]
        
        for endpoint in error_endpoints:
            response = client.get(endpoint)
            content_type = response.headers.get("content-type", "")
            assert "application/json" in content_type, f"Endpoint {endpoint} should return JSON"
    
    def test_error_response_has_error_key(self, client: httpx.Client):
        """Test all error responses have 'error' key."""
        error_endpoints = [
            "/errors/not-found",
            "/errors/bad-request",
            "/errors/unauthorized",
            "/errors/custom",
            "/errors/internal"
        ]
        
        for endpoint in error_endpoints:
            response = client.get(endpoint)
            data = response.json()
            assert "error" in data, f"Endpoint {endpoint} response should have 'error' key"
    
    def test_error_response_has_message_key(self, client: httpx.Client):
        """Test all error responses have 'message' key."""
        error_endpoints = [
            "/errors/not-found",
            "/errors/bad-request",
            "/errors/unauthorized",
            "/errors/custom",
            "/errors/internal"
        ]
        
        for endpoint in error_endpoints:
            response = client.get(endpoint)
            data = response.json()
            assert "message" in data, f"Endpoint {endpoint} response should have 'message' key"


class TestImplicitErrors:
    """Test implicit error scenarios."""
    
    def test_route_not_found(self, client: httpx.Client):
        """Test accessing non-existent route returns 404."""
        response = client.get("/this-route-does-not-exist")
        assert response.status_code == 404
    
    def test_method_not_allowed_behavior(self, client: httpx.Client):
        """Test wrong HTTP method returns appropriate error."""
        # POST to a GET-only endpoint
        response = client.post("/health")
        # Should be 404 (route not found for that method) or 405
        assert response.status_code in [404, 405]
    
    def test_resource_not_found(self, client: httpx.Client):
        """Test accessing non-existent resource returns 404."""
        response = client.get("/users/non-existent-user-id-99999")
        assert response.status_code == 404
