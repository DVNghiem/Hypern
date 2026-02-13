"""
Test cases for request and response handling in Hypern framework.

Tests cover:
- Request data access (headers, cookies, body, form data)
- Response types (JSON, HTML, text, XML)
- Response headers and status codes
- Cookies (set, secure, clear)
- Cache control
- Redirects
"""

import httpx
import pytest


class TestRequestHeaders:
    """Test request header handling."""
    
    def test_custom_header_access(self, client: httpx.Client):
        """Test accessing custom request header."""
        response = client.get(
            "/headers-echo",
            headers={"X-Custom-Header": "custom-value-123"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["custom_header"] == "custom-value-123"
    
    def test_multiple_headers(self, client: httpx.Client):
        """Test accessing multiple request headers."""
        headers = {
            "X-Custom-Header": "test",
            "X-Another-Header": "another-value",
            "Accept-Language": "en-US"
        }
        response = client.get("/headers-echo", headers=headers)
        assert response.status_code == 200
        data = response.json()
        
        all_headers = data["all_headers"]
        assert "x-custom-header" in all_headers or "X-Custom-Header" in all_headers
    
    def test_standard_headers_accessible(self, client: httpx.Client):
        """Test that standard HTTP headers are accessible."""
        response = client.get(
            "/headers-echo",
            headers={"User-Agent": "TestClient/1.0"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Headers should be present
        assert "all_headers" in data


class TestRequestCookies:
    """Test request cookie handling."""
    
    def test_cookie_access(self, client: httpx.Client):
        """Test accessing request cookies."""
        response = client.get(
            "/cookies-echo",
            cookies={"session_id": "sess-abc123", "auth_token": "token-xyz"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["session_id"] == "sess-abc123"
        assert data["auth_token"] == "token-xyz"
    
    def test_missing_cookie(self, client: httpx.Client):
        """Test accessing non-existent cookie returns None."""
        response = client.get("/cookies-echo")
        assert response.status_code == 200
        data = response.json()
        
        # Missing cookies should be None
        assert data["session_id"] is None


class TestRequestBody:
    """Test request body handling."""
    
    def test_json_body(self, client: httpx.Client):
        """Test JSON request body parsing."""
        test_data = {
            "string": "value",
            "number": 42,
            "array": [1, 2, 3],
            "nested": {"key": "value"}
        }
        response = client.post("/echo", json=test_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["echo"] == test_data
    
    def test_form_data(self, client: httpx.Client):
        """Test form data parsing."""
        form_data = {"username": "testuser", "password": "secret123"}
        response = client.post("/form-data", data=form_data)
        assert response.status_code == 200
        data = response.json()
        
        assert "form" in data
    
    def test_text_body(self, client: httpx.Client):
        """Test raw text body."""
        text_content = "This is plain text content"
        response = client.post(
            "/text-body",
            content=text_content,
            headers={"Content-Type": "text/plain"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["text"] == text_content
    
    def test_binary_body(self, client: httpx.Client):
        """Test binary body handling."""
        binary_data = b"\x00\x01\x02\x03\x04\x05"
        response = client.post(
            "/binary-body",
            content=binary_data,
            headers={"Content-Type": "application/octet-stream"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["length"] == len(binary_data)
        assert data["type"] == "bytes"


class TestResponseJSON:
    """Test JSON response handling."""
    
    def test_json_response_types(self, client: httpx.Client):
        """Test JSON response with various data types."""
        response = client.get("/response/json")
        assert response.status_code == 200
        
        content_type = response.headers.get("content-type", "")
        assert "application/json" in content_type
        
        data = response.json()
        assert data["string"] == "value"
        assert data["number"] == 42
        assert data["float"] == 3.14
        assert data["boolean"] is True
        assert data["null"] is None
        assert data["array"] == [1, 2, 3]
        assert data["nested"] == {"key": "value"}


class TestResponseHTML:
    """Test HTML response handling."""
    
    def test_html_response(self, client: httpx.Client):
        """Test HTML response content type and body."""
        response = client.get("/response/html")
        assert response.status_code == 200
        
        content_type = response.headers.get("content-type", "")
        assert "text/html" in content_type
        
        assert "<html>" in response.text
        assert "<h1>Hello HTML</h1>" in response.text


class TestResponseText:
    """Test plain text response handling."""
    
    def test_text_response(self, client: httpx.Client):
        """Test plain text response."""
        response = client.get("/response/text")
        assert response.status_code == 200
        
        content_type = response.headers.get("content-type", "")
        assert "text/plain" in content_type
        
        assert response.text == "Plain text response"


class TestResponseXML:
    """Test XML response handling."""
    
    def test_xml_response(self, client: httpx.Client):
        """Test XML response content type and body."""
        response = client.get("/response/xml")
        assert response.status_code == 200
        
        content_type = response.headers.get("content-type", "")
        assert "xml" in content_type.lower()
        
        assert "<root>" in response.text
        assert "<item>value</item>" in response.text


class TestStatusCodes:
    """Test HTTP status code responses."""
    
    def test_status_200(self, client: httpx.Client):
        """Test 200 OK status."""
        response = client.get("/response/status/200")
        assert response.status_code == 200
        data = response.json()
        assert data["status_code"] == 200
    
    def test_status_201(self, client: httpx.Client):
        """Test 201 Created status."""
        response = client.get("/response/status/201")
        assert response.status_code == 201
        data = response.json()
        assert data["status_code"] == 201
    
    def test_status_204(self, client: httpx.Client):
        """Test 204 No Content status."""
        response = client.get("/response/status/204")
        assert response.status_code == 204
    
    def test_status_400(self, client: httpx.Client):
        """Test 400 Bad Request status."""
        response = client.get("/response/status/400")
        assert response.status_code == 400
    
    def test_status_404(self, client: httpx.Client):
        """Test 404 Not Found status."""
        response = client.get("/response/status/404")
        assert response.status_code == 404
    
    def test_status_500(self, client: httpx.Client):
        """Test 500 Internal Server Error status."""
        response = client.get("/response/status/500")
        assert response.status_code == 500


class TestResponseHeaders:
    """Test response header setting."""
    
    def test_custom_response_headers(self, client: httpx.Client):
        """Test setting custom response headers."""
        response = client.get("/response/headers")
        assert response.status_code == 200
        
        assert response.headers.get("x-custom-response") == "test-value"
        assert response.headers.get("x-another-header") == "another-value"


class TestRedirects:
    """Test redirect responses."""
    
    def test_temporary_redirect(self, client: httpx.Client):
        """Test 302 temporary redirect."""
        response = client.get("/response/redirect", follow_redirects=False)
        assert response.status_code == 302
        assert "location" in response.headers
    
    def test_permanent_redirect(self, client: httpx.Client):
        """Test 301 permanent redirect."""
        response = client.get("/response/redirect-permanent", follow_redirects=False)
        assert response.status_code == 301
        assert "location" in response.headers
    
    def test_redirect_following(self, client: httpx.Client):
        """Test redirect is followed when enabled."""
        response = client.get("/response/redirect", follow_redirects=True)
        # Should end up at home page
        assert response.status_code == 200


class TestCookieResponses:
    """Test cookie setting in responses."""
    
    def test_set_cookies(self, client: httpx.Client):
        """Test setting cookies in response."""
        response = client.get("/cookies/set")
        assert response.status_code == 200
        
        assert "session_id" in response.cookies
        assert response.cookies["session_id"] == "abc123"
        
        assert "preferences" in response.cookies
    
    def test_set_secure_cookie(self, client: httpx.Client):
        """Test setting secure cookie with options."""
        response = client.get("/cookies/set-secure")
        assert response.status_code == 200
        
        # Cookie should be set
        set_cookie = response.headers.get("set-cookie", "")
        assert "secure_token" in set_cookie.lower() or "secure" in set_cookie.lower()
    
    def test_clear_cookie(self, client: httpx.Client):
        """Test clearing a cookie."""
        response = client.get("/cookies/clear")
        assert response.status_code == 200
        
        # Check for Set-Cookie header that clears the cookie
        set_cookie = response.headers.get("set-cookie", "")
        # Clearing cookie typically sets max-age=0 or expires in past
        assert "session_id" in set_cookie.lower() or len(set_cookie) > 0


class TestCacheControl:
    """Test cache control headers."""
    
    def test_cache_enabled(self, client: httpx.Client):
        """Test cache control with max-age."""
        response = client.get("/cache/enabled")
        assert response.status_code == 200
        
        cache_control = response.headers.get("cache-control", "")
        assert "max-age" in cache_control
    
    def test_cache_disabled(self, client: httpx.Client):
        """Test no-cache response."""
        response = client.get("/cache/disabled")
        assert response.status_code == 200
        
        cache_control = response.headers.get("cache-control", "")
        # Should have no-cache or no-store
        assert "no-cache" in cache_control or "no-store" in cache_control


class TestComplexRequestScenarios:
    """Test complex request scenarios."""
    
    def test_request_with_headers_and_body(self, client: httpx.Client):
        """Test request with both headers and JSON body."""
        response = client.post(
            "/echo",
            json={"data": "test"},
            headers={"X-Request-Id": "req-123"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["echo"]["data"] == "test"
    
    def test_request_with_query_and_body(self, client: httpx.Client):
        """Test POST request with query params and body."""
        response = client.post(
            "/validated/combined",
            params={"page": "2", "limit": "5"},
            json={"name": "Test", "email": "test@example.com", "age": 25}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["query"]["page"] == 2
        assert data["query"]["limit"] == 5
        assert data["body"]["name"] == "Test"
    
    def test_large_json_body(self, client: httpx.Client):
        """Test handling large JSON body."""
        large_data = {
            "items": [{"id": i, "value": f"item_{i}"} for i in range(100)],
            "metadata": {"count": 100, "type": "bulk"}
        }
        response = client.post("/echo", json=large_data)
        assert response.status_code == 200
        data = response.json()
        
        assert len(data["echo"]["items"]) == 100
    
    def test_unicode_in_body(self, client: httpx.Client):
        """Test handling unicode characters in body."""
        unicode_data = {
            "message": "Hello, 世界! 🌍 Привет",
            "emoji": "🎉🎊🎁"
        }
        response = client.post("/echo", json=unicode_data)
        assert response.status_code == 200
        data = response.json()
        
        assert data["echo"]["message"] == unicode_data["message"]
        assert data["echo"]["emoji"] == unicode_data["emoji"]
    
    def test_empty_body(self, client: httpx.Client):
        """Test request with empty JSON body."""
        response = client.post("/echo", json={})
        assert response.status_code == 200
        data = response.json()
        
        assert data["echo"] == {}

class TestFileUpload:
    """Test file upload handling."""
    
    def test_single_file_upload(self, client: httpx.Client):
        """Test uploading a single file."""
        file_content = b"This is test file content"
        files = {"document": ("test.txt", file_content, "text/plain")}
        
        response = client.post("/upload/single", files=files)
        assert response.status_code == 200
        data = response.json()
        
        assert data["uploaded"] is True
        assert data["filename"] == "test.txt"
        assert data["size"] == len(file_content)
        assert data["content_type"] == "text/plain"
        assert data["name"] == "document"
    
    def test_multiple_files_upload(self, client: httpx.Client):
        """Test uploading multiple files."""
        files = [
            ("files", ("file1.txt", b"Content 1", "text/plain")),
            ("files", ("file2.txt", b"Content 2", "text/plain")),
            ("files", ("image.jpg", b"\xff\xd8\xff\xe0", "image/jpeg"))
        ]
        
        response = client.post("/upload/multiple", files=files)
        assert response.status_code == 200
        data = response.json()
        
        assert data["uploaded"] == 3
        assert len(data["files"]) == 3
    
    def test_file_upload_with_form_fields(self, client: httpx.Client):
        """Test file upload combined with form fields."""
        files = {"document": ("data.txt", b"File content", "text/plain")}
        data_fields = {"title": "Test Document", "description": "A test file"}
        
        response = client.post("/upload/with-fields", files=files, data=data_fields)
        assert response.status_code == 200
        data = response.json()
        
        assert data["has_file"] is True
        assert data["fields"]["title"] == "Test Document"
        assert data["fields"]["description"] == "A test file"
        assert data["file"]["filename"] == "data.txt"
    
    def test_upload_without_file(self, client: httpx.Client):
        """Test upload endpoint without file returns error."""
        response = client.post("/upload/single")
        assert response.status_code == 400
        data = response.json()
        
        assert "error" in data
    
    def test_large_file_upload(self, client: httpx.Client):
        """Test uploading a larger file."""
        # Create 1MB file
        large_content = b"A" * (1024 * 1024)
        files = {"document": ("large.bin", large_content, "application/octet-stream")}
        
        response = client.post("/upload/single", files=files)
        assert response.status_code == 200
        data = response.json()
        
        assert data["size"] == 1024 * 1024
        assert data["filename"] == "large.bin"


class TestFileDownload:
    """Test file download and attachment responses."""
    
    def test_text_file_download(self, client: httpx.Client):
        """Test downloading a text file as attachment."""
        response = client.get("/download/text")
        assert response.status_code == 200
        
        # Check Content-Disposition header for attachment
        content_disposition = response.headers.get("content-disposition", "")
        assert "attachment" in content_disposition.lower()
        assert "sample.txt" in content_disposition
        
        # Verify content
        assert "This is a sample text file" in response.text
    
    def test_json_file_download(self, client: httpx.Client):
        """Test downloading JSON data as attachment."""
        response = client.get("/download/json")
        assert response.status_code == 200
        
        content_disposition = response.headers.get("content-disposition", "")
        assert "attachment" in content_disposition.lower()
        assert "data.json" in content_disposition
        
        data = response.json()
        assert data["message"] == "Hello"
        assert data["data"] == [1, 2, 3]
    
    def test_binary_file_download(self, client: httpx.Client):
        """Test downloading binary data."""
        response = client.get("/download/binary")
        assert response.status_code == 200
        
        content_disposition = response.headers.get("content-disposition", "")
        assert "attachment" in content_disposition.lower()
        assert "data.bin" in content_disposition
        
        # Verify binary content
        assert response.content == b"Hello"
    
    def test_custom_filename_download(self, client: httpx.Client):
        """Test downloading with custom filename."""
        response = client.get("/download/custom/myfile.pdf")
        assert response.status_code == 200
        
        content_disposition = response.headers.get("content-disposition", "")
        assert "attachment" in content_disposition.lower()
        assert "myfile.pdf" in content_disposition
        
        assert "Content for myfile.pdf" in response.text
    
    def test_download_content_type(self, client: httpx.Client):
        """Test that download sets appropriate content type."""
        response = client.get("/download/binary")
        assert response.status_code == 200
        
        content_type = response.headers.get("content-type", "")
        assert "application/octet-stream" in content_type