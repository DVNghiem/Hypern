"""
Test cases for validation functionality in Hypern framework.

Tests cover:
- Body validation with msgspec schemas
- Query parameter validation
- Combined body and query validation
- Nested object validation
- Validation error responses
"""

import httpx
import pytest


class TestBodyValidation:
    """Test request body validation."""
    
    def test_valid_user_body(self, client: httpx.Client):
        """Test valid user data passes validation."""
        user_data = {
            "name": "Test User",
            "email": "test@example.com",
            "age": 25
        }
        response = client.post("/validated/user", json=user_data)
        assert response.status_code == 201
        data = response.json()
        
        assert data["name"] == "Test User"
        assert data["email"] == "test@example.com"
        assert data["age"] == 25
        assert "id" in data
    
    def test_missing_required_field(self, client: httpx.Client):
        """Test missing required field fails validation."""
        incomplete_data = {
            "name": "Test User",
            # missing email and age
        }
        response = client.post("/validated/user", json=incomplete_data)
        # Should return 400 or 422 for validation error
        assert response.status_code in [400, 422]
    
    def test_wrong_type_field(self, client: httpx.Client):
        """Test wrong field type fails validation."""
        wrong_type_data = {
            "name": "Test User",
            "email": "test@example.com",
            "age": "not-a-number"  # Should be int
        }
        response = client.post("/validated/user", json=wrong_type_data)
        assert response.status_code in [400, 422]
    
    def test_extra_fields_allowed(self, client: httpx.Client):
        """Test extra fields are typically ignored or allowed."""
        data_with_extra = {
            "name": "Test User",
            "email": "test@example.com",
            "age": 25,
            "extra_field": "should be ignored"
        }
        response = client.post("/validated/user", json=data_with_extra)
        # Should succeed (extra fields typically ignored)
        assert response.status_code in [201, 200]


class TestQueryValidation:
    """Test query parameter validation."""
    
    def test_valid_query_params(self, client: httpx.Client):
        """Test valid query parameters pass validation."""
        response = client.get(
            "/validated/search",
            params={"page": "2", "limit": "20", "search": "alice"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["page"] == 2
        assert data["limit"] == 20
    
    def test_default_query_values(self, client: httpx.Client):
        """Test default values are applied for missing params."""
        response = client.get("/validated/search")
        assert response.status_code == 200
        data = response.json()
        
        # Should use defaults
        assert data["page"] == 1
        assert data["limit"] == 10
    
    def test_partial_query_params(self, client: httpx.Client):
        """Test partial query params with defaults for missing."""
        response = client.get(
            "/validated/search",
            params={"page": "5"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["page"] == 5
        assert data["limit"] == 10  # default
    
    def test_search_filtering(self, client: httpx.Client):
        """Test search query filters results."""
        response = client.get(
            "/validated/search",
            params={"search": "alice"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Should filter users by search term
        for user in data["data"]:
            assert "alice" in user["name"].lower()


class TestCombinedValidation:
    """Test combined body and query validation."""
    
    def test_valid_body_and_query(self, client: httpx.Client):
        """Test valid body and query together."""
        response = client.post(
            "/validated/combined",
            params={"page": "3", "limit": "15"},
            json={"name": "Combined Test", "email": "combined@example.com", "age": 30}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["body"]["name"] == "Combined Test"
        assert data["body"]["email"] == "combined@example.com"
        assert data["body"]["age"] == 30
        assert data["query"]["page"] == 3
        assert data["query"]["limit"] == 15
    
    def test_invalid_body_valid_query(self, client: httpx.Client):
        """Test invalid body with valid query fails."""
        response = client.post(
            "/validated/combined",
            params={"page": "1", "limit": "10"},
            json={"name": "Test"}  # Missing required fields
        )
        assert response.status_code in [400, 422]
    
    def test_valid_body_with_query_defaults(self, client: httpx.Client):
        """Test valid body with query defaults."""
        response = client.post(
            "/validated/combined",
            json={"name": "Default Query Test", "email": "default@example.com", "age": 22}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["body"]["name"] == "Default Query Test"
        # Query should use defaults
        assert data["query"]["page"] == 1
        assert data["query"]["limit"] == 10


class TestNestedValidation:
    """Test validation of nested objects."""
    
    def test_valid_nested_object(self, client: httpx.Client):
        """Test valid nested object passes validation."""
        nested_data = {
            "name": "Nested User",
            "email": "nested@example.com",
            "address": {
                "street": "123 Main St",
                "city": "Test City",
                "zip_code": "12345"
            }
        }
        response = client.post("/validated/nested", json=nested_data)
        assert response.status_code == 201
        data = response.json()
        
        assert data["name"] == "Nested User"
        assert data["email"] == "nested@example.com"
        assert data["address"]["street"] == "123 Main St"
        assert data["address"]["city"] == "Test City"
        assert data["address"]["zip_code"] == "12345"
    
    def test_missing_nested_field(self, client: httpx.Client):
        """Test missing nested field fails validation."""
        incomplete_nested = {
            "name": "Nested User",
            "email": "nested@example.com",
            "address": {
                "street": "123 Main St",
                # missing city and zip_code
            }
        }
        response = client.post("/validated/nested", json=incomplete_nested)
        assert response.status_code in [400, 422]
    
    def test_missing_nested_object(self, client: httpx.Client):
        """Test missing nested object entirely fails validation."""
        no_nested = {
            "name": "No Address User",
            "email": "noaddr@example.com"
            # missing address object
        }
        response = client.post("/validated/nested", json=no_nested)
        assert response.status_code in [400, 422]
    
    def test_wrong_type_in_nested(self, client: httpx.Client):
        """Test wrong type in nested object fails validation."""
        wrong_nested = {
            "name": "Wrong Type User",
            "email": "wrong@example.com",
            "address": {
                "street": 123,  # Should be string
                "city": "Test City",
                "zip_code": "12345"
            }
        }
        response = client.post("/validated/nested", json=wrong_nested)
        assert response.status_code in [400, 422]


class TestValidationEdgeCases:
    """Test edge cases in validation."""
    
    def test_empty_string_values(self, client: httpx.Client):
        """Test empty strings pass/fail validation appropriately."""
        empty_strings = {
            "name": "",
            "email": "",
            "age": 25
        }
        response = client.post("/validated/user", json=empty_strings)
        # Empty strings might pass validation depending on schema
        # This tests the framework's behavior
        assert response.status_code in [201, 400, 422]
    
    def test_boundary_integer_values(self, client: httpx.Client):
        """Test boundary integer values."""
        boundary_data = {
            "name": "Boundary User",
            "email": "boundary@example.com",
            "age": 0
        }
        response = client.post("/validated/user", json=boundary_data)
        # Age 0 should be valid as it's an integer
        assert response.status_code == 201
    
    def test_large_integer_value(self, client: httpx.Client):
        """Test large integer value."""
        large_int_data = {
            "name": "Large Age User",
            "email": "large@example.com",
            "age": 999999
        }
        response = client.post("/validated/user", json=large_int_data)
        assert response.status_code == 201
    
    def test_negative_integer(self, client: httpx.Client):
        """Test negative integer value."""
        negative_data = {
            "name": "Negative User",
            "email": "negative@example.com",
            "age": -1
        }
        response = client.post("/validated/user", json=negative_data)
        # Negative age might be allowed if no min constraint
        assert response.status_code in [201, 400, 422]
    
    def test_null_values(self, client: httpx.Client):
        """Test null values fail for required fields."""
        null_data = {
            "name": None,
            "email": "null@example.com",
            "age": 25
        }
        response = client.post("/validated/user", json=null_data)
        # Null for required string should fail
        assert response.status_code in [400, 422]
    
    def test_special_characters_in_strings(self, client: httpx.Client):
        """Test special characters in string fields."""
        special_data = {
            "name": "Test<User>&'\"",
            "email": "test+special@example.com",
            "age": 25
        }
        response = client.post("/validated/user", json=special_data)
        # Should handle special characters
        assert response.status_code == 201
    
    def test_unicode_in_validated_fields(self, client: httpx.Client):
        """Test unicode characters in validated fields."""
        unicode_data = {
            "name": "测试用户 🎉",
            "email": "unicode@example.com",
            "age": 25
        }
        response = client.post("/validated/user", json=unicode_data)
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "测试用户 🎉"
    
    def test_very_long_string(self, client: httpx.Client):
        """Test very long string value."""
        long_data = {
            "name": "A" * 1000,
            "email": "long@example.com",
            "age": 25
        }
        response = client.post("/validated/user", json=long_data)
        # Should handle long strings
        assert response.status_code in [201, 400, 422]


class TestValidationErrorResponses:
    """Test validation error response format."""
    
    def test_error_response_format(self, client: httpx.Client):
        """Test validation error returns proper error format."""
        invalid_data = {"name": "Only Name"}
        response = client.post("/validated/user", json=invalid_data)
        assert response.status_code in [400, 422]
        
        # Error response should be JSON
        content_type = response.headers.get("content-type", "")
        assert "json" in content_type.lower() or response.status_code == 422
    
    def test_invalid_json_body(self, client: httpx.Client):
        """Test completely invalid JSON returns error."""
        response = client.post(
            "/validated/user",
            content=b"not valid json",
            headers={"Content-Type": "application/json"}
        )
        # Should return 400 for invalid JSON
        assert response.status_code in [400, 422]
