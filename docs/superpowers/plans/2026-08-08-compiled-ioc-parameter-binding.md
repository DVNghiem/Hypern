# Compiled IoC and Parameter Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Replace positional decorator DI and validation with compiled marker-based parameter binding for functional Hypern handlers.

**Architecture:** A Python ProviderRegistry owns providers and compiles provider construction plans. A slot-backed RequestScope and precompiled HandlerPlan resolve only requested values, then invoke a handler without reflection in the request path. Existing middleware and error handling stay as the outer pipeline.

**Tech Stack:** Python 3.11+, msgspec, Hypern Rust extension, pytest, pytest-asyncio.

## Global Constraints

- All added or modified source-code comments must be written in English.
- Route/provider reflection may run only during registration/freeze, never while processing a request.
- The hot path must not eagerly construct unused providers, unwrap decorators, call inspect.signature, or call typing.get_type_hints.
- Functional handlers only; do not introduce class-controller or MVC APIs.
- Remove DIContainer, @inject, Hypern.inject, and @validate* APIs with no deprecation layer.

---

## File Structure

- Create hypern/injection.py: markers, registry, compiled provider/handler plans, request scope, and errors.
- Modify hypern/application.py: own registry, expose provide, compile handlers, and create a scope per request.
- Modify hypern/router.py: expose path parameter metadata needed by handler compilation.
- Modify hypern/__init__.py: export marker APIs and remove legacy exports.
- Delete hypern/di.py; delete decorator APIs from hypern/validation.py.
- Modify src/core/context.rs and src/lib.rs: remove Rust DIContainer but retain Context.
- Replace DI/validator tests and update README/docs.

### Task 1: Markers and Provider Registry

**Files:**

- Create: hypern/injection.py
- Create: tests/test_injection.py

**Interfaces:**

- Produces Inject(key: object | None = None), Json(), Query(name: str | None = None), Header(name: str), Path(name: str | None = None), and Body().
- Produces ProviderRegistry.provide(key, provider, *, scope: Literal["singleton", "request", "transient"]) -> None and ProviderRegistry.freeze() -> None.
- Produces InjectionConfigurationError and DependencyCycleError.

- [ ] **Step 1: Write failing marker and registration tests**

~~~python
def test_provide_rejects_unknown_scope() -> None:
    registry = ProviderRegistry()
    with pytest.raises(InjectionConfigurationError, match="scope"):
        registry.provide("service", object, scope="global")

def test_inject_has_optional_explicit_key() -> None:
    assert Inject("service").key == "service"
    assert Inject().key is None
~~~

- [ ] **Step 2: Run test to verify it fails**

Run: pytest tests/test_injection.py -q

Expected: FAIL because hypern.injection does not exist.

- [ ] **Step 3: Implement immutable marker and registry contracts**

~~~python
@dataclass(frozen=True, slots=True)
class Inject:
    key: object | None = None

class ProviderRegistry:
    def provide(self, key: object, provider: object, *, scope: Scope = "singleton") -> None:
        if scope not in {"singleton", "request", "transient"}:
            raise InjectionConfigurationError(f"unsupported provider scope: {scope}")
~~~

- [ ] **Step 4: Verify and commit**

Run: pytest tests/test_injection.py -q && ruff check hypern/injection.py tests/test_injection.py

~~~bash
git add hypern/injection.py tests/test_injection.py
git commit -m "feat: add injection markers and provider registry"
~~~

### Task 2: Compiled Provider Graph and Request Scope

**Files:**

- Modify: hypern/injection.py
- Modify: tests/test_injection.py

**Interfaces:**

- Consumes Task 1 registry and Inject.
- Produces RequestScope(registry), await RequestScope.resolve(key), and integer-slot compiled provider plans.

- [ ] **Step 1: Write failing scope and graph tests**

~~~python
async def test_request_provider_is_created_once_per_scope() -> None:
    calls = 0
    def factory() -> object:
        nonlocal calls
        calls += 1
        return object()
    registry = ProviderRegistry()
    registry.provide("value", factory, scope="request")
    registry.freeze()
    scope = RequestScope(registry)
    assert await scope.resolve("value") is await scope.resolve("value")
    assert calls == 1

def test_provider_cycle_fails_during_freeze() -> None:
    registry = ProviderRegistry()
    registry.provide(A, A)
    registry.provide(B, B)
    with pytest.raises(DependencyCycleError):
        registry.freeze()
~~~

- [ ] **Step 2: Run test to verify it fails**

Run: pytest tests/test_injection.py -q

Expected: FAIL because scopes and compiled dependency plans are absent.

- [ ] **Step 3: Implement provider compilation and slot resolution**

Use inspect.signature and typing.get_type_hints only in freeze(). Compile dependencies into integer slots. Use a private sentinel and RequestScope._values: list[object] for request caching. Support values, classes, sync factories, and async factories; resolve singleton/request/transient with their documented cache semantics.

- [ ] **Step 4: Add full provider matrix**

Add tests for singleton identity across scopes, transient non-identity, async factory, nested constructor injection, missing provider, and freeze-after-registration rejection.

- [ ] **Step 5: Verify and commit**

Run: pytest tests/test_injection.py -q && ruff check hypern/injection.py tests/test_injection.py

~~~bash
git add hypern/injection.py tests/test_injection.py
git commit -m "feat: compile scoped provider graphs"
~~~

### Task 3: HandlerPlan and Request Markers

**Files:**

- Modify: hypern/injection.py
- Modify: tests/test_injection.py

**Interfaces:**

- Consumes Task 2 ProviderRegistry and RequestScope.
- Produces compile_handler(handler, *, path_parameter_names: frozenset[str], registry) -> HandlerPlan.
- Produces await HandlerPlan.invoke(req, res, ctx, scope).

- [ ] **Step 1: Write failing handler-plan tests**

~~~python
async def test_handler_plan_binds_markers_and_dependency() -> None:
    async def handler(req, res, ctx, user_id: int = Path(), token: str = Header("X-Token"), service: Service = Inject()):
        return user_id, token, service
    plan = compile_handler(handler, path_parameter_names=frozenset({"user_id"}), registry=registry)
    assert await plan.invoke(req, res, ctx, scope) == (7, "abc", service)

def test_json_requires_annotation() -> None:
    async def handler(payload=Json()):
        return payload
    with pytest.raises(InjectionConfigurationError, match="Json"):
        compile_handler(handler, path_parameter_names=frozenset(), registry=registry)
~~~

- [ ] **Step 2: Run test to verify it fails**

Run: pytest tests/test_injection.py -q

Expected: FAIL because the handler compiler does not exist.

- [ ] **Step 3: Implement pre-bound resolvers**

Compile each default marker once. Json, Query, and Path use existing msgspec validation/coercion semantics; Body returns raw bytes; Header reads the named header and coerces to its declared type; Inject stores a provider slot. Bind req, res, and ctx by reserved name. Build positional arguments in declaration order and allocate keyword arguments only for keyword-only parameters.

- [ ] **Step 4: Add request binding/error tests**

Cover sync/async handlers, raw body, valid and invalid JSON, query defaults/coercion, required and optional headers, missing path values, unknown marker/annotation combinations, and arbitrary parameter ordering.

- [ ] **Step 5: Prove no reflection in invocation and commit**

~~~python
async def test_invocation_does_not_use_reflection(monkeypatch) -> None:
    plan = compile_handler(handler, path_parameter_names=frozenset(), registry=registry)
    monkeypatch.setattr(inspect, "signature", pytest.fail)
    monkeypatch.setattr(typing, "get_type_hints", pytest.fail)
    await plan.invoke(req, res, ctx, scope)
~~~

Run: pytest tests/test_injection.py -q && ruff check hypern/injection.py tests/test_injection.py

~~~bash
git add hypern/injection.py tests/test_injection.py
git commit -m "feat: compile handler parameter binding"
~~~

### Task 4: Application and Router Integration

**Files:**

- Modify: hypern/application.py
- Modify: hypern/router.py
- Modify: tests/test_router_integration.py
- Modify: tests/test_middleware_pipeline.py

**Interfaces:**

- Consumes ProviderRegistry, RequestScope, and compile_handler.
- Produces Hypern.provide(key, provider, *, scope="singleton") -> Hypern.
- Replaces Hypern._di with Hypern._providers and raw route calls with bound handler invocation.

- [ ] **Step 1: Write a failing app-route test**

~~~python
def test_route_injects_request_service_and_json(client: httpx.Client) -> None:
    app = create_test_app()
    app.provide(Service, Service, scope="request")
    @app.post("/items/:item_id")
    async def create_item(item_id: int = Path(), payload: CreateItem = Json(), service: Service = Inject()):
        return {"id": item_id, "name": payload.name, "service": service.identifier}
    response = client.post("/items/7", json={"name": "book"})
    assert response.status_code == 200
    assert response.json() == {"id": 7, "name": "book", "service": "request"}
~~~

- [ ] **Step 2: Run test to verify it fails**

Run: pytest tests/test_router_integration.py -q

Expected: FAIL because _wrap_handler creates the old Rust DI context and invokes an unbound handler.

- [ ] **Step 3: Integrate plans at registration and scope at request time**

Compile raw app/router handlers while registration is open; recompile when router registration changes; freeze providers before listen/start. In _wrap_handler, create Rust Context plus RequestScope and invoke the compiled handler inside the existing middleware/error pipeline. Remove singleton, factory, di, and inject from Hypern; add provide.

- [ ] **Step 4: Add pipeline regression tests**

Cover app routes/mounted routers, sync/async handlers, request-scope isolation, middleware execution, and marker validation errors processed by existing exception handling.

- [ ] **Step 5: Verify and commit**

Run: pytest tests/test_router_integration.py tests/test_middleware_pipeline.py -q

~~~bash
git add hypern/application.py hypern/router.py tests/test_router_integration.py tests/test_middleware_pipeline.py
git commit -m "feat: bind compiled injection plans in routes"
~~~

### Task 5: Remove Duplicate Legacy DI and Validation Paths

**Files:**

- Delete: hypern/di.py
- Modify/Delete: hypern/validation.py
- Modify: hypern/__init__.py
- Modify: src/core/context.rs
- Modify: src/lib.rs
- Modify: tests/test_di_context.py and tests/test_validation.py

**Interfaces:**

- Consumes marker APIs and app integration from Tasks 1-4.
- Produces a public package that exports marker binding APIs and no positional decorator APIs.

- [ ] **Step 1: Replace every legacy test and documentation call site**

Run: rg -n "@inject|app\\.inject|validate_body|validate_query|validate_params|@validate|\\.singleton\\(|\\.factory\\(" hypern tests docs README.md

Convert each route test/example to Inject, Json, Query, Path, Header, or Body. Retain only reusable ValidationError and decoder utilities needed by injection.py.

- [ ] **Step 2: Run suite before deletion**

Run: pytest -q

Expected: all migrated tests pass while legacy source still exists.

- [ ] **Step 3: Delete duplicate implementations**

Remove Rust DIContainer from src/core/context.rs, Pyo3 registration/export in src/lib.rs, Python imports/exports, hypern/di.py, and positional validation decorators. Preserve Rust Context for request/auth state.

- [ ] **Step 4: Verify and commit**

Run: cargo fmt --check && cargo check && pytest -q && ruff check hypern tests && git diff --check

~~~bash
git add -A
git commit -m "refactor: remove positional DI and validation decorators"
~~~

### Task 6: Documentation and Performance Regression Coverage

**Files:**

- Modify: README.md
- Modify: docs/dependency-injection.md
- Modify: docs/validation.md
- Modify: docs/routing.md
- Create: tests/test_injection_performance.py

**Interfaces:**

- Documents the public API from Tasks 1-4.
- Produces repeatable reflection guards and diagnostic microbenchmark cases.

- [ ] **Step 1: Write executable documentation example**

~~~python
async def test_documented_marker_example_runs() -> None:
    registry = ProviderRegistry()
    registry.provide(Service, Service, scope="request")
    registry.freeze()
    plan = compile_handler(example_handler, path_parameter_names=frozenset(), registry=registry)
    assert await plan.invoke(req, res, ctx, RequestScope(registry)) == "ok"
~~~

- [ ] **Step 2: Add hot-path performance coverage**

Create empty-handler, singleton, request, transient, and nested-graph cases. After plan compilation monkeypatch reflection APIs to fail and invoke every case repeatedly. Report time.perf_counter_ns() diagnostics only; do not use unstable absolute-time assertions.

- [ ] **Step 3: Rewrite public documentation**

Document provide, every marker, provider scopes, error behavior, and that decorator order no longer controls binding. Remove decorator-based DI/validation examples.

- [ ] **Step 4: Final verification and commit**

Run: cargo fmt --check && cargo check && pytest -q && ruff check hypern tests && git diff --check

~~~bash
git add README.md docs tests/test_injection_performance.py
git commit -m "docs: document compiled injection markers"
~~~

## Plan Self-Review

- Spec coverage: Tasks 1-3 implement markers, scopes, compilation, validation, errors, and no-reflection constraints; Task 4 integrates middleware/error pipeline; Task 5 removes duplicate legacy paths; Task 6 covers documentation and performance.
- Placeholder scan: no unfinished markers or unspecified verification steps remain.
- Type consistency: later tasks use ProviderRegistry, RequestScope, HandlerPlan, and compile_handler introduced by earlier tasks.
