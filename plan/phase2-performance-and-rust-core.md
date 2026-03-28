# Phase 2 — Performance & Rust Core

**Goal:** Resolve all P0/P1 performance issues documented in the performance
optimization plan, move WebSocket to Rust, and expose the static file handler
to Python.

**Depends on:** Phase 1 (type stubs should be done before exposing new Rust APIs)

---

## 2.1 Fix Blocking Database Operations (P0)

**Priority:** P0 — thread starvation under load  
**Files:** `src/database/request_context.rs`, `src/database/operation.rs`,
`src/database/pool.rs`

### Problem
Every DB method calls `block_on()` which blocks the calling Tokio worker thread.
Under concurrent load this starves the thread pool, causing request queuing.
Root cause: the Python→Rust boundary requires synchronous return values, so async
DB futures are blocked inline.

### Implementation Steps

- [ ] **2.1.1** Remove the separate 4-thread DB Tokio runtime in `pool.rs` (lines 13–21).
  Share the global application runtime (`core/global.rs ::RUNTIME`).
- [ ] **2.1.2** In `request_context.rs`, consolidate the three sequential
  `Mutex::lock()` calls (lines 259–261) into a single lock on a consolidated state
  struct:
  ```rust
  struct RequestState {
      connection: Option<PooledConnection>,
      in_transaction: bool,
      dirty: bool,
  }
  ```
- [ ] **2.1.3** Replace the double mutex acquire in connection take/put
  (`request_context.rs` lines 162–167) with a single `parking_lot::Mutex` guard held
  for the whole operation.
- [ ] **2.1.4** In `operation.rs`, replace the 3× `block_on` in `RowStream.__next__`
  (lines 43–50) with `std::sync::Mutex` + a pre-blocked channel fill strategy:
  fetch the next page of rows synchronously during `__next__` with a single
  `block_on`, re-use the buffered rows until exhausted, then fetch the next page.
- [ ] **2.1.5** Benchmark with `wrk`/`k6` before and after: target ≥2× throughput
  improvement under 100-concurrent DB requests.
- [ ] **2.1.6** Update `docs/performance-optimization-plan.md` — mark P0 items fixed.

---

## 2.2 Rust-Backed WebSocket

**Priority:** P1 — performance and correctness  
**Files:** `src/http/` (new `websocket.rs`), `src/core/worker.rs`,
`src/core/interpreter.rs`, `hypern/websocket.py`

### Problem
Current WebSocket is pure Python asyncio queues. The Axum WS upgrade layer is not
wired to the Rust runtime, making WS significantly slower and more fragile than
the HTTP counterpart.

### Implementation Steps

- [ ] **2.2.1** Create `src/http/websocket.rs` with:
  - `WebSocketUpgrade` — wraps Axum's `axum::extract::ws::WebSocketUpgrade`.
  - `RustWebSocket` pyclass — exposes `send_text`, `send_bytes`, `send_json`,
    `receive_text`, `receive_bytes`, `receive_json`, `close` to Python.
  - Message framing (text / binary / ping / pong / close) handled in Rust.
- [ ] **2.2.2** Register WS routes in `src/routing/router.rs` separately from HTTP
  routes — store a `ws_handlers: HashMap<u64, PyObject>` alongside `handlers`.
- [ ] **2.2.3** In `src/core/worker.rs`, add Axum route handler for WS paths that
  performs the upgrade, creates a `RustWebSocket`, and calls the Python handler via
  `future_into_py`.
- [ ] **2.2.4** Keep `hypern/websocket.py`'s `WebSocketRoom` (broadcast group) wired
  to `RustWebSocket` instead of the asyncio bridge.
- [ ] **2.2.5** Preserve the Python-facing API: `@app.ws("/path")` decorator and
  `WebSocket` object methods staying the same — only internals change.
- [ ] **2.2.6** Add `WebSocketRoom.broadcast_rust()` that uses Axum's native
  `broadcast::channel` for fan-out, avoiding per-connection Python calls for pure
  push scenarios.
- [ ] **2.2.7** Update tests in `tests/test_websocket.py`.

---

## 2.3 Static File Serving Python API

**Priority:** P2 — feature gap  
**Files:** `src/fast_path/static_files.rs`, `hypern/application.py`,
`hypern/_hypern.pyi`

### Problem
`StaticFileHandler` exists in Rust but has no Python-facing API. Users must serve
static files through a manual route handler.

### Implementation Steps

- [ ] **2.3.1** Expose `StaticFileHandler` as a pyclass with:
  ```python
  StaticFileHandler(directory: str, prefix: str, index: str = "index.html")
  ```
- [ ] **2.3.2** Support ETag generation (hash of file mtime + size) and conditional
  requests (`If-None-Match` → `304 Not Modified`).
- [ ] **2.3.3** Support `Cache-Control: max-age=N` config parameter.
- [ ] **2.3.4** Add `Hypern.static(prefix, directory, **kwargs)` Python helper that
  registers the static handler for all `GET prefix/*` paths.
- [ ] **2.3.5** SPA fallback mode: `spa=True` parameter — serve `index.html` for
  any path that doesn't match a file.
- [ ] **2.3.6** Add `Content-Type` inference from file extension (reuse
  `content_types` module constants).
- [ ] **2.3.7** Test: serve a small fixture directory; assert ETag round-trips, 404
  on missing files, and `index.html` fallback in SPA mode.
- [ ] **2.3.8** Document in `docs/` as `static-files.md`.

---

## 2.4 Merge DB Runtime into Global Runtime

**Priority:** P1 — resource efficiency  
**Files:** `src/database/pool.rs`, `src/core/global.rs`

### Problem
The DB subsystem spawns its own 4-thread Tokio runtime. On a 4-core machine this
means 8 Tokio threads competing for 4 cores, plus the overhead of cross-runtime
channel hops for every DB call.

### Implementation Steps

- [ ] **2.4.1** Remove `DATABASE_RUNTIME` static in `pool.rs`.
- [ ] **2.4.2** Replace all `DATABASE_RUNTIME.block_on(...)` calls with
  `RUNTIME.block_on(...)` from `core/global.rs`.
- [ ] **2.4.3** Ensure pool `connect()` is called post-fork (already gated by the
  multiprocess lifecycle — verify and document).
- [ ] **2.4.4** Verify no deadlock: `RUNTIME.block_on` must not be called from within
  an async Tokio context (it panics). Audit call sites — all should be in sync
  Python-invoked code paths (outside `async fn`).
- [ ] **2.4.5** Load-test with 50 concurrent DB-heavy requests; confirm no panics.

---

## 2.5 `DashMap` REQUEST_CONTEXTS Memory Management

**Priority:** P2 — memory leak under high request volume  
**Files:** `src/database/request_context.rs`

### Problem
`DashMap` used for `REQUEST_CONTEXTS` never shrinks — on high-traffic deployments
it accumulates tombstone entries over time.

### Implementation Steps

- [ ] **2.5.1** Add a periodic shrink task: after each request completes and removes
  its entry, check `map.len() < map.capacity() / 4` and call `shrink_to_fit()`.
- [ ] **2.5.2** Alternative: replace with a bounded LRU (`lru` crate, capacity =
  `max_connections * 2`) so capacity is implicitly bounded.
- [ ] **2.5.3** Add metric: expose `REQUEST_CONTEXTS.len()` via health endpoint or
  log it periodically.
