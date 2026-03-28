# Phase 4 — Ecosystem & Future

**Goal:** Integrate with the broader ecosystem and support advanced use-cases.
Items here are speculative / long-horizon and depend on Phase 3 being stable.

**Depends on:** Phase 3 (HTTP client for Redis; Rust WS for pub/sub; metrics for
observability stack)

---

## 4.1 Redis Integration

**Priority:** P1 (within this phase)  
**Files:** `src/` (new `redis/` module), `hypern/redis.py`

### Use-Cases
- Session store for `JWTAuth` refresh tokens (Phase 3.2)
- Response caching backend for `CacheMiddleware`
- Pub/sub backend for `RealtimeBroadcast` across processes
- Rate limiter shared state across worker processes (current `RateLimitMiddleware`
  is per-process)

### Implementation Steps

- [ ] **4.1.1** Add `redis` crate (`deadpool-redis` for pooling) to `Cargo.toml`.
- [ ] **4.1.2** Create `src/redis/mod.rs`:
  - `RedisPool` pyclass: `connect(url, pool_size)`, `get(key)`, `set(key, value, ex)`,
    `del(key)`, `expire(key, seconds)`, `incr(key)`, `publish(channel, message)`,
    `subscribe(channel) -> AsyncIterator`.
  - All methods are `async` and bridge via `future_into_py`.
- [ ] **4.1.3** Expose `hypern.redis.RedisPool` and `app.setup_redis(url)`.
- [ ] **4.1.4** Integrate with `JWTAuth`: if `redis_pool` passed to `JWTAuth`,
  store refresh token JTIs in Redis (set with TTL = refresh token lifetime).
- [ ] **4.1.5** Integrate with `RateLimitMiddleware`: add `RedisRateLimiter` variant
  that uses `INCR`/`EXPIRE` in Redis for cross-process rate limiting.
- [ ] **4.1.6** Integrate with `RealtimeBroadcast`: add `RedisAdapter` that bridges
  `publish`/`subscribe` so events fan out across worker processes.
- [ ] **4.1.7** Tests: `tests/test_redis.py` — use `fakeredis` or testcontainers.
- [ ] **4.1.8** Document in `docs/redis.md`.

### New Cargo Dependencies
```toml
redis = { version = "0.25", features = ["tokio-comp", "connection-manager"] }
deadpool-redis = "0.15"
```

---

## 4.2 GraphQL Endpoint (Strawberry Integration)

**Priority:** P2 (within this phase)  
**Files:** `hypern/graphql.py`, `hypern/application.py`

### Problem
REST-only framework misses the growing GraphQL user-base.

### Implementation Steps

- [ ] **4.2.1** Create `hypern/graphql.py` with `GraphQLRoute` class:
  ```python
  import strawberry
  from hypern.graphql import GraphQLRoute

  @strawberry.type
  class Query:
      @strawberry.field
      def hello(self) -> str:
          return "world"

  schema = strawberry.Schema(Query)
  app.mount("/graphql", GraphQLRoute(schema))
  ```
- [ ] **4.2.2** `GraphQLRoute` implements `__call__(req, res, ctx)` — parses
  `{"query": "...", "variables": {...}}` from request body, calls
  `schema.execute_sync()` or `await schema.execute()`, returns JSON.
- [ ] **4.2.3** Support `GET /graphql?query=...` for simple queries.
- [ ] **4.2.4** Serve GraphiQL IDE at `GET /graphql` when `Accept: text/html`.
- [ ] **4.2.5** Subscription support via WebSocket: `POST /graphql` with
  `graphql-ws` protocol, bridged through Rust WebSocket (Phase 2.2).
- [ ] **4.2.6** Make `strawberry-graphql` an optional dependency in `pyproject.toml`.
- [ ] **4.2.7** Document in `docs/graphql.md`.

---

## 4.3 MySQL & SQLite Support

**Priority:** P2 (within this phase)  
**Files:** `src/database/`, `Cargo.toml`, `hypern/database.py`

### Problem
README mentions multi-DB support but only PostgreSQL is implemented.

### Implementation Steps

- [ ] **4.3.1** Add `sqlx` with `mysql` and `sqlite` features to `Cargo.toml`
  (already has `sqlx` with `postgres`; add features).
- [ ] **4.3.2** Refactor `src/database/pool.rs` to abstract over driver via a
  `DatabaseDriver` enum: `Postgres(deadpool_postgres::Pool)`,
  `Mysql(sqlx::MySqlPool)`, `Sqlite(sqlx::SqlitePool)`.
- [ ] **4.3.3** Unify `DbSession` execute/fetch/transaction API across all three
  drivers.
- [ ] **4.3.4** Parse DSN scheme (`postgres://`, `mysql://`, `sqlite://`) in
  `Database.__init__()` to select the right driver.
- [ ] **4.3.5** Verify `RowConverter` handles MySQL/SQLite type systems
  (`DECIMAL`, `TINYINT` as bool, etc.).
- [ ] **4.3.6** Tests: add MySQL and SQLite variants in `tests/test_database.py`
  using testcontainers.
- [ ] **4.3.7** Document new DSN formats in `docs/database.md`.

---

## 4.4 gRPC / Protobuf Support

**Priority:** P3 (within this phase)  
**Files:** `src/` (new `grpc/` module), `hypern/grpc.py`

### Use-Case
Microservice interop — expose Hypern services as gRPC endpoints alongside REST.

### Implementation Steps

- [ ] **4.4.1** Add `tonic` and `prost` crates to `Cargo.toml`.
- [ ] **4.4.2** Create `src/grpc/mod.rs` with `GrpcServer` pyclass that accepts a
  mapping of `service_name → Python handler`.
- [ ] **4.4.3** Add `hypern/grpc.py` with `GrpcRoute` and `@grpc_method` decorator.
- [ ] **4.4.4** Support `.proto` file compilation via `prost-build` in `build.rs`.
- [ ] **4.4.5** Serve gRPC on a separate port (default `:50051`) alongside HTTP.
- [ ] **4.4.6** Add `app.setup_grpc(port=50051, proto_dir="./protos")`.
- [ ] **4.4.7** Document in `docs/grpc.md`.

### New Cargo Dependencies
```toml
tonic = "0.12"
prost = "0.13"
```

---

## 4.5 Response Caching Middleware

**Priority:** P2 (within this phase)  
**Files:** `src/fast_path/json_cache.rs`, `src/middleware/builtin.rs`

### Problem
`JsonResponseCache` exists in `fast_path/json_cache.rs` but is not wired into the
middleware chain or exposed to Python.

### Implementation Steps

- [ ] **4.5.1** Add `CacheMiddleware` to `src/middleware/builtin.rs`:
  - Config: `ttl_seconds`, `cache_control_respect: bool`, `max_cache_size`.
  - Key: by default `method + path + query string` (configurable via `key_fn`).
  - Storage: wire to existing `JsonResponseCache` (extend to store arbitrary `Bytes`).
- [ ] **4.5.2** Respect `Cache-Control: no-store` / `no-cache` from request headers
  when `cache_control_respect=True`.
- [ ] **4.5.3** Set `X-Cache: HIT` / `X-Cache: MISS` response header.
- [ ] **4.5.4** Expose `CacheMiddlewareConfig` pyclass and add to
  `hypern/middleware.py`.
- [ ] **4.5.5** Per-route opt-in decorator `@cache(ttl=60)` in Python layer.
- [ ] **4.5.6** Redis backend (from 4.1): `CacheMiddleware(backend="redis")` for
  cross-process cache sharing.
- [ ] **4.5.7** Tests: assert HIT/MISS headers, TTL expiry, no-store bypass.

---

## 4.6 Multi-Tenant Database Routing

**Priority:** P3 (within this phase)  
**Files:** `hypern/database.py`, `src/database/pool.rs`

### Use-Case
SaaS applications with one DB schema per tenant, routed by subdomain or JWT claim.

### Implementation Steps

- [ ] **4.6.1** Add `TenantResolver` protocol: `async def resolve(req) -> str` —
  returns a tenant identifier (e.g. subdomain, JWT `tenant_id` claim).
- [ ] **4.6.2** Add `MultiTenantDatabase(resolver, dsn_template)` where `dsn_template`
  is `"postgres://host/{tenant}"`.
- [ ] **4.6.3** Maintain a pool per resolved tenant (lazy-init, bounded by
  `max_tenants` config).
- [ ] **4.6.4** Evict least-recently-used tenant pools when `max_tenants` exceeded.
- [ ] **4.6.5** Inject `db: DbSession` for the resolved tenant via DI
  (`@inject("db")`).
- [ ] **4.6.6** Document in `docs/database.md` under "Multi-tenant" section.
