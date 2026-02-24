"""
Test cases for Router integration with validators and OpenAPI decorators.

Tests cover:
- Router + validate_body decorator
- Router + validate_query decorator
- Router + combined validate decorator
- Router + api_tags / api_doc / deprecated decorators
- Router + validation + api_doc (stacked decorators)
- app.mount() functionality
- Router handler ctx injection after mount
- Validation error responses from router routes
"""

import httpx
import pytest


class TestRouterWithBodyValidation:
    """Test Router routes with @validate_body decorator."""

    def test_router_validate_body_valid(self, client: httpx.Client):
        """Test valid body passes validation on router route."""
        response = client.post(
            "/router-validated/search",
            json={"q": "python", "page": 2, "limit": 10, "sort": "asc"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["query"] == "python"
        assert data["page"] == 2
        assert data["limit"] == 10
        assert data["sort"] == "asc"

    def test_router_validate_body_defaults(self, client: httpx.Client):
        """Test default values are applied for optional fields."""
        response = client.post(
            "/router-validated/search",
            json={"q": "test"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["query"] == "test"
        assert data["page"] == 1  # default
        assert data["limit"] == 20  # default
        assert data["sort"] == "desc"  # default

    def test_router_validate_body_missing_required(self, client: httpx.Client):
        """Test missing required field returns 400."""
        response = client.post(
            "/router-validated/search",
            json={},  # missing required 'q'
        )
        assert response.status_code in [400, 422]

    def test_router_validate_body_wrong_type(self, client: httpx.Client):
        """Test wrong type for field returns validation error."""
        response = client.post(
            "/router-validated/search",
            json={"q": "test", "page": "not_a_number"},
        )
        assert response.status_code in [400, 422]

    def test_router_validate_body_invalid_json(self, client: httpx.Client):
        """Test invalid JSON body returns error."""
        response = client.post(
            "/router-validated/search",
            content=b"not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code in [400, 422]

    def test_router_validate_body_create_item(self, client: httpx.Client):
        """Test creating an item with validated body on router."""
        response = client.post(
            "/router-validated/items",
            json={"name": "Widget", "price": 9.99},
        )
        assert response.status_code == 201
        data = response.json()

        assert data["name"] == "Widget"
        assert data["price"] == 9.99
        assert data["category"] == "general"  # default

    def test_router_validate_body_create_item_all_fields(self, client: httpx.Client):
        """Test creating item with all fields provided."""
        response = client.post(
            "/router-validated/items",
            json={"name": "Gadget", "price": 49.99, "category": "electronics"},
        )
        assert response.status_code == 201
        data = response.json()

        assert data["name"] == "Gadget"
        assert data["price"] == 49.99
        assert data["category"] == "electronics"

    def test_router_validate_body_missing_required_name(self, client: httpx.Client):
        """Test missing required 'name' field returns error."""
        response = client.post(
            "/router-validated/items",
            json={"price": 9.99},
        )
        assert response.status_code in [400, 422]

    def test_router_validate_body_missing_required_price(self, client: httpx.Client):
        """Test missing required 'price' field returns error."""
        response = client.post(
            "/router-validated/items",
            json={"name": "Incomplete"},
        )
        assert response.status_code in [400, 422]


class TestRouterWithQueryValidation:
    """Test Router routes with @validate_query decorator."""

    def test_router_validate_query_valid(self, client: httpx.Client):
        """Test valid query params on router route."""
        response = client.get(
            "/router-validated/items",
            params={"page": "3", "limit": "25", "search": "widget"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["page"] == 3
        assert data["limit"] == 25
        assert data["search"] == "widget"

    def test_router_validate_query_defaults(self, client: httpx.Client):
        """Test query params use defaults when not provided."""
        response = client.get("/router-validated/items")
        assert response.status_code == 200
        data = response.json()

        assert data["page"] == 1
        assert data["limit"] == 10
        assert data["search"] == ""

    def test_router_validate_query_partial(self, client: httpx.Client):
        """Test partial query params with defaults for missing."""
        response = client.get(
            "/router-validated/items",
            params={"page": "5"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["page"] == 5
        assert data["limit"] == 10  # default
        assert data["search"] == ""  # default


class TestRouterWithCombinedValidation:
    """Test Router routes with @validate(body=..., query=...) decorator."""

    def test_router_combined_valid(self, client: httpx.Client):
        """Test valid body and query together on router route."""
        response = client.post(
            "/router-validated/items-with-query",
            params={"page": "2", "limit": "15"},
            json={"name": "Combined Widget", "price": 19.99, "category": "test"},
        )
        assert response.status_code == 201
        data = response.json()

        assert data["item"]["name"] == "Combined Widget"
        assert data["item"]["price"] == 19.99
        assert data["item"]["category"] == "test"
        assert data["query"]["page"] == 2
        assert data["query"]["limit"] == 15

    def test_router_combined_invalid_body(self, client: httpx.Client):
        """Test invalid body with valid query fails."""
        response = client.post(
            "/router-validated/items-with-query",
            params={"page": "1"},
            json={"name": "No Price"},  # missing required 'price'
        )
        assert response.status_code in [400, 422]

    def test_router_combined_defaults(self, client: httpx.Client):
        """Test combined with default query values."""
        response = client.post(
            "/router-validated/items-with-query",
            json={"name": "Defaults", "price": 5.99},
        )
        assert response.status_code == 201
        data = response.json()

        assert data["item"]["name"] == "Defaults"
        assert data["query"]["page"] == 1
        assert data["query"]["limit"] == 10


class TestRouterWithApiDocs:
    """Test Router routes with OpenAPI decorator metadata."""

    def test_router_docs_list_users(self, client: httpx.Client):
        """Test router route with tags and summary works."""
        response = client.get("/router-docs/users")
        assert response.status_code == 200
        data = response.json()

        assert "users" in data
        assert isinstance(data["users"], list)

    def test_router_docs_get_user(self, client: httpx.Client):
        """Test router route with tags and path param works."""
        response = client.get("/router-docs/users/1")
        assert response.status_code == 200
        data = response.json()

        assert data["name"] == "Alice"

    def test_router_docs_get_user_not_found(self, client: httpx.Client):
        """Test router route returns 404 for missing user."""
        response = client.get("/router-docs/users/999")
        assert response.status_code == 404

    def test_router_docs_deprecated_endpoint(self, client: httpx.Client):
        """Test deprecated endpoint still works."""
        response = client.get("/router-docs/deprecated-endpoint")
        assert response.status_code == 200
        data = response.json()

        assert data["deprecated"] is True

    def test_router_docs_create_with_validation(self, client: httpx.Client):
        """Test router route with both validation + api_doc decorators."""
        response = client.post(
            "/router-docs/create",
            json={"name": "Doc User", "email": "doc@example.com", "age": 30},
        )
        assert response.status_code == 201
        data = response.json()

        assert data["name"] == "Doc User"
        assert data["email"] == "doc@example.com"

    def test_router_docs_create_invalid(self, client: httpx.Client):
        """Test validation still works with api_doc decorators on router."""
        response = client.post(
            "/router-docs/create",
            json={"name": "Incomplete"},  # missing email and age
        )
        assert response.status_code in [400, 422]


class TestAppMount:
    """Test app.mount() functionality."""

    def test_mount_api_v1_users(self, client: httpx.Client):
        """Test API v1 users endpoint after mounting."""
        response = client.get("/api/v1/users")
        assert response.status_code == 200
        data = response.json()

        assert data["version"] == "v1"
        assert "users" in data

    def test_mount_api_v2_users(self, client: httpx.Client):
        """Test API v2 users endpoint after mounting."""
        response = client.get("/api/v2/users")
        assert response.status_code == 200
        data = response.json()

        assert data["version"] == "v2"
        assert "data" in data
        assert "meta" in data

    def test_mount_with_prefix_router_validated(self, client: httpx.Client):
        """Test router mounted with explicit prefix."""
        response = client.post(
            "/router-validated/search",
            json={"q": "mount test"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["query"] == "mount test"

    def test_mount_router_docs_prefix(self, client: httpx.Client):
        """Test router mounted with its own prefix via mount(router)."""
        response = client.get("/router-docs/users")
        assert response.status_code == 200

    def test_mount_preserves_ctx_injection(self, client: httpx.Client):
        """Test that mounted router handlers get ctx injected."""
        # If ctx isn't injected, router handlers expecting (req, res, ctx) would crash
        response = client.get("/api/v1/users")
        assert response.status_code == 200

    def test_mount_preserves_error_handling(self, client: httpx.Client):
        """Test that mounted router routes benefit from app error handling."""
        response = client.get("/api/v1/users/9999")
        assert response.status_code == 404
        data = response.json()
        assert "error" in data


class TestRouterContextInjection:
    """Test that Router handlers receive context (ctx) properly."""

    def test_router_handler_receives_ctx(self, client: httpx.Client):
        """Test router route handler receives ctx after mounting."""
        # This tests the fix: _mount_router now wraps handlers with _wrap_handler
        # so ctx is properly injected
        response = client.get("/api/v1/users")
        assert response.status_code == 200

    def test_router_handler_with_validation_receives_ctx(self, client: httpx.Client):
        """Test router route with validation receives ctx after mounting."""
        response = client.post(
            "/router-validated/search",
            json={"q": "ctx test"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "ctx test"

    def test_router_handler_with_docs_receives_ctx(self, client: httpx.Client):
        """Test router route with API docs receives ctx after mounting."""
        response = client.get("/router-docs/users")
        assert response.status_code == 200

    def test_router_handler_stacked_decorators_receives_ctx(self, client: httpx.Client):
        """Test router route with stacked validation + docs receives ctx."""
        response = client.post(
            "/router-docs/create",
            json={"name": "Stacked", "email": "stacked@test.com", "age": 25},
        )
        assert response.status_code == 201


class TestRouterValidationErrorFormat:
    """Test error response format from router routes with validation."""

    def test_validation_error_is_json(self, client: httpx.Client):
        """Test validation errors return JSON response."""
        response = client.post(
            "/router-validated/search",
            json={},  # missing required 'q'
        )
        assert response.status_code in [400, 422]
        # Should return a JSON error
        data = response.json()
        assert "message" in data or "errors" in data or "error" in data

    def test_validation_error_invalid_type(self, client: httpx.Client):
        """Test type validation error response."""
        response = client.post(
            "/router-validated/items",
            json={"name": "Test", "price": "not_a_float"},
        )
        assert response.status_code in [400, 422]

    def test_validation_error_empty_body(self, client: httpx.Client):
        """Test empty body returns validation error."""
        response = client.post(
            "/router-validated/items",
            content=b"",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code in [400, 422]

    def test_validation_error_null_body(self, client: httpx.Client):
        """Test null body returns validation error."""
        response = client.post(
            "/router-validated/items",
            json=None,
        )
        assert response.status_code in [400, 422]
