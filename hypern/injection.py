from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import Future as ConcurrentFuture
from dataclasses import dataclass, replace
from functools import partial
from typing import Annotated, Literal, TypeAlias, cast, get_args, get_origin, get_type_hints

import msgspec

from hypern.validation import ValidationError, _convert_value, _decode_json

Scope: TypeAlias = Literal["singleton", "request", "transient"]


class InjectionConfigurationError(Exception):
    """Raised when dependency-injection configuration is invalid."""


class DependencyCycleError(InjectionConfigurationError):
    """Raised when provider dependencies contain a cycle."""


@dataclass(frozen=True, slots=True)
class Inject:
    key: object | None = None


@dataclass(frozen=True, slots=True)
class Json:
    pass


@dataclass(frozen=True, slots=True)
class Query:
    name: str | None = None


@dataclass(frozen=True, slots=True)
class Header:
    name: str


@dataclass(frozen=True, slots=True)
class Path:
    name: str | None = None


@dataclass(frozen=True, slots=True)
class Body:
    pass


_UNSET = object()
_HandlerResolver: TypeAlias = Callable[[object, object, object, "RequestScope"], object]


@dataclass(frozen=True, slots=True)
class _ProviderPlan:
    provider: object
    scope: Scope
    dependency_slots: tuple[int, ...]
    keyword_names: tuple[str | None, ...]
    is_value: bool
    is_async: bool
    requires_async: bool


@dataclass(frozen=True, slots=True)
class _InFlightProvider:
    future: ConcurrentFuture[object]


class ProviderRegistry:
    """Registry for providers while application configuration is mutable."""

    def __init__(self) -> None:
        self._providers: dict[object, tuple[object, Scope]] = {}
        self._slots: dict[object, int] = {}
        self._plans: tuple[_ProviderPlan, ...] = ()
        self._singleton_values: list[object] = []
        self._singleton_locks: tuple[threading.Lock, ...] = ()
        self._frozen = False

    def provide(
        self,
        key: object,
        provider: object,
        *,
        scope: Scope = "singleton",
    ) -> None:
        if self._frozen:
            raise InjectionConfigurationError("provider registry is frozen")
        if scope not in {"singleton", "request", "transient"}:
            raise InjectionConfigurationError(f"unsupported provider scope: {scope}")
        self._providers[key] = (provider, scope)

    def freeze(self) -> None:
        if self._frozen:
            return

        slots = {key: index for index, key in enumerate(self._providers)}
        plans = tuple(
            self._compile_provider(key, provider, scope, slots)
            for key, (provider, scope) in self._providers.items()
        )
        self._validate_acyclic(plans)
        plans = self._compile_async_requirements(plans)
        self._validate_async_singletons(plans)

        self._slots = slots
        self._plans = plans
        self._singleton_values = [_UNSET] * len(plans)
        self._singleton_locks = tuple(threading.Lock() for _ in plans)
        self._frozen = True

    def _validate_async_singletons(self, plans: tuple[_ProviderPlan, ...]) -> None:
        for key, plan in zip(self._providers, plans):
            if plan.scope == "singleton" and plan.requires_async:
                raise InjectionConfigurationError(
                    f"async singleton provider {key!r} is unsafe across worker event loops; "
                    "use request or transient scope"
                )

    def _compile_provider(
        self,
        key: object,
        provider: object,
        scope: Scope,
        slots: dict[object, int],
    ) -> _ProviderPlan:
        if not callable(provider):
            return _ProviderPlan(provider, scope, (), (), True, False, False)

        target = provider.__init__ if inspect.isclass(provider) else provider
        try:
            signature = inspect.signature(provider)
            hints = get_type_hints(target, include_extras=True)
        except (TypeError, ValueError, NameError) as error:
            raise InjectionConfigurationError(
                f"unable to inspect provider for {key!r}"
            ) from error

        dependency_slots: list[int] = []
        keyword_names: list[str | None] = []
        for parameter in signature.parameters.values():
            if parameter.kind in {
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            }:
                continue

            dependency_key = self._dependency_key(key, parameter, hints)
            if dependency_key is _UNSET:
                continue
            try:
                dependency_slots.append(slots[dependency_key])
            except KeyError as error:
                raise InjectionConfigurationError(
                    f"no provider for dependency {dependency_key!r} of {key!r}"
                ) from error
            keyword_names.append(
                parameter.name
                if parameter.kind is inspect.Parameter.KEYWORD_ONLY
                else None
            )

        return _ProviderPlan(
            provider,
            scope,
            tuple(dependency_slots),
            tuple(keyword_names),
            False,
            inspect.iscoroutinefunction(provider),
            False,
        )

    def _dependency_key(
        self,
        provider_key: object,
        parameter: inspect.Parameter,
        hints: dict[str, object],
    ) -> object:
        annotation = hints.get(parameter.name, parameter.annotation)
        marker = parameter.default if isinstance(parameter.default, Inject) else None
        if marker is not None and marker.key is not None:
            return marker.key

        annotation, annotated_marker = self._unwrap_inject_annotation(annotation)
        if annotated_marker is not None and annotated_marker.key is not None:
            return annotated_marker.key
        if marker is not None or annotated_marker is not None:
            if annotation is inspect.Parameter.empty:
                raise InjectionConfigurationError(
                    f"dependency {parameter.name!r} of {provider_key!r} has no key"
                )
            return annotation
        if annotation is not inspect.Parameter.empty:
            return annotation
        if parameter.default is inspect.Parameter.empty:
            raise InjectionConfigurationError(
                f"dependency {parameter.name!r} of {provider_key!r} has no type annotation"
            )
        return _UNSET

    @staticmethod
    def _unwrap_inject_annotation(annotation: object) -> tuple[object, Inject | None]:
        annotation, marker = ProviderRegistry._unwrap_source_annotation(annotation)
        return annotation, marker if isinstance(marker, Inject) else None

    @staticmethod
    def _unwrap_source_annotation(
        annotation: object,
    ) -> tuple[object, Inject | Json | Query | Header | Path | Body | None]:
        if get_origin(annotation) is not Annotated:
            return annotation, None
        annotated_type, *metadata = get_args(annotation)
        marker = next(
            (
                item
                for item in metadata
                if isinstance(item, (Inject, Json, Query, Header, Path, Body))
            ),
            None,
        )
        return annotated_type, marker

    @staticmethod
    def _validate_acyclic(plans: tuple[_ProviderPlan, ...]) -> None:
        visiting: set[int] = set()
        visited: set[int] = set()

        def visit(slot: int) -> None:
            if slot in visiting:
                raise DependencyCycleError("provider dependency cycle detected")
            if slot in visited:
                return
            visiting.add(slot)
            for dependency_slot in plans[slot].dependency_slots:
                visit(dependency_slot)
            visiting.remove(slot)
            visited.add(slot)

        for slot in range(len(plans)):
            visit(slot)

    @staticmethod
    def _compile_async_requirements(
        plans: tuple[_ProviderPlan, ...],
    ) -> tuple[_ProviderPlan, ...]:
        requirements: dict[int, bool] = {}

        def requires_async(slot: int) -> bool:
            if slot not in requirements:
                plan = plans[slot]
                requirements[slot] = plan.is_async or any(
                    requires_async(dependency_slot)
                    for dependency_slot in plan.dependency_slots
                )
            return requirements[slot]

        return tuple(
            replace(plan, requires_async=requires_async(slot))
            for slot, plan in enumerate(plans)
        )


class RequestScope:
    """Resolves compiled providers and caches request-scoped values."""

    def __init__(self, registry: ProviderRegistry) -> None:
        if not registry._frozen:
            raise InjectionConfigurationError("provider registry must be frozen")
        self._registry = registry
        self._values: list[object] = [_UNSET] * len(registry._plans)
        self._locks = tuple(threading.Lock() for _ in registry._plans)

    async def resolve(self, key: object) -> object:
        try:
            slot = self._registry._slots[key]
        except KeyError as error:
            raise InjectionConfigurationError(f"no provider for {key!r}") from error
        return await self._resolve_slot(slot)

    async def _resolve_slot(self, slot: int) -> object:
        plan = self._registry._plans[slot]
        if plan.scope == "singleton":
            values = self._registry._singleton_values
            lock = self._registry._singleton_locks[slot]
        elif plan.scope == "request":
            values = self._values
            lock = self._locks[slot]
        else:
            return await self._create(plan)

        with lock:
            value = values[slot]
            if value is _UNSET:
                in_flight = _InFlightProvider(ConcurrentFuture())
                values[slot] = in_flight
                creates_value = True
            elif isinstance(value, _InFlightProvider):
                in_flight = value
                creates_value = False
            else:
                return value

        if not creates_value:
            return await self._wait_for_provider(in_flight.future)

        if plan.requires_async and self._running_loop() is not None:
            creation_task = asyncio.create_task(
                self._create_and_publish(plan, values, slot, in_flight, lock)
            )
            await asyncio.shield(creation_task)
            return in_flight.future.result()

        try:
            value = await self._create(plan)
        except BaseException as error:
            self._publish_provider_error(values, slot, in_flight, lock, error)
            raise
        self._publish_provider_value(values, slot, in_flight, lock, value)
        return value

    def _resolve_slot_sync(self, slot: int) -> object:
        plan = self._registry._plans[slot]
        if plan.requires_async:
            raise RuntimeError("asynchronous provider cannot be resolved synchronously")
        if plan.scope == "singleton":
            values = self._registry._singleton_values
            lock = self._registry._singleton_locks[slot]
        elif plan.scope == "request":
            values = self._values
            lock = self._locks[slot]
        else:
            return self._create_sync(plan)

        with lock:
            value = values[slot]
            if value is _UNSET:
                in_flight = _InFlightProvider(ConcurrentFuture())
                values[slot] = in_flight
                creates_value = True
            elif isinstance(value, _InFlightProvider):
                in_flight = value
                creates_value = False
            else:
                return value

        if not creates_value:
            return in_flight.future.result()

        try:
            value = self._create_sync(plan)
        except BaseException as error:
            self._publish_provider_error(values, slot, in_flight, lock, error)
            raise
        self._publish_provider_value(values, slot, in_flight, lock, value)
        return value

    async def _create_and_publish(
        self,
        plan: _ProviderPlan,
        values: list[object],
        slot: int,
        in_flight: _InFlightProvider,
        lock: threading.Lock,
    ) -> None:
        try:
            value = await self._create(plan)
        except BaseException as error:
            self._publish_provider_error(values, slot, in_flight, lock, error)
            raise
        self._publish_provider_value(values, slot, in_flight, lock, value)

    @staticmethod
    def _publish_provider_value(
        values: list[object],
        slot: int,
        in_flight: _InFlightProvider,
        lock: threading.Lock,
        value: object,
    ) -> None:
        with lock:
            if values[slot] is in_flight:
                values[slot] = value
        in_flight.future.set_result(value)

    @staticmethod
    def _publish_provider_error(
        values: list[object],
        slot: int,
        in_flight: _InFlightProvider,
        lock: threading.Lock,
        error: BaseException,
    ) -> None:
        with lock:
            if values[slot] is in_flight:
                values[slot] = _UNSET
        in_flight.future.set_exception(error)

    @staticmethod
    async def _wait_for_provider(future: ConcurrentFuture[object]) -> object:
        loop = RequestScope._running_loop()
        if loop is None:
            return future.result()
        return await asyncio.shield(asyncio.wrap_future(future, loop=loop))

    @staticmethod
    def _running_loop() -> asyncio.AbstractEventLoop | None:
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return None

    async def _create(self, plan: _ProviderPlan) -> object:
        if plan.is_value:
            return plan.provider

        arguments: list[object] = []
        keyword_arguments: dict[str, object] = {}
        for slot, keyword_name in zip(plan.dependency_slots, plan.keyword_names):
            dependency = await self._resolve_slot(slot)
            if keyword_name is None:
                arguments.append(dependency)
            else:
                keyword_arguments[keyword_name] = dependency

        creator = cast(Callable[..., object], plan.provider)
        value = creator(*arguments, **keyword_arguments)
        if plan.is_async:
            return await value
        return value

    def _create_sync(self, plan: _ProviderPlan) -> object:
        if plan.is_value:
            return plan.provider

        arguments: list[object] = []
        keyword_arguments: dict[str, object] = {}
        for slot, keyword_name in zip(plan.dependency_slots, plan.keyword_names):
            dependency = self._resolve_slot_sync(slot)
            if keyword_name is None:
                arguments.append(dependency)
            else:
                keyword_arguments[keyword_name] = dependency

        creator = cast(Callable[..., object], plan.provider)
        return creator(*arguments, **keyword_arguments)


@dataclass(frozen=True, slots=True)
class _HandlerParameter:
    resolver: _HandlerResolver
    keyword_name: str | None
    is_async: bool


@dataclass(frozen=True, slots=True)
class HandlerPlan:
    """Invokes one handler with request values resolved from compiled bindings."""

    handler: Callable[..., object]
    positional_parameters: tuple[_HandlerParameter, ...]
    keyword_parameters: tuple[_HandlerParameter, ...]
    is_async: bool
    requires_async: bool

    async def invoke(
        self,
        req: object,
        res: object,
        ctx: object,
        scope: RequestScope,
    ) -> object:
        arguments = []
        for parameter in self.positional_parameters:
            value = parameter.resolver(req, res, ctx, scope)
            if parameter.is_async:
                value = await cast(Awaitable[object], value)
            arguments.append(value)
        if self.keyword_parameters:
            keyword_arguments = {}
            for parameter in self.keyword_parameters:
                value = parameter.resolver(req, res, ctx, scope)
                if parameter.is_async:
                    value = await cast(Awaitable[object], value)
                keyword_arguments[cast(str, parameter.keyword_name)] = value
            result = self.handler(*arguments, **keyword_arguments)
        else:
            result = self.handler(*arguments)
        if self.is_async:
            return await result
        return result

    def invoke_sync(
        self,
        req: object,
        res: object,
        ctx: object,
        scope: RequestScope,
    ) -> object:
        """Invoke a plan whose handler and provider graph are fully synchronous."""
        if self.requires_async:
            raise RuntimeError("asynchronous handler plan cannot be invoked synchronously")
        arguments = [
            parameter.resolver(req, res, ctx, scope)
            for parameter in self.positional_parameters
        ]
        if self.keyword_parameters:
            keyword_arguments = {
                cast(str, parameter.keyword_name): parameter.resolver(req, res, ctx, scope)
                for parameter in self.keyword_parameters
            }
            return self.handler(*arguments, **keyword_arguments)
        return self.handler(*arguments)


def compile_handler(
    handler: Callable[..., object],
    *,
    path_parameter_names: frozenset[str],
    registry: ProviderRegistry,
) -> HandlerPlan:
    """Compile a functional handler into pre-bound request value resolvers."""
    if not inspect.isfunction(handler):
        raise InjectionConfigurationError("handlers must be functions")
    if not registry._frozen:
        raise InjectionConfigurationError("provider registry must be frozen")

    try:
        signature = inspect.signature(handler)
        hints = get_type_hints(handler, include_extras=True)
    except (TypeError, ValueError, NameError) as error:
        raise InjectionConfigurationError("unable to inspect handler") from error

    positional_parameters: list[_HandlerParameter] = []
    keyword_parameters: list[_HandlerParameter] = []
    for parameter in signature.parameters.values():
        compiled_parameter = _compile_handler_parameter(
            parameter,
            hints,
            path_parameter_names,
            registry,
        )
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY:
            keyword_parameters.append(compiled_parameter)
        else:
            positional_parameters.append(compiled_parameter)

    is_async = inspect.iscoroutinefunction(handler)
    return HandlerPlan(
        handler,
        tuple(positional_parameters),
        tuple(keyword_parameters),
        is_async,
        is_async or any(parameter.is_async for parameter in positional_parameters)
        or any(parameter.is_async for parameter in keyword_parameters),
    )


def _compile_handler_parameter(
    parameter: inspect.Parameter,
    hints: dict[str, object],
    path_parameter_names: frozenset[str],
    registry: ProviderRegistry,
) -> _HandlerParameter:
    if parameter.kind in {
        inspect.Parameter.VAR_POSITIONAL,
        inspect.Parameter.VAR_KEYWORD,
    }:
        raise InjectionConfigurationError("handlers cannot declare variadic parameters")

    annotation = hints.get(parameter.name, parameter.annotation)
    annotation, annotated_marker = ProviderRegistry._unwrap_source_annotation(annotation)
    default = parameter.default
    default_inject = default if isinstance(default, Inject) else None
    default_marker = (
        default
        if isinstance(default, (Inject, Json, Query, Header, Path, Body))
        else None
    )
    if annotated_marker is not None and default is not inspect.Parameter.empty:
        if default_inject is not None:
            raise InjectionConfigurationError(
                f"parameter {parameter.name!r} declares Inject twice"
            )
        raise InjectionConfigurationError(
            f"parameter {parameter.name!r} declares conflicting sources"
        )
    source_marker = default_marker or annotated_marker
    inject_marker = source_marker if isinstance(source_marker, Inject) else None

    if parameter.name in {"req", "res", "ctx"}:
        if default is not inspect.Parameter.empty or annotated_marker is not None:
            raise InjectionConfigurationError(
                f"reserved parameter {parameter.name!r} cannot declare a source marker"
            )
        resolver = _transport_resolver(parameter.name)
    elif inject_marker is not None:
        resolver = _inject_resolver(parameter, annotation, inject_marker, registry)
    elif isinstance(source_marker, Json):
        resolver = _json_resolver(parameter, annotation)
    elif isinstance(source_marker, Query):
        resolver = _query_resolver(parameter, annotation, source_marker)
    elif isinstance(source_marker, Header):
        resolver = _header_resolver(parameter, annotation, source_marker)
    elif isinstance(source_marker, Path):
        resolver = _path_resolver(parameter, annotation, source_marker, path_parameter_names)
    elif isinstance(source_marker, Body):
        resolver = _body_resolver(parameter, annotation)
    else:
        raise InjectionConfigurationError(
            f"unsupported source for handler parameter {parameter.name!r}"
        )

    return _HandlerParameter(
        resolver,
        parameter.name if parameter.kind is inspect.Parameter.KEYWORD_ONLY else None,
        inspect.iscoroutinefunction(resolver),
    )


def _transport_resolver(name: str) -> _HandlerResolver:
    def resolve(req: object, res: object, ctx: object, scope: RequestScope) -> object:
        if name == "req":
            return req
        if name == "res":
            return res
        return ctx

    return resolve


def _inject_resolver(
    parameter: inspect.Parameter,
    annotation: object,
    marker: Inject,
    registry: ProviderRegistry,
) -> _HandlerResolver:
    key = marker.key if marker.key is not None else annotation
    if key is inspect.Parameter.empty:
        raise InjectionConfigurationError(
            f"Inject parameter {parameter.name!r} has no provider key"
        )
    try:
        slot = registry._slots[key]
    except KeyError as error:
        raise InjectionConfigurationError(f"no provider for {key!r}") from error

    if registry._plans[slot].requires_async:
        async def resolve_async(
            req: object,
            res: object,
            ctx: object,
            scope: RequestScope,
        ) -> object:
            return await scope._resolve_slot(slot)

        return resolve_async

    def resolve(req: object, res: object, ctx: object, scope: RequestScope) -> object:
        return scope._resolve_slot_sync(slot)

    return resolve


def _json_resolver(parameter: inspect.Parameter, annotation: object) -> _HandlerResolver:
    _require_annotation(parameter, annotation, "Json")
    try:
        decoder = msgspec.json.Decoder(annotation)
    except (TypeError, ValueError) as error:
        raise InjectionConfigurationError(
            f"Json parameter {parameter.name!r} has an invalid annotation"
        ) from error

    def resolve(req: object, res: object, ctx: object, scope: RequestScope) -> object:
        return _decode_json(decoder, req.body_bytes())  # type: ignore[attr-defined]

    return resolve


def _query_resolver(
    parameter: inspect.Parameter,
    annotation: object,
    marker: Query,
) -> _HandlerResolver:
    _require_annotation(parameter, annotation, "Query")
    name = marker.name
    is_struct = inspect.isclass(annotation) and issubclass(annotation, msgspec.Struct)
    converter = partial(msgspec.convert, type=annotation, strict=False)
    allows_none = _allows_none(annotation)

    if name is None and is_struct:
        def resolve(req: object, res: object, ctx: object, scope: RequestScope) -> object:
            return _convert_value(converter, req.query_params)  # type: ignore[attr-defined]

        return resolve

    query_name = name or parameter.name

    def resolve(req: object, res: object, ctx: object, scope: RequestScope) -> object:
        value = req.query_params.get(query_name)  # type: ignore[attr-defined]
        if value is None:
            if allows_none:
                return None
            raise ValidationError(
                message=f"missing required query parameter {query_name!r}"
            )
        return _convert_value(converter, value)

    return resolve


def _header_resolver(
    parameter: inspect.Parameter,
    annotation: object,
    marker: Header,
) -> _HandlerResolver:
    _require_annotation(parameter, annotation, "Header")
    converter = partial(msgspec.convert, type=annotation, strict=False)
    allows_none = _allows_none(annotation)

    def resolve(req: object, res: object, ctx: object, scope: RequestScope) -> object:
        value = req.header(marker.name)  # type: ignore[attr-defined]
        if value is None:
            if allows_none:
                return None
            raise ValidationError(message=f"missing required header {marker.name!r}")
        return _convert_value(converter, value)

    return resolve


def _path_resolver(
    parameter: inspect.Parameter,
    annotation: object,
    marker: Path,
    path_parameter_names: frozenset[str],
) -> _HandlerResolver:
    _require_annotation(parameter, annotation, "Path")
    name = marker.name or parameter.name
    if name not in path_parameter_names:
        raise InjectionConfigurationError(f"Path parameter {name!r} is not declared by the route")
    converter = partial(msgspec.convert, type=annotation, strict=False)
    allows_none = _allows_none(annotation)

    def resolve(req: object, res: object, ctx: object, scope: RequestScope) -> object:
        value = req.param(name)  # type: ignore[attr-defined]
        if value is None:
            if allows_none:
                return None
            raise ValidationError(message=f"missing required path parameter {name!r}")
        return _convert_value(converter, value)

    return resolve


def _body_resolver(parameter: inspect.Parameter, annotation: object) -> _HandlerResolver:
    if annotation is not inspect.Parameter.empty and annotation is not bytes:
        raise InjectionConfigurationError(
            f"Body parameter {parameter.name!r} must be annotated as bytes"
        )

    def resolve(req: object, res: object, ctx: object, scope: RequestScope) -> object:
        return req.body_bytes()  # type: ignore[attr-defined]

    return resolve


def _require_annotation(
    parameter: inspect.Parameter,
    annotation: object,
    marker_name: str,
) -> None:
    if annotation is inspect.Parameter.empty:
        raise InjectionConfigurationError(
            f"{marker_name} parameter {parameter.name!r} requires a type annotation"
        )


def _allows_none(annotation: object) -> bool:
    return type(None) in get_args(annotation)


__all__ = [
    "Body",
    "DependencyCycleError",
    "HandlerPlan",
    "Header",
    "Inject",
    "InjectionConfigurationError",
    "Json",
    "Path",
    "ProviderRegistry",
    "Query",
    "RequestScope",
    "Scope",
    "compile_handler",
]
