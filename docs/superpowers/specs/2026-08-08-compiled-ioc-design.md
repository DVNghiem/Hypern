# Compiled IoC and Parameter Binding Design

## Goal

Replace Hypern's positional decorator-based dependency injection and request
validation with one compiled parameter-binding system. The system must support
functional route handlers, inject dependencies without decorator-order coupling,
and add no reflection work to the request hot path.

## Public API

Dependencies are explicitly requested with `Inject`:

```python
app.provide(UserService, UserService, scope="request")

@router.post("/users/:user_id")
async def create_user(
    req,
    res,
    user_id: str = Path(),
    service: UserService = Inject(),
    payload: CreateUser = Json(),
    query: CreateUserQuery = Query(),
    request_id: str | None = Header("X-Request-ID"),
):
    return await service.create(user_id, payload, query, request_id)
```

The parameter markers are:

| Marker | Source | Validation behavior |
| --- | --- | --- |
| `Inject(key=None)` | IoC provider registry | Resolves by annotation, or by explicit key. |
| `Json()` | Request JSON body | Parses JSON and validates/coerces it using the annotation. |
| `Query(name=None)` | Query string | Validates/coerces using the annotation. `name` is optional for scalar parameters. |
| `Header(name)` | Request header | Coerces to the annotation; optional annotations accept missing headers. |
| `Path(name=None)` | Route parameter | Validates/coerces using the annotation. |
| `Body()` | Raw request body | Supplies raw `bytes`; it performs no JSON parsing. |

`req`, `res`, and `ctx` remain reserved transport parameters and are bound by
name. `ctx` remains request/auth state only, not a dependency container.

## Provider model

`app.provide(key, provider, scope=...)` owns all providers. A key can be a type
or a string. Providers can be an instance, class, sync factory, or async
factory. Classes and factories may themselves request `Inject` parameters.

Scopes are:

- `singleton`: create once and retain for the application lifetime.
- `request`: create at most once per request, then cache in that request scope.
- `transient`: create every time it is requested.

Provider construction plans are compiled at registration time. The registry
detects missing providers and dependency cycles before the application accepts
requests. The registry becomes immutable when application registration freezes.

## Compiled execution model

At route registration or application freeze, Hypern unwraps route metadata once
and compiles a `HandlerPlan`. The plan contains an ordered collection of
pre-bound resolvers for every parameter. It performs `inspect.signature` and
`typing.get_type_hints` only at that point.

For every request, Hypern creates a lightweight `RequestScope` backed by a list
of provider slots and a sentinel value. The handler plan invokes only its
precompiled resolvers, builds its argument vector, and calls the handler.
Keyword arguments are constructed only when the callable declares keyword-only
parameters. Separate sync and async plans avoid coroutine detection in the
common request path.

The request hot path must not call reflection APIs, unwrap decorators, resolve
provider names/types through dictionaries, scan all providers, or eagerly create
factories that the route does not use.

## Validation and decorator removal

`@validate_body`, `@validate_query`, `@validate_params`, and `@validate` are
removed. Their request parsing and `msgspec` validation behavior moves into the
resolvers for `Json`, `Query`, and `Path`.

`@inject` and `Hypern.inject` are also removed. They currently pass dependencies
as positional arguments through wrappers, which duplicates the new binder and
couples behavior to decorator composition.

No deprecation compatibility layer is required because this framework has no
external consumers. Documentation and tests are updated to use markers.

## Existing implementation changes

The Rust `DIContainer` and its export are removed. Its eager factory execution
would create unused work on every request and it cannot own Python callable
inspection plans without cross-language coordination. Rust `Context` remains
for request, authentication, and arbitrary request-local state.

The existing application route pipeline remains responsible for middleware,
error handling, and response lifecycle. It receives a single bound handler from
the compiled parameter system; it does not receive wrappers that inject or
validate positional arguments.

## Errors

Registration-time errors include invalid marker/annotation combinations, a
missing provider, a conflicting parameter source, and provider dependency
cycles. Request-time errors include malformed JSON, validation/coercion failure,
and missing required headers or request values. Request failures retain the
framework's normal validation-error response format.

## Verification

Tests cover sync and async handlers, every marker, scalar and schema validation,
all provider scopes, nested provider construction, transient/request/singleton
caching, missing providers, cycles, malformed request data, and middleware/error
pipeline integration.

Regression tests assert that reordered parameter markers produce the same
binding result and that the request invocation path does not call
`inspect.signature` or `typing.get_type_hints`.

Microbenchmarks compare an empty route, singleton injection, request-scoped
injection, transient injection, and a nested provider graph. The benchmark
records cold and warm behavior and guards against regressions relative to the
empty-handler baseline.

## Code language requirement

Every added or modified source-code comment must be written in English.
