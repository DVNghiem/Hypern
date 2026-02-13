"""
Test cases for dependency injection and context in Hypern framework.

Tests cover:
- Singleton dependencies
- Factory dependencies
- Dependency injection via @inject decorator
- Request context (set, get, has)
- Context elapsed time
"""

import httpx
import pytest


class TestSingletonDependencies:
    """Test singleton dependency injection."""
    
    def test_config_singleton(self, client: httpx.Client):
        """Test config singleton is injected correctly."""
        response = client.get("/di/config")
        assert response.status_code == 200
        data = response.json()
        
        assert data["app_name"] == "Hypern Test App"
        assert data["debug"] is True
        assert data["database_url"] == "memory://test"
        assert data["secret_key"] == "test-secret-key-123"
    
    def test_database_singleton(self, client: httpx.Client):
        """Test database singleton is injected correctly."""
        response = client.get("/di/database")
        assert response.status_code == 200
        data = response.json()
        
        assert "users" in data
        assert isinstance(data["users"], list)
        # Should have initial users from test database
        assert len(data["users"]) >= 2
    
    def test_singleton_persistence(self, client: httpx.Client):
        """Test singleton maintains state across requests."""
        # First request - create user
        create_response = client.post(
            "/crud/users",
            json={"name": "Singleton Test", "email": "singleton@test.com", "age": 30}
        )
        assert create_response.status_code == 201
        
        # Second request - verify user exists
        list_response = client.get("/di/database")
        assert list_response.status_code == 200
        users = list_response.json()["users"]
        
        names = [u["name"] for u in users]
        assert "Singleton Test" in names


class TestFactoryDependencies:
    """Test factory dependency injection."""
    
    def test_factory_creates_new_instance(self, client: httpx.Client):
        """Test factory creates new instance per injection."""
        response = client.get("/di/factory")
        assert response.status_code == 200
        data = response.json()
        
        assert data["logger_created"] is True
        assert data["has_logs"] is True


class TestRequestContext:
    """Test request context functionality."""
    
    def test_context_set_and_get(self, client: httpx.Client):
        """Test setting and getting context values."""
        response = client.get("/context/set-get")
        assert response.status_code == 200
        data = response.json()
        
        assert data["request_id"] == "req-12345"
        assert data["user_id"] == "user-789"
        assert data["has_role"] is True
        assert data["missing_with_default"] == "default_value"
    
    def test_context_elapsed_time(self, client: httpx.Client):
        """Test context elapsed time tracking."""
        response = client.get("/context/elapsed")
        assert response.status_code == 200
        data = response.json()
        
        # Should have elapsed time > 0 (at least 10ms due to sleep)
        assert data["elapsed_ms"] > 0
        # Should be reasonable (less than 1 second)
        assert data["elapsed_ms"] < 1000


class TestDependencyInjectionIntegration:
    """Test dependency injection integration scenarios."""
    
    def test_config_used_in_logic(self, client: httpx.Client):
        """Test config values are used in application logic."""
        response = client.get("/di/config")
        assert response.status_code == 200
        data = response.json()
        
        # Config should have expected keys
        assert "app_name" in data
        assert "debug" in data
        assert "database_url" in data
    
    def test_database_operations_through_di(self, client: httpx.Client):
        """Test database operations work through DI."""
        # Create via CRUD (uses DI database)
        create_resp = client.post(
            "/crud/users",
            json={"name": "DI Test User", "email": "di@test.com", "age": 28}
        )
        assert create_resp.status_code == 201
        user = create_resp.json()
        
        # Read via DI endpoint
        di_resp = client.get("/di/database")
        assert di_resp.status_code == 200
        users = di_resp.json()["users"]
        
        user_ids = [u["id"] for u in users]
        assert user["id"] in user_ids


class TestContextIsolation:
    """Test context isolation between requests."""
    
    def test_context_not_shared_between_requests(self, client: httpx.Client):
        """Test each request gets fresh context."""
        # Make first request
        response1 = client.get("/context/set-get")
        assert response1.status_code == 200
        
        # Make second request - should have fresh context
        response2 = client.get("/context/set-get")
        assert response2.status_code == 200
        
        # Both should work independently
        data1 = response1.json()
        data2 = response2.json()
        
        assert data1["request_id"] == data2["request_id"]  # Same route sets same value
    
    def test_context_elapsed_resets(self, client: httpx.Client):
        """Test elapsed time resets per request."""
        response1 = client.get("/context/elapsed")
        response2 = client.get("/context/elapsed")
        
        elapsed1 = response1.json()["elapsed_ms"]
        elapsed2 = response2.json()["elapsed_ms"]
        
        # Both should be small (fresh timers)
        assert elapsed1 < 500
        assert elapsed2 < 500
