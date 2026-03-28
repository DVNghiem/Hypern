# Phase 3 — New Capabilities

**Goal:** Add high-value new features that users of a modern Python framework expect.

**Depends on:** Phase 2 (DB async fixes needed for query builder; Rust WS needed for
Redis pub/sub integration)

---

## 3.1 Built-in Async HTTP Client

**Priority:** P1 — missing standard feature  
**Files:** `src/` (new `client/` module), `hypern/client.py`, `hypern/_hypern.pyi`

### Problem
No outbound HTTP client exists. Users must install `httpx`/`aiohttp` separately and
lose the benefit of Rust-level connection pooling and GIL-free I/O.

### Implementation Steps

- [ ] **3.1.1** Create `src/client/mod.rs` backed by `reqwest` crate (already common
  in the ecosystem; add to `Cargo.toml` with `rustls` feature).
- [ ] **3.1.2** Expose `HttpClient` pyclass:
  ```python
  client = HttpClient(base_url="https://api.example.com", timeout=30)
  response = await client.get("/users", headers={}, params={})
  response = await client.post("/users", json={"name": "Alice"})
  ```
- [ ] **3.1.3** `ClientResponse` pyclass: `.status`, `.headers`, `.text()`,
  `.json()`, `.bytes()`.
- [ ] **3.1.4** Connection pool config: `max_connections`, `keep_alive_timeout`.
- [ ] **3.1.5** Retry config: `retries=3, backoff="exponential"`.
- [ ] **3.1.6** Expose `hypern.client.HttpClient` from `hypern/__init__.py`.
- [ ] **3.1.7** Add `hypern/client.py` with convenience `get()`, `post()`, `put()`,
  `delete()` module-level async functions (shared default client).
- [ ] **3.1.8** Tests: `tests/test_http_client.py` — mock server via `pytest-httpserver`.
- [ ] **3.1.9** Document in `docs/http-client.md`.

---

## 3.2 RS256 / ES256 JWT + Refresh Tokens

**Priority:** P1 — security improvement  
**Files:** `hypern/auth.py`, `src/utils/crypto.rs`

### Problem
Current JWT supports only `HS256` via Python stdlib `hmac`. RS256/ES256 are required
for asymmetric key scenarios (microservices, JWKS endpoints). No refresh token support.

### Implementation Steps

- [ ] **3.2.1** In `src/utils/crypto.rs`, add:
  - `jwt_sign_rs256(payload_json: &str, pem_key: &[u8]) -> Result<String>`
  - `jwt_verify_rs256(token: &str, pem_key: &[u8]) -> Result<String>` (returns payload)
  - `jwt_sign_es256(...)` / `jwt_verify_es256(...)` using `p256` crate.
- [ ] **3.2.2** Expose as `sign_jwt_rs256(payload, pem)` / `verify_jwt_rs256(token, pem)`
  Python functions via PyO3.
- [ ] **3.2.3** In `hypern/auth.py`, extend `JWTAuth.__init__` to accept
  `algorithm: Literal["HS256", "RS256", "ES256"] = "HS256"` and optional
  `private_key_pem`, `public_key_pem` parameters.
- [ ] **3.2.4** Route signing/verifying to the appropriate Rust or Python implementation.
- [ ] **3.2.5** Add `JWTAuth.create_refresh_token(subject, ttl_days)` that issues a
  long-lived refresh token stored in a configurable token store (in-memory dict by
  default; pluggable interface for Redis in Phase 4).
- [ ] **3.2.6** Add `@jwt.refresh` route decorator that validates a refresh token and
  issues a new access token.
- [ ] **3.2.7** Add JWKS endpoint helper: `app.setup_jwks("/jwks.json")` that serves
  the public key in JWK format.
- [ ] **3.2.8** Tests: `tests/test_auth.py` — extend with RS256, ES256, refresh flow,
  JWKS endpoint.

### New Cargo Dependencies
```toml
rsa = "0.9"
p256 = { version = "0.13", features = ["ecdsa"] }
```

---

## 3.3 Prometheus / OpenTelemetry Metrics

**Priority:** P2 — observability  
**Files:** `src/` (new `telemetry/` module), `hypern/application.py`

### Problem
No built-in metrics or tracing. Users cannot observe request latency, error rates,
or DB pool utilisation without external tooling that cannot hook into the Rust layer.

### Implementation Steps

- [ ] **3.3.1** Add `prometheus-client` crate (or write a minimal exposition format
  builder) to `Cargo.toml`.
- [ ] **3.3.2** Create `src/telemetry/mod.rs` with global metrics registry:
  - `REQUEST_COUNTER`: labels `method`, `path`, `status`
  - `REQUEST_DURATION_HISTOGRAM`: P50/P95/P99 latency
  - `ACTIVE_CONNECTIONS`: gauge
  - `DB_POOL_USED` / `DB_POOL_IDLE`: gauges per named pool
  - `TASK_QUEUE_DEPTH`: from `TaskExecutor`
- [ ] **3.3.3** Instrument `src/core/interpreter.rs` — record counter and duration
  after each request completes.
- [ ] **3.3.4** Instrument `src/database/pool.rs` — update pool gauges on
  borrow/return.
- [ ] **3.3.5** Add `app.setup_metrics(path="/metrics")` Python method that registers
  a `GET /metrics` route returning Prometheus text exposition format.
- [ ] **3.3.6** OpenTelemetry trace context: propagate `traceparent` header (W3C
  TraceContext) — inject `trace_id` / `span_id` into `Context` so Python handlers
  can access them.
- [ ] **3.3.7** Add `app.setup_opentelemetry(endpoint, service_name)` that exports
  spans via OTLP/gRPC using `opentelemetry-otlp` crate.
- [ ] **3.3.8** Document in `docs/observability.md`.

### New Cargo Dependencies
```toml
prometheus = "0.13"
opentelemetry = "0.24"
opentelemetry-otlp = "0.17"
opentelemetry_sdk = "0.24"
```

---

## 3.4 Pydantic v2 Request Validation Integration

**Priority:** P2 — developer experience  
**Files:** `hypern/validation.py`, `hypern/openapi.py`

### Problem
The hand-rolled `@Validator` in `hypern/validation.py` cannot validate nested
models, enums, or custom types. Pydantic v2 is the de-facto Python validation
standard and is already installed by most users.

### Implementation Steps

- [ ] **3.4.1** Detect if `pydantic` is installed at import time (`importlib.util.find_spec`).
- [ ] **3.4.2** In `hypern/validation.py`, add `@validate(body=MyModel)` decorator
  that:
  1. Reads `request.json()` (or `request.body`).
  2. Calls `MyModel.model_validate(data)` (Pydantic v2).
  3. Injects the validated model instance as a keyword argument into the handler.
  4. On `ValidationError`, returns a `422 Unprocessable Entity` JSON response with
     Pydantic's error detail.
- [ ] **3.4.3** Support path/query param validation: `@validate(query=QueryModel)`.
- [ ] **3.4.4** In `hypern/openapi.py`, if a route uses `@validate(body=Model)`,
  call `Model.model_json_schema()` and embed it in the OpenAPI `requestBody`.
- [ ] **3.4.5** Support response model: `@validate(response=ResponseModel)` — validate
  outgoing JSON and generate OpenAPI response schema.
- [ ] **3.4.6** Make `pydantic` an optional dependency in `pyproject.toml`
  (`pydantic>=2.0` in `[project.optional-dependencies].validation`).
- [ ] **3.4.7** Tests: `tests/test_validation.py` — cover valid, invalid body, invalid
  query params, custom error format.
- [ ] **3.4.8** Document in `docs/validation.md`.

---

## 3.5 Query Builder + Migration Runner

**Priority:** P3 — developer experience  
**Files:** `hypern/database.py` (new `query.py`, `migrations.py`)

### Problem
Users must write raw SQL strings for all queries. No migration management exists.

### Implementation Steps

- [ ] **3.5.1** Create `hypern/query.py` — a thin Python query builder:
  ```python
  q = Query("users").select("id", "name").where("active = $1", True).limit(10)
  rows = await session.fetch(q)
  ```
- [ ] **3.5.2** `Query` class supports: `.select()`, `.insert()`, `.update()`,
  `.delete()`, `.where()`, `.order_by()`, `.limit()`, `.offset()`, `.join()`.
- [ ] **3.5.3** `Query.build() -> tuple[str, list]` returns `(sql, params)`.
- [ ] **3.5.4** Create `hypern/migrations.py`:
  - `MigrationRunner(db, migrations_dir="./migrations")`
  - Reads `.sql` files named `001_initial.sql`, `002_add_users.sql`, etc.
  - Tracks applied migrations in `hypern_migrations` table.
  - `await runner.migrate()` — apply pending.
  - `await runner.rollback(steps=1)` — requires `-- rollback` section in SQL files.
- [ ] **3.5.5** Add `hypern migrate` and `hypern migrate:rollback` CLI commands.
- [ ] **3.5.6** Tests: `tests/test_database.py` — extend with query builder and
  migration round-trips (use an in-memory SQLite or test PG container).
- [ ] **3.5.7** Document in `docs/database.md`.

---

## 3.6 Circuit Breaker Middleware (Rust)

**Priority:** P3 — reliability  
**Files:** `src/middleware/builtin.rs`, `src/middleware/chain.rs`

### Problem
No protection against cascading failures when a downstream service degrades.

### Implementation Steps

- [ ] **3.6.1** Add `CircuitBreakerMiddleware` to `builtin.rs`:
  - States: `Closed → Open → HalfOpen`
  - Config: `failure_threshold`, `success_threshold`, `timeout_seconds`
  - Track per-route or global failure counts using `DashMap<RouteHash, AtomicU64>`.
- [ ] **3.6.2** In `Open` state, short-circuit with `503 Service Unavailable` before
  invoking the Python handler.
- [ ] **3.6.3** Expose `CircuitBreakerConfig` pyclass for Python configuration.
- [ ] **3.6.4** Expose `CircuitBreakerMiddleware` through `hypern/middleware.py`.
- [ ] **3.6.5** Add `CircuitBreakerStats` (state, failure_count, last_failure_at)
  accessible from Python.
- [ ] **3.6.6** Tests: `tests/test_middleware.py` — simulate failures and verify state
  transitions.
