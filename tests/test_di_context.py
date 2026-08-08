"""
Test cases for dependency injection and context in Hypern framework.

Tests cover:
- Singleton dependencies
- Request-scoped dependencies
- Compiled dependency injection markers
- Request context (set, get, has)
- Context elapsed time
"""

import httpx


class TestSingletonDependencies:
    """Test singleton dependency injection."""
    
    def test_config_singleton(self, client: httpx.Client):
        """Test config singleton is injected correctly."""
        response = client.get("/di/config")
        assert response.status_code == 200
        data = response.json()
        
        assert data["app_name"] == "Hypern Test App"
        assert data["debug"] is True
        assert data["store_url"] == "memory://test"
        assert data["secret_key"] == "test-secret-key-123"
    
    def test_store_singleton(self, client: httpx.Client):
        """Test store singleton is injected correctly."""
        response = client.get("/di/store")
        assert response.status_code == 200
        data = response.json()
        
        assert "users" in data
        assert isinstance(data["users"], list)
        # Should have initial users from test store
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
        list_response = client.get("/di/store")
        assert list_response.status_code == 200
        users = list_response.json()["users"]
        
        names = [u["name"] for u in users]
        assert "Singleton Test" in names


class TestRequestScopedDependencies:
    """Test request-scoped dependency injection."""
    
    def test_request_provider_creates_an_instance(self, client: httpx.Client):
        """Test that the request provider creates an injected instance."""
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
    
    def test_explicit_store_marker(self, client: httpx.Client):
        """Test explicit-key marker injection for the store."""
        response = client.get("/di/store")
        assert response.status_code == 200
        data = response.json()
        assert "users" in data

    def test_request_scoped_marker(self, client: httpx.Client):
        """Test marker injection for a request-scoped provider."""
        response = client.get("/di/factory")
        assert response.status_code == 200
        data = response.json()
        assert data["logger_created"] is True

    def test_multiple_injected_parameters(self, client: httpx.Client):
        """Test multiple explicitly keyed injection markers."""
        response = client.get("/di/multi")
        assert response.status_code == 200
        data = response.json()
        assert "user_count" in data
        assert "app_name" in data
        assert data["app_name"] == "Hypern Test App"
    
    def test_config_used_in_logic(self, client: httpx.Client):
        """Test config values are used in application logic."""
        response = client.get("/di/config")
        assert response.status_code == 200
        data = response.json()
        
        # Config should have expected keys
        assert "app_name" in data
        assert "debug" in data
        assert "store_url" in data
    
    def test_store_operations_through_di(self, client: httpx.Client):
        """Test store operations work through DI."""
        # Create via CRUD (uses DI store)
        create_resp = client.post(
            "/crud/users",
            json={"name": "DI Test User", "email": "di@test.com", "age": 28}
        )
        assert create_resp.status_code == 201
        user = create_resp.json()
        
        # Read via DI endpoint
        di_resp = client.get("/di/store")
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


class TestRouterInject:
    """Test compiled injection markers with Router-mounted routes."""

    def test_router_inject_single_config(self, client: httpx.Client):
        """Test explicit config injection on a Router route."""
        response = client.get("/router-di/config")
        assert response.status_code == 200
        data = response.json()
        assert data["app_name"] == "Hypern Test App"
        assert data["debug"] is True

    def test_router_inject_single_store(self, client: httpx.Client):
        """Test explicit store injection on a Router route."""
        response = client.get("/router-di/store")
        assert response.status_code == 200
        data = response.json()
        assert "users" in data
        assert isinstance(data["users"], list)

    def test_router_inject_multi(self, client: httpx.Client):
        """Test multiple injection markers on a Router route."""
        response = client.get("/router-di/multi")
        assert response.status_code == 200
        data = response.json()
        assert "user_count" in data
        assert "app_name" in data
        assert data["app_name"] == "Hypern Test App"
        assert isinstance(data["user_count"], int)

    def test_router_inject_stacked(self, client: httpx.Client):
        """Test that marker order does not affect Router binding."""
        response = client.get("/router-di/stacked")
        assert response.status_code == 200
        data = response.json()
        assert data["stacked"] is True
        assert data["app_name"] == "Hypern Test App"
        assert isinstance(data["user_count"], int)


class TestInjectWithValidator:
    """Test compiled injection and validation markers together."""

    # ------------------------------------------------------------------
    # App-level routes
    # ------------------------------------------------------------------

    def test_json_then_injected_dependency(self, client: httpx.Client):
        """Bind a JSON payload before an injected dependency."""
        response = client.post(
            "/di-validate/body",
            json={"name": "widget", "value": 42},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "widget"
        assert data["value"] == 42
        assert data["app_name"] == "Hypern Test App"

    def test_json_then_injected_dependency_invalid(self, client: httpx.Client):
        """Return a validation response for an invalid JSON payload."""
        response = client.post(
            "/di-validate/body",
            json={"value": 1},  # missing required field 'name'
        )
        assert response.status_code == 400

    def test_injected_dependency_before_json(self, client: httpx.Client):
        """Bind an injected dependency before a JSON payload."""
        response = client.post(
            "/di-validate/body-reversed",
            json={"name": "gadget", "value": 7},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "gadget"
        assert data["value"] == 7
        assert data["app_name"] == "Hypern Test App"

    def test_query_then_injected_dependency(self, client: httpx.Client):
        """Bind a query structure before an injected dependency."""
        response = client.get("/di-validate/query", params={"limit": "5", "active": "true"})
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 5
        assert data["active"] is True
        assert data["app_name"] == "Hypern Test App"

    def test_query_defaults_with_injected_dependency(self, client: httpx.Client):
        """Apply query defaults alongside an injected dependency."""
        response = client.get("/di-validate/query")
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 10
        assert data["active"] is True
        assert data["app_name"] == "Hypern Test App"

    def test_multiple_injections_with_json_and_query(self, client: httpx.Client):
        """Bind JSON, query, and multiple injected values in declaration order."""
        response = client.post(
            "/di-validate/body-query",
            params={"limit": "3", "active": "false"},
            json={"name": "combo", "value": 99},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "combo"
        assert data["value"] == 99
        assert data["limit"] == 3
        assert data["active"] is False
        assert data["app_name"] == "Hypern Test App"
        assert isinstance(data["user_count"], int)

    # ------------------------------------------------------------------
    # Router-level routes
    # ------------------------------------------------------------------

    def test_router_inject_json(self, client: httpx.Client):
        """Bind a validated JSON body and injected dependencies on a Router."""
        response = client.post(
            "/router-di-validate/create",
            json={"name": "thing", "value": 10},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "thing"
        assert data["value"] == 10
        assert data["debug"] is True
        assert data["has_users"] is True

    def test_router_inject_json_invalid(self, client: httpx.Client):
        """Return a validation response for invalid Router JSON input."""
        response = client.post(
            "/router-di-validate/create",
            json={"value": 10},  # missing 'name'
        )
        assert response.status_code == 400

    def test_router_inject_query(self, client: httpx.Client):
        """Bind a query structure and an injected dependency on a Router."""
        response = client.get(
            "/router-di-validate/search",
            params={"limit": "20", "active": "false"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 20
        assert data["active"] is False
        assert data["app_name"] == "Hypern Test App"

    def test_router_inject_validate_combined(self, client: httpx.Client):
        """Bind Router JSON, query, and injected parameters together."""
        response = client.post(
            "/router-di-validate/combined",
            params={"limit": "8"},
            json={"name": "entry", "value": 5},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "entry"
        assert data["value"] == 5
        assert data["limit"] == 8
        assert data["active"] is True
        assert data["app_name"] == "Hypern Test App"
