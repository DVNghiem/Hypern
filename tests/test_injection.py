import asyncio
import inspect
import threading
import time
import typing

import msgspec
import pytest

import hypern.injection as injection
from hypern.injection import (
    Body,
    DependencyCycleError,
    HandlerPlan,
    Header,
    Inject,
    InjectionConfigurationError,
    Json,
    Path,
    ProviderRegistry,
    Query,
    RequestScope,
    compile_handler,
)


class Database:
    pass


class Service:
    def __init__(self, database: Database) -> None:
        self.database = database


class CycleA:
    def __init__(self, dependency: "CycleB") -> None:
        self.dependency = dependency


class CycleB:
    def __init__(self, dependency: CycleA) -> None:
        self.dependency = dependency


class InjectedService:
    def __init__(self, value: str = Inject("configured-value")) -> None:
        self.value = value


class NeedsMissingProvider:
    def __init__(self, dependency: int) -> None:
        self.dependency = dependency


class _Request:
    def __init__(
        self,
        *,
        body: bytes = b"",
        query_params: dict[str, str] | None = None,
        path_params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._body = body
        self.query_params = query_params or {}
        self._path_params = path_params or {}
        self._headers = headers or {}

    def body_bytes(self) -> bytes:
        return self._body

    def param(self, name: str) -> str | None:
        return self._path_params.get(name)

    def header(self, name: str) -> str | None:
        return self._headers.get(name)


class _Payload(msgspec.Struct):
    name: str
    quantity: int


class _Search(msgspec.Struct):
    page: int = 1
    active: bool = False


def test_inject_has_optional_explicit_key() -> None:
    assert Inject("service").key == "service"
    assert Inject().key is None


def test_markers_store_binding_options() -> None:
    assert Json() == Json()
    assert Query().name is None
    assert Query("term").name == "term"
    assert Header("X-Request-ID").name == "X-Request-ID"
    assert Path().name is None
    assert Path("item_id").name == "item_id"
    assert Body() == Body()


def test_markers_are_immutable() -> None:
    marker = Query("term")
    with pytest.raises(AttributeError):
        marker.name = "other"  # type: ignore[misc]


def test_provide_rejects_unknown_scope() -> None:
    registry = ProviderRegistry()
    with pytest.raises(InjectionConfigurationError, match="scope"):
        registry.provide("service", object, scope="global")  # type: ignore[arg-type]


def test_freeze_rejects_later_registration() -> None:
    registry = ProviderRegistry()
    registry.freeze()
    with pytest.raises(InjectionConfigurationError, match="frozen"):
        registry.provide("service", object)


def test_dependency_cycle_error_is_configuration_error() -> None:
    assert issubclass(DependencyCycleError, InjectionConfigurationError)


def test_request_provider_is_created_once_per_scope() -> None:
    calls = 0

    def factory() -> object:
        nonlocal calls
        calls += 1
        return object()

    registry = ProviderRegistry()
    registry.provide("value", factory, scope="request")
    registry.freeze()
    scope = RequestScope(registry)

    value = asyncio.run(scope.resolve("value"))

    assert value is asyncio.run(scope.resolve("value"))
    assert value is not asyncio.run(RequestScope(registry).resolve("value"))
    assert calls == 2


def test_async_request_provider_is_created_once_for_concurrent_resolves() -> None:
    calls = 0

    async def factory() -> object:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return object()

    async def resolve_twice(scope: RequestScope) -> tuple[object, object]:
        first, second = await asyncio.gather(
            scope.resolve("value"),
            scope.resolve("value"),
        )
        return first, second

    registry = ProviderRegistry()
    registry.provide("value", factory, scope="request")
    registry.freeze()

    first, second = asyncio.run(resolve_twice(RequestScope(registry)))

    assert first is second
    assert calls == 1


def test_loop_affine_async_singleton_is_rejected_during_freeze() -> None:
    calls = 0

    class LoopAffineValue:
        def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
            self.loop = loop

    async def factory() -> LoopAffineValue:
        nonlocal calls
        calls += 1
        return LoopAffineValue(asyncio.get_running_loop())

    registry = ProviderRegistry()
    registry.provide("value", factory, scope="singleton")

    with pytest.raises(InjectionConfigurationError, match="async singleton"):
        registry.freeze()
    assert calls == 0


async def _cancelled_waiter_keeps_completed_provider_value(scope_name: str) -> int:
    calls = 0
    provider_started = asyncio.Event()
    allow_completion = asyncio.Event()
    created_value = object()

    async def factory() -> object:
        nonlocal calls
        calls += 1
        provider_started.set()
        await allow_completion.wait()
        return created_value

    registry = ProviderRegistry()
    registry.provide("value", factory, scope=scope_name)
    registry.freeze()
    scope = RequestScope(registry)
    waiting_resolve = asyncio.create_task(scope.resolve("value"))

    await provider_started.wait()
    values = registry._singleton_values if scope_name == "singleton" else scope._values
    in_flight = values[0]
    in_flight.future.add_done_callback(lambda _: waiting_resolve.cancel())
    allow_completion.set()

    with pytest.raises(asyncio.CancelledError):
        await waiting_resolve
    await asyncio.wrap_future(in_flight.future)

    assert await scope.resolve("value") is created_value
    return calls


def test_cancelled_request_waiter_keeps_completed_provider_value() -> None:
    assert asyncio.run(_cancelled_waiter_keeps_completed_provider_value("request")) == 1


def test_provider_cycle_fails_during_freeze() -> None:
    registry = ProviderRegistry()
    registry.provide(CycleA, CycleA)
    registry.provide(CycleB, CycleB)

    with pytest.raises(DependencyCycleError):
        registry.freeze()


def test_value_provider_resolves_without_construction() -> None:
    value = {"configured": True}
    registry = ProviderRegistry()
    registry.provide("value", value)
    registry.freeze()

    assert asyncio.run(RequestScope(registry).resolve("value")) is value


def test_singleton_provider_is_shared_across_scopes() -> None:
    registry = ProviderRegistry()
    registry.provide("value", object, scope="singleton")
    registry.freeze()

    assert asyncio.run(RequestScope(registry).resolve("value")) is asyncio.run(RequestScope(registry).resolve("value"))


def test_transient_provider_is_created_for_every_resolution() -> None:
    registry = ProviderRegistry()
    registry.provide("value", object, scope="transient")
    registry.freeze()
    scope = RequestScope(registry)

    assert asyncio.run(scope.resolve("value")) is not asyncio.run(scope.resolve("value"))


def test_async_factory_provider_is_awaited() -> None:
    calls = 0

    async def factory() -> str:
        nonlocal calls
        calls += 1
        return "ready"

    registry = ProviderRegistry()
    registry.provide("value", factory, scope="request")
    registry.freeze()

    assert asyncio.run(RequestScope(registry).resolve("value")) == "ready"
    assert calls == 1


def test_sync_provider_resolves_without_a_running_event_loop() -> None:
    registry = ProviderRegistry()
    registry.provide("value", "ready", scope="request")
    registry.freeze()
    resolution = RequestScope(registry).resolve("value")

    with pytest.raises(StopIteration) as completed:
        resolution.send(None)

    assert completed.value.value == "ready"


def test_async_provider_resolves_without_a_running_event_loop() -> None:
    async def factory() -> str:
        return "ready"

    registry = ProviderRegistry()
    registry.provide("value", factory, scope="request")
    registry.freeze()
    resolution = RequestScope(registry).resolve("value")

    with pytest.raises(StopIteration) as completed:
        resolution.send(None)

    assert completed.value.value == "ready"


def test_singleton_with_async_dependency_is_rejected_during_freeze() -> None:
    async def dependency() -> object:
        return object()

    def factory(value: object = Inject("dependency")) -> object:
        return value

    registry = ProviderRegistry()
    registry.provide("dependency", dependency, scope="request")
    registry.provide("value", factory, scope="singleton")

    with pytest.raises(InjectionConfigurationError, match="async singleton"):
        registry.freeze()


def test_sync_singleton_is_created_once_across_threads() -> None:
    calls = 0
    calls_lock = threading.Lock()
    start = threading.Barrier(2)

    def factory() -> object:
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.01)
        return object()

    registry = ProviderRegistry()
    registry.provide("value", factory, scope="singleton")
    registry.freeze()
    results: list[object] = []

    def resolve() -> None:
        start.wait()
        results.append(asyncio.run(RequestScope(registry).resolve("value")))

    threads = [threading.Thread(target=resolve) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 2
    assert results[0] is results[1]
    assert calls == 1


def test_constructor_dependencies_are_resolved_from_annotations() -> None:
    registry = ProviderRegistry()
    registry.provide(Database, Database)
    registry.provide(Service, Service)
    registry.freeze()

    service = asyncio.run(RequestScope(registry).resolve(Service))

    assert isinstance(service, Service)
    assert isinstance(service.database, Database)


def test_inject_marker_overrides_the_annotation_key() -> None:
    registry = ProviderRegistry()
    registry.provide("configured-value", "injected")
    registry.provide(InjectedService, InjectedService)
    registry.freeze()

    service = asyncio.run(RequestScope(registry).resolve(InjectedService))

    assert service.value == "injected"


def test_missing_dependency_provider_fails_during_freeze() -> None:
    registry = ProviderRegistry()
    registry.provide(NeedsMissingProvider, NeedsMissingProvider)

    with pytest.raises(InjectionConfigurationError, match="no provider"):
        registry.freeze()


def test_resolving_an_unknown_key_fails() -> None:
    registry = ProviderRegistry()
    registry.freeze()

    with pytest.raises(InjectionConfigurationError, match="no provider"):
        asyncio.run(RequestScope(registry).resolve("missing"))


def test_handler_plan_binds_markers_and_dependency() -> None:
    service = Service(Database())
    registry = ProviderRegistry()
    registry.provide(Service, service)
    registry.freeze()
    request = _Request(
        path_params={"user_id": "7"},
        headers={"X-Token": "abc"},
    )

    async def handler(
        req: object,
        res: object,
        ctx: object,
        user_id: int = Path(),
        token: str = Header("X-Token"),
        injected_service: Service = Inject(),
    ) -> tuple[object, ...]:
        return req, res, ctx, user_id, token, injected_service

    plan = compile_handler(
        handler,
        path_parameter_names=frozenset({"user_id"}),
        registry=registry,
    )

    result = asyncio.run(plan.invoke(request, "response", "context", RequestScope(registry)))

    assert result == (request, "response", "context", 7, "abc", service)


def test_sync_handler_plan_invokes_without_creating_an_awaitable() -> None:
    registry = ProviderRegistry()
    registry.provide(Database, Database, scope="request")
    registry.provide(Service, Service, scope="request")
    registry.freeze()

    def handler(service: Service = Inject()) -> Database:
        return service.database

    plan = compile_handler(handler, path_parameter_names=frozenset(), registry=registry)
    result = plan.invoke_sync(_Request(), object(), object(), RequestScope(registry))

    assert plan.requires_async is False
    assert isinstance(result, Database)
    assert inspect.isawaitable(result) is False


def test_async_provider_keeps_handler_plan_on_async_invocation_path() -> None:
    registry = ProviderRegistry()

    async def create_database() -> Database:
        await asyncio.sleep(0)
        return Database()

    registry.provide(Database, create_database, scope="request")
    registry.freeze()

    def handler(database: Database = Inject()) -> Database:
        return database

    plan = compile_handler(handler, path_parameter_names=frozenset(), registry=registry)

    assert plan.requires_async is True
    with pytest.raises(RuntimeError, match="asynchronous handler plan"):
        plan.invoke_sync(_Request(), object(), object(), RequestScope(registry))
    assert isinstance(
        asyncio.run(plan.invoke(_Request(), object(), object(), RequestScope(registry))),
        Database,
    )


def test_json_requires_annotation() -> None:
    registry = ProviderRegistry()
    registry.freeze()

    async def handler(payload=Json()):
        return payload

    with pytest.raises(InjectionConfigurationError, match="Json"):
        compile_handler(handler, path_parameter_names=frozenset(), registry=registry)


def test_handler_plan_binds_json_query_body_and_keyword_only_header() -> None:
    registry = ProviderRegistry()
    registry.freeze()
    request = _Request(
        body=b'{"name":"widget","quantity":3}',
        query_params={"page": "2", "active": "true"},
        headers={"X-Mode": "fast"},
    )

    def handler(
        req: object,
        res: object,
        ctx: object,
        payload: _Payload = Json(),
        query: _Search = Query(),
        body: bytes = Body(),
        *,
        mode: str = Header("X-Mode"),
    ) -> tuple[object, ...]:
        return req, res, ctx, payload, query, body, mode

    plan = compile_handler(handler, path_parameter_names=frozenset(), registry=registry)

    result = asyncio.run(plan.invoke(request, "response", "context", RequestScope(registry)))

    assert result == (
        request,
        "response",
        "context",
        _Payload("widget", 3),
        _Search(2, True),
        b'{"name":"widget","quantity":3}',
        "fast",
    )


def test_handler_plan_rejects_invalid_json() -> None:
    registry = ProviderRegistry()
    registry.freeze()

    def handler(payload: _Payload = Json()) -> _Payload:
        return payload

    plan = compile_handler(handler, path_parameter_names=frozenset(), registry=registry)

    with pytest.raises(msgspec.DecodeError):
        asyncio.run(
            plan.invoke(
                _Request(body=b"not-json"),
                object(),
                object(),
                RequestScope(registry),
            )
        )


def test_handler_plan_coerces_scalar_query_and_optional_header() -> None:
    registry = ProviderRegistry()
    registry.freeze()
    request = _Request(query_params={"limit": "12"})

    def handler(
        limit: int = Query(),
        request_id: str | None = Header("X-Request-ID"),
    ) -> tuple[int, str | None]:
        return limit, request_id

    plan = compile_handler(handler, path_parameter_names=frozenset(), registry=registry)

    assert asyncio.run(plan.invoke(request, object(), object(), RequestScope(registry))) == (12, None)


def test_handler_plan_rejects_missing_required_header_and_path_value() -> None:
    registry = ProviderRegistry()
    registry.freeze()

    def handler(token: str = Header("X-Token"), item_id: int = Path()) -> tuple[str, int]:
        return token, item_id

    plan = compile_handler(
        handler,
        path_parameter_names=frozenset({"item_id"}),
        registry=registry,
    )

    with pytest.raises(msgspec.ValidationError, match="header"):
        asyncio.run(plan.invoke(_Request(), object(), object(), RequestScope(registry)))

    with pytest.raises(msgspec.ValidationError, match="path"):
        asyncio.run(
            plan.invoke(
                _Request(headers={"X-Token": "abc"}),
                object(),
                object(),
                RequestScope(registry),
            )
        )


def test_handler_plan_rejects_unknown_parameter_source() -> None:
    registry = ProviderRegistry()
    registry.freeze()

    def handler(value: str = "default") -> str:
        return value

    with pytest.raises(InjectionConfigurationError, match="unsupported"):
        compile_handler(handler, path_parameter_names=frozenset(), registry=registry)


def test_handler_plan_rejects_annotated_inject_with_a_default_marker() -> None:
    registry = ProviderRegistry()
    registry.provide(Service, Service(Database()))
    registry.freeze()

    def handler(value: typing.Annotated[Service, Inject()] = Json()) -> Service:
        return value

    with pytest.raises(InjectionConfigurationError, match="conflicting"):
        compile_handler(handler, path_parameter_names=frozenset(), registry=registry)


def test_body_rejects_a_non_bytes_annotation() -> None:
    registry = ProviderRegistry()
    registry.freeze()

    def handler(body: str = Body()) -> str:
        return body

    with pytest.raises(InjectionConfigurationError, match="Body"):
        compile_handler(handler, path_parameter_names=frozenset(), registry=registry)


def test_handler_plan_does_not_create_unused_providers() -> None:
    calls = 0

    def unused_provider() -> object:
        nonlocal calls
        calls += 1
        return object()

    registry = ProviderRegistry()
    registry.provide("unused", unused_provider)
    registry.freeze()

    def handler(token: str = Header("X-Token")) -> str:
        return token

    plan = compile_handler(handler, path_parameter_names=frozenset(), registry=registry)

    assert asyncio.run(
        plan.invoke(
            _Request(headers={"X-Token": "abc"}),
            object(),
            object(),
            RequestScope(registry),
        )
    ) == "abc"
    assert calls == 0


def test_reordered_marker_parameters_bind_the_same_values() -> None:
    service = Service(Database())
    registry = ProviderRegistry()
    registry.provide(Service, service)
    registry.freeze()
    request = _Request(
        body=b'{"name":"widget","quantity":3}',
        path_params={"user_id": "7"},
        headers={"X-Token": "abc"},
    )

    async def path_first(
        req: object,
        res: object,
        ctx: object,
        user_id: int = Path(),
        payload: _Payload = Json(),
        token: str = Header("X-Token"),
        injected_service: Service = Inject(),
    ) -> tuple[int, _Payload, str, Service]:
        return user_id, payload, token, injected_service

    async def service_first(
        req: object,
        res: object,
        ctx: object,
        injected_service: Service = Inject(),
        token: str = Header("X-Token"),
        payload: _Payload = Json(),
        user_id: int = Path(),
    ) -> tuple[int, _Payload, str, Service]:
        return user_id, payload, token, injected_service

    path_first_plan = compile_handler(
        path_first,
        path_parameter_names=frozenset({"user_id"}),
        registry=registry,
    )
    service_first_plan = compile_handler(
        service_first,
        path_parameter_names=frozenset({"user_id"}),
        registry=registry,
    )

    assert asyncio.run(
        path_first_plan.invoke(request, object(), object(), RequestScope(registry))
    ) == asyncio.run(
        service_first_plan.invoke(request, object(), object(), RequestScope(registry))
    )


def test_invocation_does_not_use_reflection(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = ProviderRegistry()
    registry.freeze()
    request = _Request(headers={"X-Token": "abc"})

    async def handler(token: str = Header("X-Token")) -> str:
        return token

    plan: HandlerPlan = compile_handler(
        handler,
        path_parameter_names=frozenset(),
        registry=registry,
    )
    monkeypatch.setattr(inspect, "signature", pytest.fail)
    monkeypatch.setattr(typing, "get_type_hints", pytest.fail)
    monkeypatch.setattr(injection, "get_type_hints", pytest.fail)

    assert asyncio.run(plan.invoke(request, object(), object(), RequestScope(registry))) == "abc"


def test_optional_header_binding_does_not_reflect_during_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ProviderRegistry()
    registry.freeze()

    def handler(request_id: str | None = Header("X-Request-ID")) -> str | None:
        return request_id

    plan = compile_handler(handler, path_parameter_names=frozenset(), registry=registry)
    monkeypatch.setattr(injection, "get_args", pytest.fail)

    assert asyncio.run(plan.invoke(_Request(), object(), object(), RequestScope(registry))) is None
