# Hypern — Feature Roadmap

This folder contains phased implementation plans for new features and improvements.

## Phases

| Phase | Theme | Files |
|-------|-------|-------|
| [Phase 1](phase1-correctness-and-dx.md) | Correctness & Developer Experience | `phase1-correctness-and-dx.md` |
| [Phase 2](phase2-performance-and-rust-core.md) | Performance & Rust Core | `phase2-performance-and-rust-core.md` |
| [Phase 3](phase3-new-capabilities.md) | New Capabilities | `phase3-new-capabilities.md` |
| [Phase 4](phase4-ecosystem-and-future.md) | Ecosystem & Future | `phase4-ecosystem-and-future.md` |

## Quick Reference

```
plan/
├── README.md                       ← this file
├── phase1-correctness-and-dx.md    ← Streaming SSE fix, type stubs, CLI DI wiring
├── phase2-performance-and-rust-core.md ← Rust WebSocket, DB async, static files
├── phase3-new-capabilities.md      ← HTTP client, JWT RS256, Metrics, Pydantic
└── phase4-ecosystem-and-future.md  ← GraphQL, Redis, gRPC, multi-tenancy
```

## Dependency Graph

```
Phase 1 (no blockers)
   ↓
Phase 2 (depends on Phase 1 type stubs being done)
   ↓
Phase 3 (depends on Phase 2 DB async, Rust WS)
   ↓
Phase 4 (depends on Phase 3 HTTP client, Redis)
```

## Status Legend

- `[ ]` Not started
- `[~]` In progress
- `[x]` Done
- `[!]` Blocked
