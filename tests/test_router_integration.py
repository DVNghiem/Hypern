"""
Test cases for Router integration with validators and OpenAPI decorators.

Tests cover:
- Router + Json marker
- Router + Query marker
- Router + combined Json and Query markers
- Router + api_tags / api_doc / deprecated decorators
- Router + validation + api_doc (stacked decorators)
- app.mount() functionality
- Router handler ctx injection after mount
- Validation error responses from router routes
"""

import asyncio
import functools
import threading
import time
from types import SimpleNamespace

import httpx
import msgspec
import pytest

from hypern import Hypern, Router
from hypern._hypern import Route as RustRoute
from hypern.injection import HandlerPlan, Inject, InjectionConfigurationError, Json, Path
from tests.conftest import TestServerProcess as _TestServerProcess


class _CreateItem(msgspec.Struct):
    name: str


class _RequestService:
    next_identifier = 0

    def __init__(self) -> None:
        type(self).next_identifier += 1
        self.identifier = type(self).next_identifier


class _BindingRequest:
    def __init__(self, item_id: str, body: bytes) -> None:
        self._item_id = item_id
        self._body = body

    def param(self, name: str) -> str | None:
        return self._item_id if name == "item_id" else None

    def body_bytes(self) -> bytes:
        return self._body


class _BindingResponse(SimpleNamespace):
    def __init__(self) -> None:
        super().__init__(finished=False, payload=None)

    def json(self, payload: object) -> None:
        self.payload = payload
        self.finished = True

    def send(self, payload: object) -> None:
        self.json(payload)


def test_app_route_binds_path_json_and_request_provider() -> None:
    _RequestService.next_identifier = 0
    app = Hypern()
    assert app.provide(_RequestService, _RequestService, scope="request") is app

    @app.post("/items/:item_id")
    async def create_item(
        item_id: int = Path(),
        payload: _CreateItem = Json(),
        service: _RequestService = Inject(),
    ) -> dict[str, object]:
        return {"id": item_id, "name": payload.name, "service": service.identifier}

    app._freeze_registration()
    route = app.router.get_route("/items/:item_id", "POST")
    assert route is not None
    response = _BindingResponse()

    asyncio.run(
        route.function(
            _BindingRequest("7", b'{"name":"book"}'),
            response,
        )
    )

    assert response.payload == {"id": 7, "name": "book", "service": 1}


def test_mounted_router_binds_sync_handler_and_isolates_request_scope() -> None:
    _RequestService.next_identifier = 0
    app = Hypern()
    router = Router()
    app.provide(_RequestService, _RequestService, scope="request")

    @router.get("/services/:item_id")
    def get_service(
        res: object,
        item_id: int = Path(),
        first: _RequestService = Inject(),
        second: _RequestService = Inject(),
    ) -> None:
        assert first is second
        res.json({"id": item_id, "service": first.identifier})

    app.mount("/api", router)
    app._freeze_registration()
    route = app.router.get_route("/api/services/:item_id", "GET")
    assert route is not None

    responses = [_BindingResponse(), _BindingResponse()]
    for response in responses:
        asyncio.run(route.function(_BindingRequest("9", b""), response))

    assert [response.payload for response in responses] == [
        {"id": 9, "service": 1},
        {"id": 9, "service": 2},
    ]


def test_sync_route_pipeline_uses_direct_handler_plan_fast_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = Hypern()
    app.provide("value", "direct")

    @app.get("/direct-plan")
    def handler(value: str = Inject("value")) -> str:
        return value

    app._freeze_registration()
    route = app.router.get_route("/direct-plan", "GET")
    assert route is not None

    async def unexpected_async_invoke(*args: object, **kwargs: object) -> object:
        pytest.fail("synchronous route must not create a HandlerPlan invocation coroutine")

    monkeypatch.setattr(HandlerPlan, "invoke", unexpected_async_invoke)
    response = _BindingResponse()
    asyncio.run(route.function(_BindingRequest("", b""), response))

    assert response.payload == "direct"


def test_app_route_builder_uses_compiled_parameter_binding() -> None:
    app = Hypern()
    app.provide("value", "builder")

    def handler(res: object, value: str = Inject("value")) -> None:
        res.json({"value": value})

    app.route("/builder").get(handler)
    app._freeze_registration()
    route = app.router.get_route("/builder", "GET")
    assert route is not None
    response = _BindingResponse()

    asyncio.run(route.function(_BindingRequest("", b""), response))

    assert response.payload == {"value": "builder"}


def test_add_route_uses_compiled_parameter_binding() -> None:
    app = Hypern()
    app.provide("value", "direct")

    def handler(res: object, value: str = Inject("value")) -> None:
        res.json({"value": value})

    app.add_route("GET", "/direct", handler)
    app._freeze_registration()
    route = app.router.get_route("/direct", "GET")
    assert route is not None
    response = _BindingResponse()

    asyncio.run(route.function(_BindingRequest("", b""), response))

    assert response.payload == {"value": "direct"}


def test_router_route_added_after_mount_is_compiled_before_freeze() -> None:
    app = Hypern()
    router = Router()
    app.provide("value", "late-router")
    app.mount("/api", router)

    @router.get("/late")
    def handler(res: object, value: str = Inject("value")) -> None:
        res.json({"value": value})

    app._freeze_registration()
    route = app.router.get_route("/api/late", "GET")
    assert route is not None
    response = _BindingResponse()

    asyncio.run(route.function(_BindingRequest("", b""), response))

    assert response.payload == {"value": "late-router"}


def test_ordinary_decorator_does_not_bypass_handler_binding_validation() -> None:
    app = Hypern()

    def ordinary_decorator(handler):
        @functools.wraps(handler)
        def wrapped(*args, **kwargs):
            return handler(*args, **kwargs)

        return wrapped

    @app.get("/invalid-decorated")
    @ordinary_decorator
    def handler(req, res, ctx, unsupported):
        res.finished = True

    with pytest.raises(InjectionConfigurationError, match="unsupported source"):
        app._freeze_registration()


def test_constructor_routes_use_compiled_parameter_binding() -> None:
    def handler(res: object, value: str = Inject("value")) -> None:
        res.json({"value": value})

    app = Hypern(
        routes=[RustRoute(path="/constructor", function=handler, method="GET")]
    )
    app.provide("value", "constructor")
    app._freeze_registration()
    route = app.router.get_route("/constructor", "GET")
    assert route is not None
    response = _BindingResponse()

    asyncio.run(route.function(_BindingRequest("", b""), response))

    assert response.payload == {"value": "constructor"}


def test_app_route_builder_all_preserves_five_method_contract() -> None:
    app = Hypern()

    def handler(req, res):
        res.finished = True

    app.route("/five-methods").all(handler)

    for method in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
        assert app.router.get_route("/five-methods", method) is not None
    assert app.router.get_route("/five-methods", "OPTIONS") is None
    assert app.router.get_route("/five-methods", "HEAD") is None


def test_compiled_binding_runs_through_http_server(client: httpx.Client) -> None:
    response = client.post(
        "/compiled/items/7",
        json={"name": "book"},
    )

    assert response.status_code == 200
    assert response.json() == {"id": 7, "name": "book", "service": "request"}


def test_rust_workers_reuse_event_loops_without_per_request_asyncio_lookup(
    client: httpx.Client,
) -> None:
    initial_stats = client.get("/async/loop-runtime-stats")
    assert initial_stats.status_code == 200

    identities = []
    for _ in range(32):
        response = client.get("/async/loop-identity")
        assert response.status_code == 200
        identities.append(response.json())

    final_stats = client.get("/async/loop-runtime-stats")
    assert final_stats.status_code == 200

    loops_by_thread: dict[int, set[int]] = {}
    for identity in identities:
        loops_by_thread.setdefault(identity["thread_id"], set()).add(identity["loop_id"])

    assert len(identities) > len(loops_by_thread)
    assert all(len(loop_ids) == 1 for loop_ids in loops_by_thread.values())
    assert final_stats.json()["asyncio_imports"] == initial_stats.json()["asyncio_imports"]
    assert final_stats.json()["get_event_loop_calls"] == initial_stats.json()["get_event_loop_calls"]


def test_shutdown_rejects_queued_and_stops_active_async_handlers() -> None:
    server = _TestServerProcess(port=8767)
    request_finished = [threading.Event() for _ in range(24)]
    responses: list[tuple[int, str]] = []
    responses_lock = threading.Lock()

    def request_slow_handler(index: int) -> None:
        try:
            response = httpx.get(
                f"{server.base_url}/async/cancellation-resistant",
                timeout=10,
            )
            with responses_lock:
                responses.append((response.status_code, response.text))
        except httpx.RequestError:
            pass
        finally:
            request_finished[index].set()

    server.start()
    request_threads = [
        threading.Thread(target=request_slow_handler, args=(index,))
        for index in range(len(request_finished))
    ]
    for request_thread in request_threads:
        request_thread.start()
    time.sleep(0.5)
    assert server.process is not None
    started_at = time.monotonic()
    server.process.terminate()
    try:
        server.process.wait(timeout=4.5)
    finally:
        if server.process.poll() is None:
            server.process.kill()
            server.process.wait(timeout=1)
        server.process = None
    for request_thread in request_threads:
        request_thread.join(timeout=2)

    assert time.monotonic() - started_at < 4.5
    assert all(finished.is_set() for finished in request_finished)
    assert (503, "Service Unavailable") in responses


class TestRouterWithBodyValidation:
    """Test Router routes with the Json marker."""

    def test_router_json_valid(self, client: httpx.Client):
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

    def test_router_json_defaults(self, client: httpx.Client):
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

    def test_router_json_missing_required(self, client: httpx.Client):
        """Test missing required field returns 400."""
        response = client.post(
            "/router-validated/search",
            json={},  # missing required 'q'
        )
        assert response.status_code in [400, 422]

    def test_router_json_wrong_type(self, client: httpx.Client):
        """Test wrong type for field returns validation error."""
        response = client.post(
            "/router-validated/search",
            json={"q": "test", "page": "not_a_number"},
        )
        assert response.status_code in [400, 422]

    def test_router_json_invalid_json(self, client: httpx.Client):
        """Test invalid JSON body returns error."""
        response = client.post(
            "/router-validated/search",
            content=b"not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code in [400, 422]

    def test_router_json_create_item(self, client: httpx.Client):
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

    def test_router_json_create_item_all_fields(self, client: httpx.Client):
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

    def test_router_json_missing_required_name(self, client: httpx.Client):
        """Test missing required 'name' field returns error."""
        response = client.post(
            "/router-validated/items",
            json={"price": 9.99},
        )
        assert response.status_code in [400, 422]

    def test_router_json_missing_required_price(self, client: httpx.Client):
        """Test missing required 'price' field returns error."""
        response = client.post(
            "/router-validated/items",
            json={"name": "Incomplete"},
        )
        assert response.status_code in [400, 422]


class TestRouterWithQueryValidation:
    """Test Router routes with the Query marker."""

    def test_router_query_valid(self, client: httpx.Client):
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

    def test_router_query_defaults(self, client: httpx.Client):
        """Test query params use defaults when not provided."""
        response = client.get("/router-validated/items")
        assert response.status_code == 200
        data = response.json()

        assert data["page"] == 1
        assert data["limit"] == 10
        assert data["search"] == ""

    def test_router_query_partial(self, client: httpx.Client):
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
    """Test Router routes with Json and Query markers together."""

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
