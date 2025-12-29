//! Thread-local arena allocator for fast per-request allocations.

use bumpalo::Bump;
use std::cell::RefCell;

thread_local! {
    /// Thread-local arena for fast allocations
    static THREAD_ARENA: RefCell<ThreadArena> = RefCell::new(ThreadArena::new());
}

/// Arena allocator for per-request allocations.
///
/// Provides O(1) allocation and batch deallocation by resetting
/// the entire arena after each request.
pub struct ThreadArena {
    arena: Bump,
    allocation_count: usize,
    bytes_allocated: usize,
}

impl ThreadArena {
    pub fn new() -> Self {
        Self {
            arena: Bump::with_capacity(64 * 1024), // 64KB initial
            allocation_count: 0,
            bytes_allocated: 0,
        }
    }

    /// Allocate bytes in the arena
    pub fn alloc_bytes(&mut self, size: usize) -> &mut [u8] {
        self.allocation_count += 1;
        self.bytes_allocated += size;
        self.arena.alloc_slice_fill_default(size)
    }

    /// Allocate a string in the arena
    pub fn alloc_str(&mut self, s: &str) -> &str {
        self.allocation_count += 1;
        self.bytes_allocated += s.len();
        self.arena.alloc_str(s)
    }

    /// Reset the arena, deallocating all memory at once
    pub fn reset(&mut self) {
        self.arena.reset();
        self.allocation_count = 0;
        self.bytes_allocated = 0;
    }

    /// Get allocation statistics
    pub fn stats(&self) -> ArenaStats {
        ArenaStats {
            allocation_count: self.allocation_count,
            bytes_allocated: self.bytes_allocated,
            capacity: self.arena.chunk_capacity(),
        }
    }
}

impl Default for ThreadArena {
    fn default() -> Self {
        Self::new()
    }
}

/// Arena allocation statistics
#[derive(Debug, Clone, Default)]
pub struct ArenaStats {
    pub allocation_count: usize,
    pub bytes_allocated: usize,
    pub capacity: usize,
}

/// Execute a closure with access to the thread-local arena
pub fn with_arena<F, R>(f: F) -> R
where
    F: FnOnce(&mut ThreadArena) -> R,
{
    THREAD_ARENA.with(|arena| f(&mut arena.borrow_mut()))
}

/// Reset the thread-local arena
pub fn reset_arena() {
    THREAD_ARENA.with(|arena| arena.borrow_mut().reset());
}

/// Get thread-local arena statistics
pub fn arena_stats() -> ArenaStats {
    THREAD_ARENA.with(|arena| arena.borrow().stats())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_arena_allocation() {
        let mut arena = ThreadArena::new();

        let bytes = arena.alloc_bytes(100);
        assert_eq!(bytes.len(), 100);

        let s = arena.alloc_str("hello world");
        assert_eq!(s, "hello world");

        let stats = arena.stats();
        assert_eq!(stats.allocation_count, 2);
        assert_eq!(stats.bytes_allocated, 100 + 11);
    }

    #[test]
    fn test_arena_reset() {
        let mut arena = ThreadArena::new();

        arena.alloc_bytes(1000);
        assert_eq!(arena.stats().bytes_allocated, 1000);

        arena.reset();
        assert_eq!(arena.stats().bytes_allocated, 0);
        assert_eq!(arena.stats().allocation_count, 0);
    }

    #[test]
    fn test_with_arena() {
        with_arena(|arena| {
            let bytes = arena.alloc_bytes(50);
            assert_eq!(bytes.len(), 50);
        });

        reset_arena();

        let stats = arena_stats();
        assert_eq!(stats.bytes_allocated, 0);
    }
}
