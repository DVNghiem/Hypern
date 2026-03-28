# Phase 1 — Correctness & Developer Experience

**Goal:** Fix known correctness issues and bring developer tooling up to standard.
No blockers — all items are self-contained.

---

## 1.1 True Streaming SSE

**Priority:** P0 — correctness bug  
**Files:** `src/http/streaming.rs`, `src/http/response.rs`, `hypern/application.py`

### Problem
`Response.sse_stream(generator)` collects **all** generator events into memory before
writing them to the response body. This breaks long-lived SSE streams (e.g. LLM token
streaming, live data feeds).

### Implementation Steps

- [ ] **1.1.1** Add a `StreamingBody` variant to `ResponseSlot` that holds an
  `mpsc::Receiver<Bytes>` instead of a `Vec<u8>`.
- [ ] **1.1.2** In `response.rs`, add `Response::sse_stream_live(generator: PyObject)`
  that:
  1. Creates an `mpsc::channel<Bytes>`.
  2. Spawns a Tokio task that iterates the Python generator (via `GILPool`), formats
     each event with `SSEEvent::format()`, and sends bytes into the channel.
  3. Stores the `Receiver` end in `ResponseSlot`.
- [ ] **1.1.3** In `ResponseSlot::into_response()` detect the `StreamingBody` variant
  and build an `axum::body::Body::from_stream(ReceiverStream)`.
- [ ] **1.1.4** Set `Transfer-Encoding: chunked` and remove explicit `Content-Length`
  for streaming responses.
- [ ] **1.1.5** Update Python `Response.sse_stream` docstring and keep the old
  `sse_stream` behaviour under `sse_collect` for backwards compatibility.
- [ ] **1.1.6** Add test: `tests/test_sse.py` — assert events are delivered before
  generator is exhausted (use a `threading.Event` to pause the generator mid-way and
  check response bytes so far).

### Key Structs / Types
```rust
// src/http/response.rs
enum BodyKind {
    Buffered(Vec<u8>),
    Streaming(tokio::sync::mpsc::Receiver<bytes::Bytes>),
}
```

---

## 1.2 Complete `_hypern.pyi` Type Stubs

**Priority:** P1 — developer experience  
**Files:** `hypern/_hypern.pyi`

### Problem
The `Request` class stub is `pass` — no method signatures. All Rust-exposed types
(`Request`, `Response`, `Context`, `DIContainer`, `TaskExecutor`, `BlockingExecutor`,
`FormData`, `UploadedFile`, `HeaderMap`) lack complete stubs.

### Implementation Steps

- [ ] **1.2.1** Audit all `#[pyclass]` types in `src/` and list every `#[pymethods]`
  exported method/property.
- [ ] **1.2.2** Write stub for `Request`:
  ```python
  class Request:
      url: str
      method: str
      path_params: dict[str, str]
      query_params: dict[str, str]
      headers: HeaderMap
      body: bytes
      def json(self) -> Any: ...
      def text(self) -> str: ...
      def form_data(self) -> FormData: ...
      def ip(self) -> str | None: ...
  ```
- [ ] **1.2.3** Write stubs for `Response` (all chainable methods, matching
  `response.rs` `#[pymethods]`).
- [ ] **1.2.4** Write stubs for `Context`, `DIContainer`, `TaskExecutor`,
  `BlockingExecutor`, `FormData`, `UploadedFile`, `HeaderMap`.
- [ ] **1.2.5** Write stubs for realtime types: `RealtimeBroadcast`, `ChannelManager`,
  `PresenceTracker`, `HeartbeatMonitor`.
- [ ] **1.2.6** Add `py.typed` marker (already exists — verify it's included in wheel).
- [ ] **1.2.7** Run `pyright` / `mypy` against `tests/` and fix any type errors surfaced.

---

## 1.3 Fix DI Wiring in CLI Scaffolding Templates

**Priority:** P2 — developer experience  
**Files:** `hypern/cli/scaffolding/layered.py`, `hexagonal.py`, `ddd.py`, `cqrs.py`

### Problem
All four templates contain `# TODO: inject ... via DI` comments in generated handler
functions. The generated project compiles but DI is non-functional out of the box.

### Implementation Steps

- [ ] **1.3.1** In `layered.py`: replace placeholder with actual
  `@inject("example_service")` decorator and matching `app.singleton(...)` call in
  the generated `main.py`.
- [ ] **1.3.2** In `hexagonal.py`: wire `ExampleUseCase` with `@inject("use_case")`.
- [ ] **1.3.3** In `ddd.py`: wire domain use case with `@inject("example_use_case")`.
- [ ] **1.3.4** In `cqrs.py`: wire `QueryHandler` and `CommandHandler` separately.
- [ ] **1.3.5** Add a smoke test: `hypern new tmp_project --template=layered` in a
  temp dir, import the generated `main.py`, confirm no import errors and all routes
  are registered.
- [ ] **1.3.6** Delete the `# TODO` comments from all generated template strings.

---

## 1.4 `hypern routes` CLI Command

**Priority:** P2 — developer experience  
**Files:** `hypern/cli/main.py`, `hypern/application.py`

### Problem
No way to inspect registered routes without running the server.

### Implementation Steps

- [ ] **1.4.1** Add `app.get_routes() -> list[dict]` Python method that returns
  `[{"method": "GET", "path": "/users/{id}", "handler": "get_user"}]`.
- [ ] **1.4.2** In Rust `Router`, expose `routes()` that iterates each method's
  `matchit::Router` and collects `(path, handler_name)` pairs.
- [ ] **1.4.3** Add `hypern routes` Typer command that imports the user's app module
  (similar to how `hypern run` resolves `app:app`) and calls `app.get_routes()`.
- [ ] **1.4.4** Output as rich table (method coloured by verb, path, handler name).
- [ ] **1.4.5** Add `--json` flag for machine-readable output.
- [ ] **1.4.6** Document in `docs/cli.md`.
