use bumpalo::Bump;
use std::cell::RefCell;

thread_local! {
    /// Thread-local arena for fast allocations
    static THREAD_ARENA: RefCell<ThreadArena> = RefCell::new(ThreadArena::new());
}

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
}

impl Default for ThreadArena {
    fn default() -> Self {
        Self::new()
    }
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
