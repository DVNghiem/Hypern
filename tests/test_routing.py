"""
Test cases for routing functionality in Hypern framework.

Tests cover:
- All HTTP methods (GET, POST, PUT, PATCH, DELETE, OPTIONS, HEAD)
- Route parameters (single, multiple)
- Wildcard routes
- Router groups (API versioning)
- Query parameters
- Async handlers
- CRUD operations
"""

import httpx
import pytest


class TestBasicRouting:
    """Test basic HTTP method routing."""
    
    def test_get_home_route(self, client: httpx.Client):
        """Test GET request to home route returns welcome message."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        
        assert data["message"] == "Hello, World!"
        assert data["service"] == "Hypern Test Server"
    
    def test_get_health_route(self, client: httpx.Client):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "healthy"
        assert "timestamp" in data
    
    def test_post_echo_route(self, client: httpx.Client):
        """Test POST request echoes back the body."""
        test_data = {"message": "test", "value": 123}
        response = client.post("/echo", json=test_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["echo"] == test_data
    
    def test_put_echo_route(self, client: httpx.Client):
        """Test PUT request handles body correctly."""
        test_data = {"update": "data", "id": 1}
        response = client.put("/echo", json=test_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["method"] == "PUT"
        assert data["echo"] == test_data
    
    def test_patch_echo_route(self, client: httpx.Client):
        """Test PATCH request handles body correctly."""
        test_data = {"partial": "update"}
        response = client.patch("/echo", json=test_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["method"] == "PATCH"
        assert data["echo"] == test_data
    
    def test_delete_echo_route(self, client: httpx.Client):
        """Test DELETE request."""
        response = client.delete("/echo")
        assert response.status_code == 200
        data = response.json()
        
        assert data["method"] == "DELETE"
        assert data["deleted"] is True
    
    def test_options_echo_route(self, client: httpx.Client):
        """Test OPTIONS request returns allowed methods."""
        response = client.options("/echo")
        assert response.status_code == 204
        
        allow_header = response.headers.get("allow")
        assert allow_header is not None
        
        for method in ["GET", "POST", "PUT", "DELETE"]:
            assert method in allow_header
    
    def test_head_echo_route(self, client: httpx.Client):
        """Test HEAD request returns headers without body."""
        response = client.head("/echo")
        assert response.status_code == 200
        
        # HEAD should have no body
        assert len(response.content) == 0
        
        # Check custom header is set
        assert "x-echo-status" in response.headers


class TestRouteParameters:
    """Test route parameter handling."""
    
    def test_single_route_parameter(self, client: httpx.Client):
        """Test route with single parameter."""
        response = client.get("/users/1")
        assert response.status_code == 200
        data = response.json()
        
        assert data["id"] == "1"
        assert data["name"] == "Alice"
    
    def test_route_parameter_different_values(self, client: httpx.Client):
        """Test route parameter with different values."""
        response = client.get("/users/2")
        assert response.status_code == 200
        data = response.json()
        
        assert data["id"] == "2"
        assert data["name"] == "Bob"
    
    def test_route_parameter_not_found(self, client: httpx.Client):
        """Test route parameter with non-existent resource."""
        response = client.get("/users/999")
        assert response.status_code == 404
        data = response.json()
        
        assert "error" in data
        assert data["user_id"] == "999"
    
    def test_multiple_route_parameters(self, client: httpx.Client):
        """Test route with multiple parameters."""
        response = client.get("/users/42/posts/123")
        assert response.status_code == 200
        data = response.json()
        
        assert data["user_id"] == "42"
        assert data["post_id"] == "123"
        assert "title" in data


class TestWildcardRoutes:
    """Test wildcard route parameter handling."""
    
    def test_wildcard_single_segment(self, client: httpx.Client):
        """Test wildcard route with single path segment."""
        response = client.get("/files/document.txt")
        assert response.status_code == 200
        data = response.json()
        
        assert data["filepath"] == "document.txt"
    
    def test_wildcard_multiple_segments(self, client: httpx.Client):
        """Test wildcard route with multiple path segments."""
        response = client.get("/files/path/to/nested/file.pdf")
        assert response.status_code == 200
        data = response.json()
        
        assert data["filepath"] == "path/to/nested/file.pdf"
    
    def test_wildcard_with_special_chars(self, client: httpx.Client):
        """Test wildcard route with special characters in path."""
        response = client.get("/files/folder/my-file_v2.json")
        assert response.status_code == 200
        data = response.json()
        
        assert data["filepath"] == "folder/my-file_v2.json"


class TestQueryParameters:
    """Test query parameter handling."""
    
    def test_single_query_parameter(self, client: httpx.Client):
        """Test single query parameter."""
        response = client.get("/search", params={"q": "python"})
        assert response.status_code == 200
        data = response.json()
        
        assert data["q"] == "python"
    
    def test_multiple_query_parameters(self, client: httpx.Client):
        """Test multiple query parameters."""
        response = client.get("/search", params={
            "q": "hypern",
            "page": "2",
            "limit": "25"
        })
        assert response.status_code == 200
        data = response.json()
        
        assert data["q"] == "hypern"
        assert data["page"] == 2
        assert data["limit"] == 25
    
    def test_query_parameters_defaults(self, client: httpx.Client):
        """Test query parameters use defaults when not provided."""
        response = client.get("/search")
        assert response.status_code == 200
        data = response.json()
        
        assert data["page"] == 1
        assert data["limit"] == 10
    
    def test_all_queries_returned(self, client: httpx.Client):
        """Test that all query parameters are accessible."""
        params = {"q": "test", "page": "1", "extra": "value"}
        response = client.get("/search", params=params)
        assert response.status_code == 200
        data = response.json()
        
        assert "extra" in data["all_queries"]


class TestRouterGroups:
    """Test router groups (API versioning)."""
    
    def test_api_v1_list_users(self, client: httpx.Client):
        """Test API v1 list users endpoint."""
        response = client.get("/api/v1/users")
        assert response.status_code == 200
        data = response.json()
        
        assert data["version"] == "v1"
        assert "users" in data
        assert isinstance(data["users"], list)
    
    def test_api_v1_get_user(self, client: httpx.Client):
        """Test API v1 get user endpoint."""
        response = client.get("/api/v1/users/1")
        assert response.status_code == 200
        data = response.json()
        
        assert data["version"] == "v1"
        assert "user" in data
    
    def test_api_v1_create_user(self, client: httpx.Client):
        """Test API v1 create user endpoint."""
        user_data = {"name": "Charlie", "email": "charlie@example.com", "age": 28}
        response = client.post("/api/v1/users", json=user_data)
        assert response.status_code == 201
        data = response.json()
        
        assert data["version"] == "v1"
        assert data["user"]["name"] == "Charlie"
    
    def test_api_v2_list_users(self, client: httpx.Client):
        """Test API v2 list users endpoint with different response format."""
        response = client.get("/api/v2/users")
        assert response.status_code == 200
        data = response.json()
        
        assert data["version"] == "v2"
        assert "data" in data
        assert "meta" in data
        assert "total" in data["meta"]
    
    def test_api_v2_get_user(self, client: httpx.Client):
        """Test API v2 get user endpoint."""
        response = client.get("/api/v2/users/1")
        assert response.status_code == 200
        data = response.json()
        
        assert data["version"] == "v2"
        assert "data" in data
    
    def test_api_version_isolation(self, client: httpx.Client):
        """Test that API versions are isolated from each other."""
        v1_response = client.get("/api/v1/users")
        v2_response = client.get("/api/v2/users")
        
        v1_data = v1_response.json()
        v2_data = v2_response.json()
        
        # Verify different response structures
        assert "users" in v1_data
        assert "data" in v2_data
        assert "meta" in v2_data


class TestAsyncHandlers:
    """Test async handler functionality."""
    
    def test_async_basic_handler(self, client: httpx.Client):
        """Test basic async handler."""
        response = client.get("/async/basic")
        assert response.status_code == 200
        data = response.json()
        
        assert data["type"] == "async"
        assert data["status"] == "completed"
    
    def test_async_process_handler(self, client: httpx.Client):
        """Test async handler with request body."""
        test_data = {"items": [1, 2, 3], "name": "test"}
        response = client.post("/async/process", json=test_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["async"] is True
        assert data["processed"] == test_data


class TestRequestInfo:
    """Test request information access."""
    
    def test_request_metadata(self, client: httpx.Client):
        """Test request method, path, and URL are accessible."""
        response = client.get("/request-info")
        assert response.status_code == 200
        data = response.json()
        
        assert data["method"] == "GET"
        assert data["path"] == "/request-info"
        assert "request-info" in data["url"]


class TestCRUDOperations:
    """Test complete CRUD operations."""
    
    def test_crud_create_read_update_delete(self, client: httpx.Client):
        """Test full CRUD lifecycle."""
        # CREATE
        new_user = {"name": "Dave", "email": "dave@example.com", "age": 35}
        create_response = client.post("/crud/users", json=new_user)
        assert create_response.status_code == 201
        created = create_response.json()
        
        assert created["name"] == "Dave"
        user_id = created["id"]
        
        # READ
        read_response = client.get(f"/crud/users/{user_id}")
        assert read_response.status_code == 200
        read_data = read_response.json()
        
        assert read_data["name"] == "Dave"
        
        # UPDATE
        update_data = {"name": "David", "age": 36}
        update_response = client.put(f"/crud/users/{user_id}", json=update_data)
        assert update_response.status_code == 200
        updated = update_response.json()
        
        assert updated["name"] == "David"
        assert updated["age"] == 36
        
        # DELETE
        delete_response = client.delete(f"/crud/users/{user_id}")
        assert delete_response.status_code == 204
        
        # Verify deletion
        verify_response = client.get(f"/crud/users/{user_id}")
        assert verify_response.status_code == 404
    
    def test_crud_list_users(self, client: httpx.Client):
        """Test listing all users."""
        response = client.get("/crud/users")
        assert response.status_code == 200
        data = response.json()
        
        assert "users" in data
        assert len(data["users"]) >= 2
    
    def test_crud_update_nonexistent(self, client: httpx.Client):
        """Test updating non-existent user returns 404."""
        response = client.put("/crud/users/9999", json={"name": "Ghost"})
        assert response.status_code == 404
    
    def test_crud_delete_nonexistent(self, client: httpx.Client):
        """Test deleting non-existent user returns 404."""
        response = client.delete("/crud/users/9999")
        assert response.status_code == 404


class TestRouteNotFound:
    """Test 404 handling for non-existent routes."""
    
    def test_nonexistent_route(self, client: httpx.Client):
        """Test request to non-existent route returns 404."""
        response = client.get("/this/route/does/not/exist")
        assert response.status_code == 404
    
    def test_wrong_method(self, client: httpx.Client):
        """Test request with wrong HTTP method."""
        response = client.post("/health")
        # Should return 404 or 405 depending on implementation
        assert response.status_code in [404, 405]
