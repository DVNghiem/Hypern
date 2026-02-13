# Performance Optimization Plan for Hypern Database Module

## Overview

This document outlines identified performance bottlenecks and a prioritized plan for optimization.

## Critical Issues (P0)

### 1. Blocking Operations in Database Session Methods

**Location:** `src/database/request_context.rs:326-410`

**Issue:** Every `DbSession` method (`begin()`, `commit()`, `rollback()`, `query()`, `execute()`) uses `get_db_runtime().block_on()` to bridge async Rust code with sync Python. This blocks the calling thread completely.

**Impact:** Thread starvation under load when many requests wait on database I/O.

**Recommendation:**
- Consider exposing async Python methods using `pyo3-asyncio` for future_into_py pattern
- For now, the blocking approach is acceptable for synchronous Python handlers
- Consider implementing a connection-per-thread model for better thread utilization

**Estimated Effort:** High (requires architectural changes)

### 2. Multiple Sequential Mutex Locks in Hot Path

**Location:** `src/database/request_context.rs:259-261`

**Issue:** Three separate mutex locks are acquired sequentially in `finalize()` and other methods.

```rust
let in_tx = *self.in_transaction.lock().unwrap();
let has_error = *self.has_error.lock().unwrap();
let auto_commit = *self.auto_commit.lock().unwrap();
```

**Recommendation:** Consolidate state into a single struct protected by one mutex:

```rust
struct ContextState {
    state: ContextState,
    auto_commit: bool,
    has_error: bool,
    in_transaction: bool,
}
inner_state: Mutex<InnerState>,
```

**Estimated Effort:** Medium

### 3. Connection Take/Put Pattern Causes Lock Churn

**Location:** `src/database/request_context.rs:162-167`

**Issue:** Every database operation acquires the connection mutex twice (take + put).

**Recommendation:** Use a `MutexGuard` pattern to hold lock for the duration:

```rust
let guard = self.connection.lock().unwrap();
if let Some(conn) = guard.as_ref() {
    conn.execute("BEGIN", &[]).await?;
}
```

**Estimated Effort:** Medium

## High Priority Issues (P1)

### 4. RowStream Iterator Uses block_on

**Location:** `src/database/operation.rs:43-50`

**Issue:** Each call to `__next__` triggers 3 `block_on` calls for tokio async mutexes.

**Recommendation:** Use `std::sync` primitives instead of tokio async mutexes:

```rust
struct RowStream {
    chunks: Vec<Vec<Py<PyAny>>>,
    current_index: AtomicUsize,
    exhausted: AtomicBool,
}
```

**Estimated Effort:** Low-Medium

### 5. Duplicate Runtime for Database

**Location:** `src/database/pool.rs:13-21`

**Issue:** A separate 4-thread runtime is created for database operations, in addition to the main application runtime.

**Recommendation:** Share the existing global runtime from `src/core/global.rs`:

```rust
// Use the global runtime instead of creating a new one
pub fn get_db_runtime() -> &'static tokio::runtime::Runtime {
    get_global_runtime().inner
}
```

**Estimated Effort:** Low (but requires careful testing)

## Medium Priority Issues (P2)

### 6. SQL String Cloning

**Location:** `src/database/request_context.rs:361`

**Issue:** SQL strings are cloned to `String` even when they could be borrowed.

**Recommendation:** Use `&str` or `Cow<str>` where possible.

**Estimated Effort:** Low

### 7. Parameter Vector Allocation

**Location:** `src/database/request_context.rs:221`

**Issue:** Creates a new `Vec` of trait object references for every query.

**Recommendation:** Use `SmallVec<[&dyn ToSql; 8]>` for small parameter counts.

**Estimated Effort:** Low

### 8. DashMap Memory Never Shrinks

**Location:** `src/database/request_context.rs:39`

**Issue:** The `REQUEST_CONTEXTS` DashMap grows but never shrinks.

**Recommendation:** Periodically call `shrink_to_fit()` or use LRU cache.

**Estimated Effort:** Low

## Low Priority Issues (P3)

### 9. Import in Finally Block

**Location:** `hypern/application.py:753-761`

**Issue:** Import statements execute on every request.

**Status:** **FIXED** - Moved imports to module level.

### 10. Connection Drop Spawns Task

**Location:** `src/database/request_context.rs:278-284`

**Issue:** Every request spawns a task just to drop the connection.

**Recommendation:** Drop connection synchronously or batch returns.

**Estimated Effort:** Low

## Implementation Order

1. **Phase 1 (Quick Wins):**
   - Fix import in finally block (done)
   - Fix RowStream iterator to use std::sync
   - Add SmallVec for parameters

2. **Phase 2 (Medium Effort):**
   - Consolidate mutex locks into single state struct
   - Fix take/put pattern to use guards
   - Share runtime with global

3. **Phase 3 (Architecture):**
   - Consider async Python bindings for database operations
   - Implement connection pooling per-thread model

## Benchmarks to Run

Before and after each optimization:

1. **Single request latency:** Time for single `/health` DB query
2. **Concurrent throughput:** Requests/sec at 100 concurrent connections
3. **Memory usage:** RSS under sustained load
4. **Connection pool efficiency:** Pool utilization under various loads

## Notes

- The lazy database initialization fix ensures each forked worker process creates its own connection pool, which is correct for the multiprocess architecture.
- The auto-finalization of database connections ensures connections are returned to the pool even if handlers forget to call `finalize_db()`.
- Current performance is likely acceptable for most use cases; these optimizations are for high-load scenarios.
