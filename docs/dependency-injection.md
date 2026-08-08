# Dependency Injection

Hypern compiles provider construction and handler-binding plans before requests are accepted. Register providers with `app.provide()` and request them with `Inject()` parameters; the handler invocation path does not inspect signatures or type hints.

## Registering providers

```python
from hypern import Hypern

app = Hypern()

config = {"environment": "production"}
app.provide("config", config)
app.provide(UserRepository, UserRepository)
app.provide(UserService, UserService, scope="request")
app.provide("logger", create_logger, scope="transient")
```

A provider key can be a type, string, or another hashable object. A provider can be an existing value, class, synchronous factory, or asynchronous factory.

The supported scopes are:

- `singleton`: one value for the application lifetime; this is the default.
- `request`: at most one value in each request scope.
- `transient`: a new value for each resolution.

`provide()` returns the application, so registrations may be chained. Providers may depend on other registered providers through type annotations or `Inject()`.

## Type-keyed injection

With `Inject()` and a type annotation, the annotation is the provider key:

```python
from hypern import Inject, Path


@app.get("/users/:user_id")
async def get_user(
    user_id: int = Path(),
    service: UserService = Inject(),
):
    return await service.get(user_id)
```

## Explicit keys

Pass a key when the registry uses a name or when the annotation describes a protocol rather than the registration key:

```python
@app.get("/configuration")
def configuration(res, config: dict = Inject("config")):
    res.json(config)
```

`Inject()` requires a type annotation when no explicit key is provided. `Inject("config")` can be used with any useful annotation for editor support.

## Provider dependencies

Classes and factories can request other providers through annotations or markers. Hypern compiles the dependency graph and reports missing providers or cycles before startup.

```python
class UserService:
    def __init__(self, repository: UserRepository):
        self.repository = repository


app.provide(UserRepository, UserRepository)
app.provide(UserService, UserService, scope="request")
```

Use an explicit marker inside a provider when needed:

```python
def create_mailer(config: dict = Inject("config")) -> Mailer:
    return Mailer(config["smtp_url"])


app.provide(Mailer, create_mailer)
```

## Request context

`ctx` stores request and authentication state. It is intentionally separate from dependency resolution:

```python
@app.get("/session")
def session(res, ctx):
    ctx.set("trace", "active")
    res.json({"trace": ctx.get("trace"), "request_id": ctx.request_id})
```

Provider registration becomes immutable when the application starts. Register all providers during setup, before `listen()` or `start()`.

## Configuration errors and ordering

An unsupported scope passed to `app.provide()` raises `InjectionConfigurationError` immediately. Calling the public `app.provide()` after application registration has frozen raises `RuntimeError` from the application registration guard; calling `ProviderRegistry.provide()` after its registry is frozen raises `InjectionConfigurationError`. When Hypern freezes the provider graph, it raises `InjectionConfigurationError` for a missing provider dependency and `DependencyCycleError` for a provider cycle. Invalid injection annotations and unsupported handler parameter sources raise `InjectionConfigurationError` when Hypern compiles the handler plan.

Every handler parameter independently states where its value comes from. `Inject()` can therefore be freely combined with `Json()`, `Query()`, `Header()`, `Path()`, and `Body()`; decorator order does not control binding. The former decorator-based DI API is removed.
