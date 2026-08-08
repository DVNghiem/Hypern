"""Focused contract tests for the application-owned Python request pipeline."""

import asyncio
import inspect
from types import SimpleNamespace

import msgspec
import pytest

from hypern import Hypern, Middleware, Router
from hypern import application as application_module
from hypern.middleware import middleware
from hypern.injection import Inject, Json


class _PipelinePayload(msgspec.Struct):
    quantity: int


class _PipelineRequest(SimpleNamespace):
    def body_bytes(self) -> bytes:
        return self.body


class _PipelineResponse(SimpleNamespace):
    def __init__(self) -> None:
        super().__init__(finished=False, status_code=200, payload=None)

    def status(self, status_code: int) -> "_PipelineResponse":
        self.status_code = status_code
        return self

    def json(self, payload: object) -> None:
        self.payload = payload
        self.finished = True


def test_compiled_binding_runs_inside_existing_middleware_pipeline() -> None:
    events: list[str] = []
    app = Hypern()
    app.provide("value", "bound")

    async def pipeline_middleware(req, res, ctx, next_fn):
        events.append("before")
        await next_fn()
        events.append("after")

    app.use(pipeline_middleware)

    @app.get("/bound")
    def handler(res: object, value: str = Inject("value")) -> None:
        events.append(value)
        res.json({"value": value})

    app._freeze_registration()
    route = app.router.get_route("/bound", "GET")
    assert route is not None
    response = _PipelineResponse()

    asyncio.run(route.function(_PipelineRequest(body=b""), response))

    assert events == ["before", "bound", "after"]
    assert response.payload == {"value": "bound"}


def test_marker_validation_error_uses_existing_exception_pipeline() -> None:
    app = Hypern()

    @app.errorhandler(msgspec.ValidationError)
    def handle_validation(req, res, error):
        res.status(422).json({"error": str(error)})

    @app.post("/payload")
    def handler(res: object, payload: _PipelinePayload = Json()) -> None:
        res.json({"quantity": payload.quantity})

    app._freeze_registration()
    route = app.router.get_route("/payload", "POST")
    assert route is not None
    response = _PipelineResponse()

    asyncio.run(
        route.function(
            _PipelineRequest(body=b'{"quantity":"invalid"}'),
            response,
        )
    )

    assert response.status_code == 422
    assert "quantity" in response.payload["error"]


def test_legacy_request_hook_apis_are_not_exposed():
    app = Hypern()
    router = Router()

    assert not hasattr(app, "before_request")
    assert not hasattr(app, "after_request")
    assert not hasattr(router, "before")
    assert not hasattr(router, "after")


def test_start_propagates_invalid_rust_middleware_registration(monkeypatch):
    class FakeServer:
        registered: list[object] = []

        def set_router(self, router):
            pass

        def set_reload_config(self, config):
            pass

        def use_middleware(self, middleware):
            self.registered.append(middleware)
            raise TypeError("invalid Rust middleware")

        def start(self, **kwargs):
            pass

        def get_reload_manager(self):
            return None

    monkeypatch.setattr(application_module, "Server", FakeServer)
    app = Hypern()
    invalid_middleware = object()
    app.use(invalid_middleware)

    with pytest.raises(TypeError, match="invalid Rust middleware"):
        app.start(host="127.0.0.1", port=0)

    assert FakeServer.registered == [invalid_middleware]


def test_start_does_not_register_python_middleware_with_rust_server(monkeypatch):
    class FakeServer:
        def set_router(self, router):
            pass

        def set_reload_config(self, config):
            pass

        def use_middleware(self, middleware):
            raise AssertionError("Python middleware must stay in the Python pipeline")

        def start(self, **kwargs):
            pass

        def get_reload_manager(self):
            return None

    monkeypatch.setattr(application_module, "Server", FakeServer)
    app = Hypern()

    async def python_middleware(req, res, ctx, next_fn):
        await next_fn()

    app.use(python_middleware)
    app.start(host="127.0.0.1", port=0)

    with pytest.raises(RuntimeError, match="registration is frozen after listen"):
        app.provide("late", object())


def test_listen_compiles_pipeline_descriptors_before_requests(monkeypatch):
    events: list[str] = []
    app = Hypern()

    async def middleware(req, res, ctx, next_fn):
        events.append("middleware")
        await next_fn()

    app.use(middleware)

    @app.get("/compiled")
    def handler(req, res, ctx):
        events.append("handler")
        res.finished = True

    monkeypatch.setattr(app, "start", lambda **kwargs: None)
    app.listen(callback=lambda: None)

    def fail_request_time_selection(req):
        raise AssertionError("middleware selection must not run per request")

    monkeypatch.setattr(app, "_python_middleware_for", fail_request_time_selection)
    route = app.router.get_route("/compiled", "GET")
    assert route is not None

    for _ in range(2):
        asyncio.run(route.function(SimpleNamespace(path="/compiled"), SimpleNamespace(finished=False)))

    assert events == ["middleware", "handler", "middleware", "handler"]


def test_listen_freezes_app_and_mounted_router_registration(monkeypatch):
    app = Hypern()
    router = Router()

    @router.get("/ready")
    def ready(req, res, ctx):
        res.finished = True

    app.mount(router)
    monkeypatch.setattr(app, "start", lambda **kwargs: None)
    app.listen(callback=lambda: None)

    async def middleware(req, res, ctx, next_fn):
        await next_fn()

    def handler(req, res, ctx):
        res.finished = True

    with pytest.raises(RuntimeError, match="registration is frozen after listen"):
        app.use(middleware)
    with pytest.raises(RuntimeError, match="registration is frozen after listen"):
        app.get("/late")(handler)
    with pytest.raises(RuntimeError, match="registration is frozen after listen"):
        app.mount(Router())
    with pytest.raises(RuntimeError, match="registration is frozen after listen"):
        app.provide("late", object())

    with pytest.raises(RuntimeError, match="registration is frozen after listen"):
        router.use(middleware)
    with pytest.raises(RuntimeError, match="registration is frozen after listen"):
        router.get("/late")(handler)


@pytest.mark.skip(reason="Legacy request hooks were removed")
def test_mounted_router_uses_one_pipeline_for_hooks_and_middleware():
    events: list[str] = []
    contexts: list[object] = []
    app = Hypern()
    router = Router()

    @app.before_request
    def app_before(req, res, ctx):
        contexts.append(ctx)
        events.append("app-before")

    @router.before_with_context
    async def router_before(req, res, ctx):
        contexts.append(ctx)
        events.append("router-before")

    def route_before(req, res, ctx):
        contexts.append(ctx)
        events.append("route-before")

    def route_after_first(req, res, ctx):
        contexts.append(ctx)
        events.append("route-after-first")

    async def route_after_second(req, res, ctx):
        contexts.append(ctx)
        events.append("route-after-second")

    async def app_middleware(req, res, ctx, next_fn):
        contexts.append(ctx)
        events.append("app-middleware-before")
        await next_fn()
        events.append("app-middleware-after")

    async def router_middleware(req, res, ctx, next_fn):
        contexts.append(ctx)
        events.append("router-middleware-before")
        await next_fn()
        events.append("router-middleware-after")

    async def route_middleware(req, res, ctx, next_fn):
        contexts.append(ctx)
        events.append("route-middleware-before")
        await next_fn()
        events.append("route-middleware-after")

    app.use(app_middleware)
    router.use(router_middleware)

    @router.get(
        "/items",
        middleware=[route_middleware],
        before_hooks=[route_before],
        after_hooks=[route_after_first, route_after_second],
    )
    def handler(req, res, ctx):
        contexts.append(ctx)
        events.append("handler")
        res.finished = True

    @router.after_with_context
    def router_after_first(req, res, ctx):
        contexts.append(ctx)
        events.append("router-after-first")

    @router.after_with_context
    async def router_after_second(req, res, ctx):
        contexts.append(ctx)
        events.append("router-after-second")

    @app.after_request
    async def app_after_first(req, res, ctx):
        contexts.append(ctx)
        events.append("app-after-first")

    @app.after_request
    def app_after_second(req, res, ctx):
        contexts.append(ctx)
        events.append("app-after-second")

    app.mount("/api", router)
    route = app.router.get_route("/api/items", "GET")
    assert route is not None

    request = SimpleNamespace(path="/api/items")
    response = SimpleNamespace(finished=False)
    asyncio.run(route.function(request, response))

    assert events == [
        "app-before",
        "router-before",
        "app-middleware-before",
        "router-middleware-before",
        "route-before",
        "route-middleware-before",
        "handler",
        "route-middleware-after",
        "router-middleware-after",
        "app-middleware-after",
        "route-after-second",
        "route-after-first",
        "router-after-second",
        "router-after-first",
        "app-after-second",
        "app-after-first",
    ]
    assert contexts
    assert all(ctx is contexts[0] for ctx in contexts)


@pytest.mark.skip(reason="Legacy request hooks were removed")
def test_app_before_short_circuit_only_unwinds_the_app_scope():
    events: list[str] = []
    app = Hypern()
    router = Router()

    @app.before_request
    def app_before(req, res, ctx):
        events.append("app-before")
        res.finished = True

    @router.before
    def router_before(req, res):
        events.append("router-before")

    @router.get("/blocked")
    def handler(req, res, ctx):
        events.append("handler")

    @router.after
    def router_after(req, res):
        events.append("router-after")

    @app.after_request
    def app_after(req, res, ctx):
        events.append("app-after")

    app.mount(router)
    route = app.router.get_route("/blocked", "GET")
    assert route is not None

    request = SimpleNamespace(path="/blocked")
    response = SimpleNamespace(finished=False)
    asyncio.run(route.function(request, response))

    assert events == ["app-before", "app-after"]


@pytest.mark.skip(reason="Legacy request hooks were removed")
def test_mounted_router_supports_documented_two_argument_hooks():
    events: list[str] = []
    app = Hypern()
    router = Router()

    @router.before
    def sync_before(req, res):
        events.append("sync-before")

    @router.before
    async def async_before(req, res):
        events.append("async-before")

    @router.get("/hooks")
    def handler(req, res, ctx):
        events.append("handler")
        res.finished = True

    @router.after
    def sync_after(req, res):
        events.append("sync-after")

    @router.after
    async def async_after(req, res):
        events.append("async-after")

    app.mount(router)
    route = app.router.get_route("/hooks", "GET")
    assert route is not None

    request = SimpleNamespace(path="/hooks")
    response = SimpleNamespace(finished=False)
    asyncio.run(route.function(request, response))

    assert events == [
        "sync-before",
        "async-before",
        "handler",
        "async-after",
        "sync-after",
    ]


@pytest.mark.skip(reason="Legacy request hooks were removed")
def test_exception_after_next_is_not_handled_by_a_noop_error_handler():
    events: list[str] = []
    app = Hypern()
    router = Router()

    async def fails_after_next(req, res, ctx, next_fn):
        await next_fn()
        raise RuntimeError("after next")

    def route_after(req, res, ctx):
        events.append("route-after")

    @app.errorhandler(RuntimeError)
    def noop_error_handler(req, res, error):
        events.append("error-handler")

    @router.get(
        "/failure",
        middleware=[fails_after_next],
        after_hooks=[route_after],
    )
    def handler(req, res, ctx):
        events.append("handler")
        res.finished = True

    app.mount(router)
    route = app.router.get_route("/failure", "GET")
    assert route is not None

    request = SimpleNamespace(path="/failure")
    response = SimpleNamespace(finished=False)
    with pytest.raises(RuntimeError, match="after next"):
        asyncio.run(route.function(request, response))

    assert events == ["handler", "error-handler", "route-after"]


@pytest.mark.skip(reason="Legacy request hooks were removed")
def test_route_short_circuit_unwinds_route_router_and_app_hooks():
    events: list[str] = []
    app = Hypern()
    router = Router()

    async def short_circuit(req, res, ctx, next_fn):
        events.append("short-circuit")
        res.finished = True

    def route_after(req, res, ctx):
        events.append("route-after")

    @router.after
    def router_after(req, res):
        events.append("router-after")

    @app.after_request
    def app_after(req, res, ctx):
        events.append("app-after")

    @router.get(
        "/short-circuit",
        middleware=[short_circuit],
        after_hooks=[route_after],
    )
    def handler(req, res, ctx):
        events.append("handler")

    app.mount(router)
    route = app.router.get_route("/short-circuit", "GET")
    assert route is not None

    request = SimpleNamespace(path="/short-circuit")
    response = SimpleNamespace(finished=False)
    asyncio.run(route.function(request, response))

    assert events == [
        "short-circuit",
        "route-after",
        "router-after",
        "app-after",
    ]


@pytest.mark.skip(reason="Legacy request hooks were removed")
def test_handled_preterminal_failure_unwinds_route_router_and_app_hooks():
    events: list[str] = []
    app = Hypern()
    router = Router()

    async def fail_after_partial_response(req, res, ctx, next_fn):
        events.append("middleware")
        res.status_code = 409
        raise ValueError("partial response")

    def route_after(req, res, ctx):
        events.append("route-after")

    @router.after
    def router_after(req, res):
        events.append("router-after")

    @app.after_request
    def app_after(req, res, ctx):
        events.append("app-after")

    @app.errorhandler(ValueError)
    def handle_value_error(req, res, error):
        events.append("error-handler")
        res.finished = True

    @router.get(
        "/handled-failure",
        middleware=[fail_after_partial_response],
        after_hooks=[route_after],
    )
    def handler(req, res, ctx):
        events.append("handler")

    app.mount(router)
    route = app.router.get_route("/handled-failure", "GET")
    assert route is not None

    request = SimpleNamespace(path="/handled-failure")
    response = SimpleNamespace(finished=False, status_code=200)
    asyncio.run(route.function(request, response))

    assert response.status_code == 409
    assert events == [
        "middleware",
        "error-handler",
        "route-after",
        "router-after",
        "app-after",
    ]


def test_preterminal_failure_is_not_handled_by_a_noop_error_handler():
    app = Hypern()
    router = Router()

    async def fail_after_partial_response(req, res, ctx, next_fn):
        res.status_code = 409
        raise ValueError("partial response")

    @app.errorhandler(ValueError)
    def noop_error_handler(req, res, error):
        pass

    @router.get("/unhandled", middleware=[fail_after_partial_response])
    def handler(req, res, ctx):
        res.finished = True

    app.mount(router)
    app._freeze_registration()
    route = app.router.get_route("/unhandled", "GET")
    assert route is not None

    request = SimpleNamespace(path="/unhandled")
    response = SimpleNamespace(finished=False, status_code=200)
    with pytest.raises(ValueError, match="partial response"):
        asyncio.run(route.function(request, response))


@pytest.mark.skip(reason="Legacy request hooks were removed")
def test_router_before_short_circuit_unwinds_only_entered_scopes():
    events: list[str] = []
    app = Hypern()
    router = Router()

    @app.after_request
    def app_after(req, res, ctx):
        events.append("app-after")

    @router.before_with_context
    def router_before(req, res, ctx):
        events.append("router-before")
        res.finished = True

    @router.after_with_context
    def router_after(req, res, ctx):
        events.append("router-after")

    @router.get("/blocked")
    def handler(req, res, ctx):
        events.append("handler")

    app.mount(router)
    route = app.router.get_route("/blocked", "GET")
    assert route is not None

    asyncio.run(route.function(SimpleNamespace(path="/blocked"), SimpleNamespace(finished=False)))

    assert events == ["router-before", "router-after", "app-after"]


def test_middleware_receives_context_and_awaitable_next():
    contexts: list[object] = []
    events: list[str] = []
    app = Hypern()

    async def middleware(req, res, ctx, next_fn):
        contexts.append(ctx)
        next_result = next_fn()
        assert inspect.isawaitable(next_result)
        events.append("before-next")
        await next_result
        events.append("after-next")

    app.use(middleware)

    @app.get("/ctx")
    def handler(req, res, ctx):
        contexts.append(ctx)
        events.append("handler")
        res.finished = True

    app._freeze_registration()
    route = app.router.get_route("/ctx", "GET")
    assert route is not None
    asyncio.run(route.function(SimpleNamespace(path="/ctx"), SimpleNamespace(finished=False)))

    assert events == ["before-next", "handler", "after-next"]
    assert len(contexts) == 2
    assert contexts[0] is contexts[1]


def test_middleware_omitting_next_does_not_enter_downstream_scope():
    events: list[str] = []
    app = Hypern()

    async def middleware(req, res, ctx, next_fn):
        events.append("middleware")

    app.use(middleware)

    @app.get("/omitted")
    def handler(req, res, ctx):
        events.append("handler")
        res.finished = True

    app._freeze_registration()
    route = app.router.get_route("/omitted", "GET")
    assert route is not None
    asyncio.run(route.function(SimpleNamespace(path="/omitted"), SimpleNamespace(finished=False)))

    assert events == ["middleware"]


def test_middleware_double_next_raises_after_first_downstream_entry():
    events: list[str] = []
    app = Hypern()

    async def middleware(req, res, ctx, next_fn):
        await next_fn()
        events.append("after-first-next")
        await next_fn()

    app.use(middleware)

    @app.get("/double-next")
    def handler(req, res, ctx):
        events.append("handler")
        res.finished = True

    app._freeze_registration()
    route = app.router.get_route("/double-next", "GET")
    assert route is not None
    with pytest.raises(RuntimeError, match="may only be awaited once"):
        asyncio.run(route.function(SimpleNamespace(path="/double-next"), SimpleNamespace(finished=False)))

    assert events == ["handler", "after-first-next"]


def test_middleware_decorator_rejects_an_invalid_signature():
    with pytest.raises(TypeError, match=r"\(req, res, ctx, next\)"):

        @middleware
        async def invalid(req, res, next_fn):
            await next_fn()


def test_middleware_decorator_returns_a_neutral_descriptor():
    @middleware
    async def handler(req, res, ctx, next_fn):
        await next_fn()

    assert isinstance(handler, Middleware)


def test_app_use_rejects_an_invalid_python_middleware_signature():
    app = Hypern()

    async def invalid(req, res, next_fn):
        await next_fn()

    with pytest.raises(TypeError, match=r"\(req, res, ctx, next\)"):
        app.use(invalid)


def test_mount_supports_router_prefix_and_explicit_prefix_forms():
    app = Hypern()
    prefixed_router = Router(prefix="/v1")
    explicit_router = Router()

    @prefixed_router.get("/items")
    def prefixed_handler(req, res, ctx):
        res.finished = True

    @explicit_router.get("/items")
    def explicit_handler(req, res, ctx):
        res.finished = True

    app.mount(prefixed_router)
    app.mount("/api", explicit_router)

    assert app.router.get_route("/v1/items", "GET") is not None
    assert app.router.get_route("/api/items", "GET") is not None
