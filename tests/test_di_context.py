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
    
    def test_standalone_inject_database(self, client: httpx.Client):
        """Test standalone @inject decorator works for database."""
        response = client.get("/di/database")
        assert response.status_code == 200
        data = response.json()
        assert "users" in data

    def test_standalone_inject_factory(self, client: httpx.Client):
        """Test standalone @inject decorator works for factory deps."""
        response = client.get("/di/factory")
        assert response.status_code == 200
        data = response.json()
        assert data["logger_created"] is True

    def test_multi_inject(self, client: httpx.Client):
        """Test @inject with multiple dependency names."""
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


class TestRouterInject:
    """Test standalone @inject decorator works with Router-mounted routes."""

    def test_router_inject_single_config(self, client: httpx.Client):
        """Test @inject('config') on a Router route resolves correctly."""
        response = client.get("/router-di/config")
        assert response.status_code == 200
        data = response.json()
        assert data["app_name"] == "Hypern Test App"
        assert data["debug"] is True

    def test_router_inject_single_database(self, client: httpx.Client):
        """Test @inject('database') on a Router route resolves correctly."""
        response = client.get("/router-di/database")
        assert response.status_code == 200
        data = response.json()
        assert "users" in data
        assert isinstance(data["users"], list)

    def test_router_inject_multi(self, client: httpx.Client):
        """Test @inject with multiple names on a Router route."""
        response = client.get("/router-di/multi")
        assert response.status_code == 200
        data = response.json()
        assert "user_count" in data
        assert "app_name" in data
        assert data["app_name"] == "Hypern Test App"
        assert isinstance(data["user_count"], int)

    def test_router_inject_stacked(self, client: httpx.Client):
        """Test stacked @inject decorators on a Router route."""
        response = client.get("/router-di/stacked")
        assert response.status_code == 200
        data = response.json()
        assert data["stacked"] is True
        assert data["app_name"] == "Hypern Test App"
        assert isinstance(data["user_count"], int)


class TestInjectWithValidator:
    """Test @inject combined with @validate_body / @validate_query / @validate."""

    # ------------------------------------------------------------------
    # App-level routes
    # ------------------------------------------------------------------

    def test_inject_outer_validate_body_inner(self, client: httpx.Client):
        """@inject outer + @validate_body inner: body then injected dep."""
        response = client.post(
            "/di-validate/body",
            json={"name": "widget", "value": 42},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "widget"
        assert data["value"] == 42
        assert data["app_name"] == "Hypern Test App"

    def test_inject_outer_validate_body_inner_invalid(self, client: httpx.Client):
        """@inject outer + @validate_body inner: validation error still handled."""
        response = client.post(
            "/di-validate/body",
            json={"value": 1},  # missing required field 'name'
        )
        assert response.status_code == 400

    def test_validate_body_outer_inject_inner(self, client: httpx.Client):
        """@validate_body outer + @inject inner (reversed): same argument order."""
        response = client.post(
            "/di-validate/body-reversed",
            json={"name": "gadget", "value": 7},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "gadget"
        assert data["value"] == 7
        assert data["app_name"] == "Hypern Test App"

    def test_inject_outer_validate_query_inner(self, client: httpx.Client):
        """@inject outer + @validate_query inner: query then injected dep."""
        response = client.get("/di-validate/query", params={"limit": "5", "active": "true"})
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 5
        assert data["active"] is True
        assert data["app_name"] == "Hypern Test App"

    def test_inject_outer_validate_query_defaults(self, client: httpx.Client):
        """@inject outer + @validate_query inner: query defaults still applied."""
        response = client.get("/di-validate/query")
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 10
        assert data["active"] is True
        assert data["app_name"] == "Hypern Test App"

    def test_inject_multi_validate_body_query(self, client: httpx.Client):
        """@inject multi + @validate(body+query): all args in correct order."""
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

    def test_router_inject_validate_body(self, client: httpx.Client):
        """Router + @inject + @validate_body: validated body + injected deps."""
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

    def test_router_inject_validate_body_invalid(self, client: httpx.Client):
        """Router + @inject + @validate_body: validation error still returned."""
        response = client.post(
            "/router-di-validate/create",
            json={"value": 10},  # missing 'name'
        )
        assert response.status_code == 400

    def test_router_inject_validate_query(self, client: httpx.Client):
        """Router + @inject + @validate_query: validated query + injected dep."""
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
        """Router + @inject + @validate(body+query): all resolved correctly."""
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
