"""Regression coverage for compiled injection invocation hot paths."""

import asyncio
import inspect
import statistics
import time
import typing
from collections.abc import Callable

import pytest

import hypern.injection as injection
from hypern.injection import Inject, ProviderRegistry, RequestScope, compile_handler


class _Request:
    pass


class _Service:
    pass


class _Repository:
    pass


class _NestedService:
    def __init__(self, repository: _Repository) -> None:
        self.repository = repository


async def _documented_handler(service: _Service = Inject()) -> str:
    return "ok" if isinstance(service, _Service) else "unexpected"


def test_documented_marker_example_runs() -> None:
    registry = ProviderRegistry()
    registry.provide(_Service, _Service, scope="request")
    registry.freeze()
    plan = compile_handler(
        _documented_handler,
        path_parameter_names=frozenset(),
        registry=registry,
    )

    assert (
        asyncio.run(plan.invoke(_Request(), object(), object(), RequestScope(registry)))
        == "ok"
    )


def _compile_case(scope: str, nested: bool = False):
    registry = ProviderRegistry()
    if nested:
        registry.provide(_Repository, _Repository, scope=scope)
        registry.provide(_NestedService, _NestedService, scope=scope)

        async def handler(service: _NestedService = Inject()) -> object:
            return service.repository
    else:
        registry.provide(_Service, _Service, scope=scope)

        async def handler(service: _Service = Inject()) -> object:
            return service

    registry.freeze()
    return registry, compile_handler(handler, path_parameter_names=frozenset(), registry=registry)


def _compile_empty_case():
    registry = ProviderRegistry()
    registry.freeze()

    async def handler() -> str:
        return "ok"

    return registry, compile_handler(handler, path_parameter_names=frozenset(), registry=registry)


def _disable_reflection(monkeypatch: pytest.MonkeyPatch) -> None:
    def reflection_used(*args: object, **kwargs: object) -> None:
        pytest.fail("compiled invocation must not inspect signatures or type hints")

    monkeypatch.setattr(inspect, "signature", reflection_used)
    monkeypatch.setattr(typing, "get_type_hints", reflection_used)
    monkeypatch.setattr(injection, "get_type_hints", reflection_used)


async def _measure_invocation(
    registry: ProviderRegistry,
    invoke: Callable[[object, object, object, RequestScope], object],
    iterations: int = 200,
) -> dict[str, int]:
    started_at = time.perf_counter_ns()
    cold_value = await invoke(_Request(), object(), object(), RequestScope(registry))
    cold_ns = time.perf_counter_ns() - started_at
    assert cold_value is not None

    warm_scope = RequestScope(registry)
    warm_value = await invoke(_Request(), object(), object(), warm_scope)
    assert warm_value is not None

    samples: list[int] = []
    for _ in range(5):
        started_at = time.perf_counter_ns()
        for _ in range(iterations):
            value = await invoke(_Request(), object(), object(), warm_scope)
            assert value is not None
        samples.append((time.perf_counter_ns() - started_at) // iterations)

    return {
        "cold_ns": cold_ns,
        "warm_ns": int(statistics.median(samples)),
    }


def test_compiled_invocation_avoids_reflection_for_hot_path_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = {
        "empty": _compile_empty_case(),
        "singleton": _compile_case("singleton"),
        "request": _compile_case("request"),
        "transient": _compile_case("transient"),
        "nested": _compile_case("request", nested=True),
    }
    _disable_reflection(monkeypatch)

    diagnostics = {
        name: asyncio.run(_measure_invocation(registry, plan.invoke))
        for name, (registry, plan) in cases.items()
    }

    print(f"compiled injection invocation diagnostics (ns): {diagnostics}")
    assert set(diagnostics) == {"empty", "singleton", "request", "transient", "nested"}
    assert all(
        measurement[phase] > 0
        for measurement in diagnostics.values()
        for phase in ("cold_ns", "warm_ns")
    )

    empty_warm_ns = diagnostics["empty"]["warm_ns"]
    for name in ("singleton", "request", "transient", "nested"):
        assert diagnostics[name]["warm_ns"] <= empty_warm_ns * 25, (
            f"{name} warm invocation exceeded 25x empty-handler baseline: "
            f"{diagnostics[name]['warm_ns']}ns vs {empty_warm_ns}ns"
        )
